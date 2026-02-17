from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg.errors import UniqueViolation

from app.db import get_db_connection
from app.schemas.ocr_jobs import (
    OCRDocumentSummary,
    OCRJobCreateRequest,
    OCRJobCreateResponse,
    OCRJobDetailResponse,
)

router = APIRouter(prefix="/ocr/jobs", tags=["ocr-jobs"])


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
