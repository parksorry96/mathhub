from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from app.config import (
    get_ai_api_base_url,
    get_ai_api_key,
    get_ai_model,
    get_mathpix_app_id,
    get_mathpix_app_key,
    get_mathpix_base_url,
)
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
    OCRJobListItem,
    OCRJobListResponse,
    OCRJobMaterializeProblemsRequest,
    OCRJobMaterializeProblemsResponse,
    OCRJobMathpixSubmitRequest,
    OCRJobMathpixSubmitResponse,
    OCRJobMathpixSyncRequest,
    OCRJobMathpixSyncResponse,
)
from app.services.ai_classifier import classify_candidate, extract_problem_candidates
from app.services.mathpix_client import (
    extract_mathpix_pages,
    fetch_mathpix_pdf_status,
    map_mathpix_job_status,
    resolve_provider_job_id,
    submit_mathpix_pdf,
)

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


def _resolve_mathpix_credentials(
    *,
    app_id: str | None,
    app_key: str | None,
    base_url: str | None,
) -> tuple[str, str, str]:
    resolved_app_id = app_id or get_mathpix_app_id()
    resolved_app_key = app_key or get_mathpix_app_key()
    resolved_base_url = base_url or get_mathpix_base_url()

    if not resolved_app_id or not resolved_app_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mathpix credentials missing: provide app_id/app_key or set MATHPIX_APP_ID/MATHPIX_APP_KEY",
        )
    return resolved_app_id, resolved_app_key, resolved_base_url


