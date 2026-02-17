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
    OCRDocumentSummary,
    OCRJobAIClassifyRequest,
    OCRJobAIClassifyResponse,
    OCRJobCreateRequest,
    OCRJobCreateResponse,
    OCRJobDetailResponse,
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
