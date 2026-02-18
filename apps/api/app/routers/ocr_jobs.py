from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from app.config import get_ai_api_base_url, get_ai_api_key, get_ai_model
from app.db import get_db_connection
from app.schemas.ocr_jobs import (
    AICandidateClassification,
    AIPageClassification,
    MaterializedProblemResult,
    OCRDocumentSummary,
    OCRJobAIClassifyRequest,
    OCRJobAIClassifyResponse,
    OCRJobCreateRequest,
    OCRJobCreateResponse,
    OCRJobDetailResponse,
    OCRJobMaterializeProblemsRequest,
    OCRJobMaterializeProblemsResponse,
)
from app.services.ai_classifier import classify_candidate, extract_problem_candidates

router = APIRouter(prefix="/ocr/jobs", tags=["ocr-jobs"])


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


@router.post("", response_model=OCRJobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_ocr_job(payload: OCRJobCreateRequest) -> OCRJobCreateResponse:
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ocr_documents (
                        storage_key,
                        original_filename,
                        mime_type,
                        file_size_bytes,
                        sha256
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (sha256) DO NOTHING
                    RETURNING id
                    """,
                    (
                        payload.storage_key,
                        payload.original_filename,
                        payload.mime_type,
                        payload.file_size_bytes,
                        payload.sha256,
                    ),
                )
                row = cur.fetchone()

                if row:
                    document_id = row["id"]
                else:
                    cur.execute(
                        "SELECT id FROM ocr_documents WHERE sha256 = %s",
                        (payload.sha256,),
                    )
                    existing = cur.fetchone()
                    if not existing:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to resolve OCR document",
                        )
                    document_id = existing["id"]

                cur.execute(
                    """
                    INSERT INTO ocr_jobs (
                        document_id,
                        provider,
                        status,
                        progress_pct
                    )
                    VALUES (%s, %s, 'queued', 0)
                    RETURNING id, document_id, provider, status::text AS status, progress_pct, requested_at
                    """,
                    (document_id, payload.provider),
                )
                job = cur.fetchone()

            conn.commit()
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="storage_key or provider_job_id already exists",
        ) from exc

    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create OCR job",
        )

    return OCRJobCreateResponse(**job)


@router.get("/{job_id}", response_model=OCRJobDetailResponse)
def get_ocr_job(job_id: UUID) -> OCRJobDetailResponse:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    j.id,
                    j.document_id,
                    j.provider,
                    j.provider_job_id,
                    j.status::text AS status,
                    j.progress_pct,
                    j.error_code,
                    j.error_message,
                    j.requested_at,
                    j.started_at,
                    j.finished_at,
                    d.id AS doc_id,
                    d.storage_key,
                    d.original_filename,
                    d.mime_type,
                    d.file_size_bytes,
                    d.sha256,
                    d.created_at AS document_created_at
                FROM ocr_jobs j
                JOIN ocr_documents d ON d.id = j.document_id
                WHERE j.id = %s
                """,
                (str(job_id),),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR job not found: {job_id}",
        )

    document = OCRDocumentSummary(
        id=row["doc_id"],
        storage_key=row["storage_key"],
        original_filename=row["original_filename"],
        mime_type=row["mime_type"],
        file_size_bytes=row["file_size_bytes"],
        sha256=row["sha256"],
        created_at=row["document_created_at"],
    )

    return OCRJobDetailResponse(
        id=row["id"],
        document_id=row["document_id"],
        provider=row["provider"],
        provider_job_id=row["provider_job_id"],
        status=row["status"],
        progress_pct=row["progress_pct"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        requested_at=row["requested_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        document=document,
    )


@router.post("/{job_id}/ai-classify", response_model=OCRJobAIClassifyResponse)
def classify_ocr_job(job_id: UUID, payload: OCRJobAIClassifyRequest) -> OCRJobAIClassifyResponse:
    api_key = payload.api_key or get_ai_api_key()
    api_base_url = payload.api_base_url or get_ai_api_base_url()
    model = payload.model or get_ai_model()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status::text AS status FROM ocr_jobs WHERE id = %s",
                (str(job_id),),
            )
            job = cur.fetchone()
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"OCR job not found: {job_id}",
                )

            cur.execute(
                """
                SELECT id, page_no, extracted_text, extracted_latex, raw_payload
                FROM ocr_pages
                WHERE job_id = %s
                ORDER BY page_no
                LIMIT %s
                """,
                (str(job_id), payload.max_pages),
            )
            pages = cur.fetchall()

        if not pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No OCR pages available for AI classification",
            )

        page_results: list[AIPageClassification] = []
        candidates_processed = 0
        candidates_accepted = 0
        api_candidates = 0

        for page in pages:
            page_text = (page.get("extracted_text") or page.get("extracted_latex") or "").strip()
            candidates = extract_problem_candidates(page_text)
            classified_candidates: list[AICandidateClassification] = []

            for candidate in candidates:
                classified = classify_candidate(
                    statement_text=candidate["statement_text"],
                    api_key=api_key,
                    api_base_url=api_base_url,
                    model=model,
                )

                confidence = Decimal(str(classified["confidence"]))
                if confidence >= payload.min_confidence:
                    candidates_accepted += 1

                candidate_out = AICandidateClassification(
                    candidate_no=candidate["candidate_no"],
                    statement_text=candidate["statement_text"],
                    subject_code=classified["subject_code"],
                    unit_code=classified["unit_code"],
                    point_value=classified["point_value"],
                    source_category=classified["source_category"],
                    source_type=classified["source_type"],
                    validation_status=classified["validation_status"],
                    confidence=confidence,
                    reason=classified["reason"],
                    provider=classified["provider"],
                    model=classified["model"],
                )
                classified_candidates.append(candidate_out)
                candidates_processed += 1
                if candidate_out.provider == "api":
                    api_candidates += 1

            page_result = AIPageClassification(
                page_id=page["id"],
                page_no=page["page_no"],
                candidate_count=len(classified_candidates),
                candidates=classified_candidates,
            )
            page_results.append(page_result)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ocr_pages
                    SET
                        raw_payload = COALESCE(raw_payload, '{}'::jsonb)
                            || jsonb_build_object('ai_classification', %s::jsonb),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (Json(_json_ready(page_result.model_dump())), str(page["id"])),
                )

        final_provider = "api" if api_candidates > 0 else "heuristic"

        summary_payload = {
            "provider": final_provider,
            "model": model,
            "pages_processed": len(page_results),
            "candidates_processed": candidates_processed,
            "candidates_accepted": candidates_accepted,
        }

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ocr_jobs
                SET raw_response = COALESCE(raw_response, '{}'::jsonb)
                    || jsonb_build_object('ai_classification', %s::jsonb)
                WHERE id = %s
                """,
                (Json(summary_payload), str(job_id)),
            )

        conn.commit()

    return OCRJobAIClassifyResponse(
        job_id=job_id,
        provider=final_provider,
        model=model,
        pages_processed=len(page_results),
        candidates_processed=candidates_processed,
        candidates_accepted=candidates_accepted,
        page_results=page_results,
    )


@router.post("/{job_id}/materialize-problems", response_model=OCRJobMaterializeProblemsResponse)
def materialize_ocr_job_problems(
    job_id: UUID,
    payload: OCRJobMaterializeProblemsRequest,
) -> OCRJobMaterializeProblemsResponse:
    allowed_response_types = {"five_choice", "short_answer"}
    if payload.default_response_type not in allowed_response_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_response_type must be one of five_choice, short_answer",
        )
    if payload.default_response_type == "five_choice" and payload.default_answer_key not in {"1", "2", "3", "4", "5"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="five_choice response_type requires default_answer_key in 1..5",
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM ocr_jobs WHERE id = %s", (str(job_id),))
            job = cur.fetchone()
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"OCR job not found: {job_id}",
                )

            if payload.source_id:
                cur.execute(
                    "SELECT id FROM problem_sources WHERE id = %s",
                    (str(payload.source_id),),
                )
                source_row = cur.fetchone()
                if not source_row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"problem source not found: {payload.source_id}",
                    )

            cur.execute(
                "SELECT id FROM curriculum_versions WHERE code = %s",
                (payload.curriculum_code,),
            )
            curriculum = cur.fetchone()
            if not curriculum:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"curriculum not found: {payload.curriculum_code}",
                )
            curriculum_id = curriculum["id"]

            cur.execute(
                """
                SELECT code, id
                FROM math_subjects
                WHERE curriculum_version_id = %s
                """,
                (str(curriculum_id),),
            )
            subject_rows = cur.fetchall()
            subject_id_by_code = {row["code"]: row["id"] for row in subject_rows}

            cur.execute(
                """
                SELECT s.code AS subject_code, u.code AS unit_code, u.id AS unit_id
                FROM math_units u
                JOIN math_subjects s ON s.id = u.subject_id
                WHERE s.curriculum_version_id = %s
                """,
                (str(curriculum_id),),
            )
            unit_rows = cur.fetchall()
            unit_id_by_subject_unit = {
                (row["subject_code"], row["unit_code"]): row["unit_id"]
                for row in unit_rows
            }

            cur.execute(
                """
                SELECT id, page_no, raw_payload
                FROM ocr_pages
                WHERE job_id = %s
                ORDER BY page_no
                """,
                (str(job_id),),
            )
            pages = cur.fetchall()

        if not pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No OCR pages found for this job",
            )

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        results: list[MaterializedProblemResult] = []

        for page in pages:
            page_no = page["page_no"]
            raw_payload = page.get("raw_payload") or {}
            ai_classification = raw_payload.get("ai_classification")
            if not isinstance(ai_classification, dict):
                continue

            candidates = ai_classification.get("candidates")
            if not isinstance(candidates, list):
                continue

            for index, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    skipped_count += 1
                    results.append(
                        MaterializedProblemResult(
                            page_no=page_no,
                            candidate_no=index + 1,
                            status="skipped",
                            problem_id=None,
                            external_problem_key=f"OCR:{job_id}:P{page_no}:I{index + 1}",
                            reason="candidate payload is not an object",
                        )
                    )
                    continue

                candidate_no_raw = candidate.get("candidate_no")
                try:
                    candidate_no = int(candidate_no_raw)
                except Exception:
                    candidate_no = index + 1

                candidate_index = index + 1
                external_problem_key = f"OCR:{job_id}:P{page_no}:I{candidate_index}"
                confidence = _to_decimal(candidate.get("confidence"))
                if confidence < payload.min_confidence:
                    skipped_count += 1
                    results.append(
                        MaterializedProblemResult(
                            page_no=page_no,
                            candidate_no=candidate_no,
                            status="skipped",
                            problem_id=None,
                            external_problem_key=external_problem_key,
                            reason="confidence below threshold",
                        )
                    )
                    continue

                statement_text = (candidate.get("statement_text") or "").strip()
                if not statement_text:
                    skipped_count += 1
                    results.append(
                        MaterializedProblemResult(
                            page_no=page_no,
                            candidate_no=candidate_no,
                            status="skipped",
                            problem_id=None,
                            external_problem_key=external_problem_key,
                            reason="empty statement_text",
                        )
                    )
                    continue

                subject_code = candidate.get("subject_code")
                subject_id = subject_id_by_code.get(subject_code)
                if subject_id is None:
                    skipped_count += 1
                    results.append(
                        MaterializedProblemResult(
                            page_no=page_no,
                            candidate_no=candidate_no,
                            status="skipped",
                            problem_id=None,
                            external_problem_key=external_problem_key,
                            reason="subject_code is missing or not mapped",
                        )
                    )
                    continue

                point_value = candidate.get("point_value")
                if point_value not in (2, 3, 4):
                    point_value = payload.default_point_value

                source_problem_no = candidate_no if 1 <= candidate_no <= 32767 else None
                source_problem_label = str(candidate_no)

                metadata = {
                    "needs_review": True,
                    "ingest": {
                        "source": "ocr_ai_classification",
                        "job_id": str(job_id),
                        "page_no": page_no,
                        "candidate_no": candidate_no,
                        "confidence": float(confidence),
                        "validation_status": candidate.get("validation_status"),
                        "provider": candidate.get("provider"),
                        "model": candidate.get("model"),
                        "reason": candidate.get("reason"),
                        "source_category": candidate.get("source_category"),
                        "source_type": candidate.get("source_type"),
                    },
                }

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO problems (
                            curriculum_version_id,
                            source_id,
                            ocr_page_id,
                            external_problem_key,
                            primary_subject_id,
                            response_type,
                            point_value,
                            answer_key,
                            source_problem_no,
                            source_problem_label,
                            problem_text_raw,
                            problem_text_final,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (external_problem_key) DO UPDATE
                        SET
                            source_id = COALESCE(EXCLUDED.source_id, problems.source_id),
                            ocr_page_id = EXCLUDED.ocr_page_id,
                            primary_subject_id = EXCLUDED.primary_subject_id,
                            response_type = EXCLUDED.response_type,
                            point_value = EXCLUDED.point_value,
                            answer_key = EXCLUDED.answer_key,
                            source_problem_no = EXCLUDED.source_problem_no,
                            source_problem_label = EXCLUDED.source_problem_label,
                            problem_text_raw = EXCLUDED.problem_text_raw,
                            problem_text_final = EXCLUDED.problem_text_final,
                            metadata = COALESCE(problems.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                            updated_at = NOW()
                        RETURNING id, (xmax = 0) AS inserted
                        """,
                        (
                            str(curriculum_id),
                            str(payload.source_id) if payload.source_id else None,
                            str(page["id"]),
                            external_problem_key,
                            str(subject_id),
                            payload.default_response_type,
                            point_value,
                            payload.default_answer_key,
                            source_problem_no,
                            source_problem_label,
                            statement_text,
                            statement_text,
                            Json(_json_ready(metadata)),
                        ),
                    )
                    problem_row = cur.fetchone()

                problem_id = problem_row["id"]
                was_inserted = bool(problem_row["inserted"])
                if was_inserted:
                    inserted_count += 1
                    item_status = "inserted"
                else:
                    updated_count += 1
                    item_status = "updated"

                unit_code = candidate.get("unit_code")
                unit_id = unit_id_by_subject_unit.get((subject_code, unit_code))
                if unit_id:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE problem_unit_map
                            SET is_primary = FALSE
                            WHERE problem_id = %s
                              AND is_primary = TRUE
                              AND unit_id <> %s
                            """,
                            (str(problem_id), str(unit_id)),
                        )
                        cur.execute(
                            """
                            INSERT INTO problem_unit_map (problem_id, unit_id, is_primary)
                            VALUES (%s, %s, TRUE)
                            ON CONFLICT (problem_id, unit_id) DO UPDATE
                            SET is_primary = EXCLUDED.is_primary
                            """,
                            (str(problem_id), str(unit_id)),
                        )

                results.append(
                    MaterializedProblemResult(
                        page_no=page_no,
                        candidate_no=candidate_no,
                        status=item_status,
                        problem_id=problem_id,
                        external_problem_key=external_problem_key,
                        reason=None,
                    )
                )

        conn.commit()

    return OCRJobMaterializeProblemsResponse(
        job_id=job_id,
        curriculum_code=payload.curriculum_code,
        source_id=payload.source_id,
        inserted_count=inserted_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        results=results,
    )