@router.get("", response_model=OCRJobListResponse)
def list_ocr_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
) -> OCRJobListResponse:
    allowed_statuses = {"queued", "uploading", "processing", "completed", "failed", "cancelled"}
    if status_filter and status_filter not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be one of queued, uploading, processing, completed, failed, cancelled",
        )

    where_clauses: list[str] = []
    params: list = []

    if status_filter:
        where_clauses.append("j.status::text = %s")
        params.append(status_filter)
    if q:
        where_clauses.append(
            "(d.original_filename ILIKE %s OR d.storage_key ILIKE %s OR COALESCE(j.provider_job_id, '') ILIKE %s)"
        )
        q_value = f"%{q.strip()}%"
        params.extend([q_value, q_value, q_value])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    j.id,
                    j.document_id,
                    j.provider,
                    j.provider_job_id,
                    j.status::text AS status,
                    j.progress_pct,
                    j.error_message,
                    j.requested_at,
                    j.started_at,
                    j.finished_at,
                    d.storage_key,
                    d.original_filename,
                    COALESCE(pg.total_pages, 0) AS total_pages,
                    COALESCE(pg.processed_pages, 0) AS processed_pages
                FROM ocr_jobs j
                JOIN ocr_documents d ON d.id = j.document_id
                LEFT JOIN LATERAL (
                    SELECT
                        COUNT(*)::int AS total_pages,
                        COUNT(*) FILTER (
                            WHERE p.extracted_text IS NOT NULL
                               OR p.extracted_latex IS NOT NULL
                               OR p.status = 'completed'
                        )::int AS processed_pages
                    FROM ocr_pages p
                    WHERE p.job_id = j.id
                ) pg ON TRUE
                {where_sql}
                ORDER BY j.requested_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM ocr_jobs j
                JOIN ocr_documents d ON d.id = j.document_id
                {where_sql}
                """,
                tuple(params),
            )
            total_row = cur.fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            cur.execute(
                f"""
                SELECT
                    j.status::text AS status,
                    COUNT(*) AS cnt
                FROM ocr_jobs j
                JOIN ocr_documents d ON d.id = j.document_id
                {where_sql}
                GROUP BY j.status::text
                """,
                tuple(params),
            )
            status_rows = cur.fetchall()

    status_counts = {key: 0 for key in allowed_statuses}
    for row in status_rows:
        key = row["status"]
        if key in status_counts:
            status_counts[key] = int(row["cnt"])

    items = [OCRJobListItem(**row) for row in rows]
    return OCRJobListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        status_counts=status_counts,
    )


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


@router.post("/{job_id}/mathpix/submit", response_model=OCRJobMathpixSubmitResponse)
def submit_ocr_job_to_mathpix(
    job_id: UUID,
    payload: OCRJobMathpixSubmitRequest,
) -> OCRJobMathpixSubmitResponse:
    app_id, app_key, base_url = _resolve_mathpix_credentials(
        app_id=payload.app_id,
        app_key=payload.app_key,
        base_url=payload.base_url,
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, j.provider, j.provider_job_id, j.requested_at, j.started_at, d.storage_key
                FROM ocr_jobs j
                JOIN ocr_documents d ON d.id = j.document_id
                WHERE j.id = %s
                """,
                (str(job_id),),
            )
            job = cur.fetchone()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OCR job not found: {job_id}",
            )
        if job["provider"] != "mathpix":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only provider=mathpix jobs are supported, current provider={job['provider']}",
            )
        if job["provider_job_id"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"provider_job_id already exists: {job['provider_job_id']}",
            )

        file_url = payload.file_url or job["storage_key"]
        if not isinstance(file_url, str) or not file_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="file_url is required (or storage_key must contain URL)",
            )

        try:
            submit_result = submit_mathpix_pdf(
                file_url=file_url,
                app_id=app_id,
                app_key=app_key,
                base_url=base_url,
                callback_url=payload.callback_url,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Mathpix submit request failed: {exc}",
            ) from exc

        provider_job_id = resolve_provider_job_id(submit_result)
        if not provider_job_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Mathpix submit response missing job id (expected pdf_id/id/job_id/request_id)",
            )

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ocr_jobs
                    SET
                        provider_job_id = %s,
                        status = 'processing',
                        progress_pct = 5,
                        started_at = COALESCE(started_at, NOW()),
                        error_code = NULL,
                        error_message = NULL,
                        raw_response = COALESCE(raw_response, '{}'::jsonb)
                            || jsonb_build_object('mathpix_submit', %s::jsonb)
                    WHERE id = %s
                    RETURNING id, provider_job_id, status::text AS status, progress_pct, requested_at, started_at
                    """,
                    (
                        provider_job_id,
                        Json(_json_ready(submit_result)),
                        str(job_id),
                    ),
                )
                updated = cur.fetchone()
            conn.commit()
        except UniqueViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="provider_job_id already exists on another job",
            ) from exc

    return OCRJobMathpixSubmitResponse(
        job_id=updated["id"],
        provider_job_id=updated["provider_job_id"],
        status=updated["status"],
        progress_pct=updated["progress_pct"],
        requested_at=updated["requested_at"],
        started_at=updated["started_at"],
    )


@router.post("/{job_id}/mathpix/sync", response_model=OCRJobMathpixSyncResponse)
def sync_ocr_job_with_mathpix(
    job_id: UUID,
    payload: OCRJobMathpixSyncRequest,
) -> OCRJobMathpixSyncResponse:
    app_id, app_key, base_url = _resolve_mathpix_credentials(
        app_id=payload.app_id,
        app_key=payload.app_key,
        base_url=payload.base_url,
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, provider, provider_job_id
                FROM ocr_jobs
                WHERE id = %s
                """,
                (str(job_id),),
            )
            job = cur.fetchone()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OCR job not found: {job_id}",
            )
        if job["provider"] != "mathpix":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only provider=mathpix jobs are supported, current provider={job['provider']}",
            )
        provider_job_id = job["provider_job_id"]
        if not provider_job_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_job_id is empty. submit the job to Mathpix first.",
            )

        try:
            status_result = fetch_mathpix_pdf_status(
                provider_job_id=provider_job_id,
                app_id=app_id,
                app_key=app_key,
                base_url=base_url,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Mathpix status request failed: {exc}",
            ) from exc

        mapped_status, progress_pct, error_message = map_mathpix_job_status(status_result)
        pages = extract_mathpix_pages(status_result)
        pages_upserted = 0

        with conn.cursor() as cur:
            for page in pages:
                cur.execute(
                    """
                    INSERT INTO ocr_pages (
                        job_id,
                        page_no,
                        status,
                        extracted_text,
                        extracted_latex,
                        raw_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (job_id, page_no) DO UPDATE
                    SET
                        status = EXCLUDED.status,
                        extracted_text = COALESCE(EXCLUDED.extracted_text, ocr_pages.extracted_text),
                        extracted_latex = COALESCE(EXCLUDED.extracted_latex, ocr_pages.extracted_latex),
                        raw_payload = COALESCE(ocr_pages.raw_payload, '{}'::jsonb) || EXCLUDED.raw_payload,
                        updated_at = NOW()
                    """,
                    (
                        str(job_id),
                        page["page_no"],
                        mapped_status,
                        page["extracted_text"],
                        page["extracted_latex"],
                        Json(_json_ready(page["raw_payload"])),
                    ),
                )
                pages_upserted += 1

            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    status = %s,
                    progress_pct = %s,
                    error_code = CASE WHEN %s::text IS NULL THEN NULL ELSE 'MATHPIX_ERROR' END,
                    error_message = %s::text,
                    finished_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE finished_at END,
                    raw_response = COALESCE(raw_response, '{}'::jsonb)
                        || jsonb_build_object('mathpix_status', %s::jsonb)
                WHERE id = %s
                RETURNING id, provider_job_id, status::text AS status, progress_pct
                """,
                (
                    mapped_status,
                    progress_pct,
                    error_message,
                    error_message,
                    mapped_status,
                    Json(_json_ready(status_result)),
                    str(job_id),
                ),
            )
            updated_job = cur.fetchone()
        conn.commit()

    return OCRJobMathpixSyncResponse(
        job_id=updated_job["id"],
        provider_job_id=updated_job["provider_job_id"],
        status=updated_job["status"],
        progress_pct=updated_job["progress_pct"],
        pages_upserted=pages_upserted,
        error_message=error_message,
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

                # OCR candidate numbers are page-local and can collide across pages,
                # so keep source_problem_no NULL unless explicitly curated later.
                source_problem_no = None
                source_problem_label = f"P{page_no}-C{candidate_no}"

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
