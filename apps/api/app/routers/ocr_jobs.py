from __future__ import annotations

import time as time_module
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from app.config import (
    get_gemini_base_url,
    get_gemini_api_key,
    get_gemini_preprocess_model,
    get_mathpix_app_id,
    get_mathpix_app_key,
    get_mathpix_base_url,
)
from app.db import get_db_connection
from app.schemas.ocr_jobs import (
    MaterializedProblemResult,
    OCRDocumentSummary,
    OCRJobCreateRequest,
    OCRJobCreateResponse,
    OCRJobDeleteResponse,
    OCRJobDetailResponse,
    OCRJobListItem,
    OCRJobListResponse,
    OCRJobPagesResponse,
    OCRJobQuestionsResponse,
    OCRJobWorkflowRunRequest,
    OCRJobWorkflowRunResponse,
    OCRPagePreviewItem,
    OCRQuestionAssetPreview,
    OCRQuestionPreviewItem,
)
from app.services.ai_classifier import collect_problem_asset_hints, extract_problem_candidates
from app.services.gemini_document_scanner import attach_answer_keys_to_scanned_pages, scan_pdf_document_with_gemini
from app.services.mathpix_client import (
    extract_mathpix_pages,
    extract_mathpix_pages_from_lines,
    extract_mathpix_text_fields,
    fetch_mathpix_pdf_lines,
    fetch_mathpix_pdf_status,
    map_mathpix_job_status,
    merge_mathpix_pages,
    ocr_mathpix_image,
    resolve_provider_job_id,
    submit_mathpix_pdf,
)
from app.services.problem_asset_extractor import ProblemAssetExtractor
from app.services.s3_storage import (
    build_storage_key,
    create_s3_client,
    delete_object,
    ensure_s3_bucket,
    generate_presigned_get_url,
    get_object_bytes,
    parse_storage_key,
    put_object_bytes,
)

router = APIRouter(prefix="/ocr/jobs", tags=["ocr-jobs"])
ALLOWED_ASSET_TYPES = {"image", "table", "graph", "other"}


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


def _to_optional_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _build_external_problem_key(*, job_id: UUID, page_no: int, candidate_index: int) -> str:
    return f"OCR:{job_id}:P{page_no}:I{candidate_index}"


def _resolve_asset_preview_url(storage_key: str, s3_client) -> str | None:
    if not storage_key.startswith("s3://") or s3_client is None:
        return None
    try:
        bucket, key = parse_storage_key(storage_key)
        return generate_presigned_get_url(client=s3_client, bucket=bucket, key=key, expires_in=1800)
    except Exception:
        return None


def _load_materialized_asset_preview_map(job_id: UUID) -> dict[str, list[OCRQuestionAssetPreview]]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.external_problem_key,
                    pa.asset_type::text AS asset_type,
                    pa.storage_key,
                    pa.page_no,
                    pa.bbox
                FROM problems p
                JOIN problem_assets pa ON pa.problem_id = p.id
                WHERE p.external_problem_key LIKE %s
                ORDER BY pa.created_at ASC
                """,
                (f"OCR:{job_id}:%",),
            )
            rows = cur.fetchall()

    if not rows:
        return {}

    try:
        s3_client = create_s3_client()
    except Exception:
        s3_client = None

    mapped: dict[str, list[OCRQuestionAssetPreview]] = {}
    for row in rows:
        key = row["external_problem_key"]
        if not key:
            continue
        previews = mapped.setdefault(key, [])
        storage_key = row["storage_key"]
        previews.append(
            OCRQuestionAssetPreview(
                asset_type=row["asset_type"] or "other",
                storage_key=storage_key,
                preview_url=_resolve_asset_preview_url(storage_key, s3_client),
                page_no=row["page_no"],
                bbox=row["bbox"] if isinstance(row["bbox"], dict) else None,
            )
        )
    return mapped


def _build_question_preview_items_for_page(
    *,
    job_id: UUID,
    page: dict,
    materialized_asset_map: dict[str, list[OCRQuestionAssetPreview]],
    preview_asset_extractor: ProblemAssetExtractor | None = None,
    preview_asset_s3_client=None,
) -> list[OCRQuestionPreviewItem]:
    page_text = (page.get("extracted_text") or page.get("extracted_latex") or "").strip()
    raw_payload = page.get("raw_payload")
    raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
    source_candidates = extract_problem_candidates(page_text, raw_payload if isinstance(raw_payload, dict) else None)

    items: list[OCRQuestionPreviewItem] = []
    for index, candidate in enumerate(source_candidates):
        if not isinstance(candidate, dict):
            continue

        statement_text = str(candidate.get("statement_text") or "").strip()
        if not statement_text:
            continue

        candidate_no_raw = candidate.get("candidate_no")
        try:
            candidate_no = int(candidate_no_raw)
        except Exception:
            candidate_no = index + 1

        split_strategy = str(candidate.get("split_strategy") or "").strip() or "numbered"

        candidate_bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
        asset_hints = collect_problem_asset_hints(
            statement_text,
            raw_payload,
            candidate_bbox=candidate_bbox,
            candidate_meta=candidate,
        )
        asset_types = sorted(
            {
                str(asset.get("asset_type")).strip().lower()
                for asset in asset_hints
                if str(asset.get("asset_type")).strip().lower() in ALLOWED_ASSET_TYPES
            }
        )
        candidate_index = index + 1
        external_problem_key = _build_external_problem_key(
            job_id=job_id,
            page_no=page["page_no"],
            candidate_index=candidate_index,
        )
        materialized_asset_previews = list(materialized_asset_map.get(external_problem_key) or [])
        generated_asset_previews: list[OCRQuestionAssetPreview] = []
        if (
            not materialized_asset_previews
            and preview_asset_extractor
            and preview_asset_extractor.is_available
            and asset_hints
        ):
            try:
                extracted_assets = preview_asset_extractor.extract_and_upload(
                    page_no=page["page_no"],
                    candidate_no=candidate_index,
                    external_problem_key=external_problem_key,
                    asset_hints=asset_hints,
                    candidate_bbox=candidate_bbox,
                )
                generated_asset_previews = [
                    OCRQuestionAssetPreview(
                        asset_type=extracted.asset_type,
                        storage_key=extracted.storage_key,
                        preview_url=_resolve_asset_preview_url(extracted.storage_key, preview_asset_s3_client),
                        page_no=extracted.page_no,
                        bbox=extracted.bbox if isinstance(extracted.bbox, dict) else None,
                    )
                    for extracted in extracted_assets
                ]
            except Exception:
                generated_asset_previews = []

        resolved_asset_previews = materialized_asset_previews or generated_asset_previews
        for preview in resolved_asset_previews:
            if preview.asset_type not in asset_types:
                asset_types.append(preview.asset_type)
        asset_types = sorted(set(asset_types))

        items.append(
            OCRQuestionPreviewItem(
                page_id=page["id"],
                page_no=page["page_no"],
                candidate_no=candidate_no,
                candidate_index=candidate_index,
                candidate_key=f"P{page['page_no']}-C{candidate_no}",
                external_problem_key=external_problem_key,
                split_strategy=split_strategy,
                statement_text=statement_text,
                confidence=_to_optional_decimal(candidate.get("confidence")),
                validation_status=str(candidate.get("validation_status"))
                if candidate.get("validation_status") is not None
                else None,
                provider=str(candidate.get("provider")) if candidate.get("provider") is not None else None,
                model=str(candidate.get("model")) if candidate.get("model") is not None else None,
                has_visual_asset=bool(asset_types) or bool(resolved_asset_previews),
                asset_types=asset_types,
                asset_previews=resolved_asset_previews,
                updated_at=page["updated_at"],
            )
        )

    return items


def _build_ai_preprocess_extracted_text(*, problem_items: list[dict]) -> str | None:
    # AI preprocess only segments candidates and assets. OCR text source remains Mathpix.
    del problem_items
    return None


def _resolve_problem_text_from_mathpix(*, extracted_text: str | None, extracted_latex: str | None) -> str | None:
    text = (extracted_text or "").strip()
    if text:
        return text
    latex = (extracted_latex or "").strip()
    if latex:
        return latex
    return None


def _normalize_visual_asset_types(value: object, *, has_visual_asset: bool = False) -> list[str]:
    allowed = {"image", "table", "graph", "other"}
    normalized: list[str] = []
    seen: set[str] = set()
    if isinstance(value, list):
        for item in value:
            asset_type = str(item).strip().lower()
            if not asset_type:
                continue
            if asset_type not in allowed:
                asset_type = "other"
            if asset_type in seen:
                continue
            seen.add(asset_type)
            normalized.append(asset_type)
    if not normalized and has_visual_asset:
        normalized.append("other")
    return normalized


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


def _resolve_gemini_credentials(
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    default_model: str | None = None,
) -> tuple[str, str, str]:
    resolved_api_key = api_key or get_gemini_api_key()
    resolved_base_url = base_url or get_gemini_base_url()
    resolved_model = model or default_model or get_gemini_preprocess_model()

    if not resolved_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gemini credentials missing: provide gemini_api_key or set GEMINI_API_KEY",
        )
    return resolved_api_key, resolved_base_url, resolved_model


def _resolve_mathpix_file_url(*, file_url: str | None, storage_key: str) -> str:
    candidate = (file_url or storage_key or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_url is required (or storage_key must be a valid URL/S3 key)",
        )

    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate

    if candidate.startswith("s3://"):
        try:
            bucket, key = parse_storage_key(candidate)
            s3_client = create_s3_client()
            return generate_presigned_get_url(
                client=s3_client,
                bucket=bucket,
                key=key,
                expires_in=1800,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to generate S3 presigned GET URL: {exc}",
            ) from exc

    if candidate.startswith("upload://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "legacy storage_key scheme upload:// is not supported for Mathpix submit. "
                "Re-upload the file through S3 flow and retry."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="file_url must be http(s) URL or storage_key must be s3://bucket/key",
    )


def _validate_source_category_type(source_category: str, source_type: str) -> tuple[str, str]:
    category = source_category.strip().lower()
    source = source_type.strip().lower()
    allowed_by_category = {
        "past_exam": {"csat", "kice_mock", "office_mock"},
        "linked_textbook": {"ebs_linked"},
        "other": {"private_mock", "workbook", "school_exam", "teacher_made", "other"},
    }
    allowed_types = allowed_by_category.get(category)
    if not allowed_types or source not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "invalid source_category/source_type pair. "
                "allowed: past_exam(csat,kice_mock,office_mock), "
                "linked_textbook(ebs_linked), other(private_mock,workbook,school_exam,teacher_made,other)"
            ),
        )
    return category, source


def _mark_job_failed(*, conn, job_id: UUID, error_code: str, message: str) -> None:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ocr_jobs
            SET
                status = 'failed',
                error_code = %s,
                error_message = %s,
                finished_at = NOW()
            WHERE id = %s
            """,
            (error_code, message, str(job_id)),
        )
    conn.commit()


def _poll_mathpix_until_completed(
    *,
    provider_job_id: str,
    app_id: str,
    app_key: str,
    base_url: str,
    max_polls: int,
    poll_interval_sec: float,
) -> tuple[str, Decimal, str | None, dict, list[dict]]:
    latest_status_payload: dict = {}
    latest_pages: list[dict] = []
    for _ in range(max_polls):
        status_payload = fetch_mathpix_pdf_status(
            provider_job_id=provider_job_id,
            app_id=app_id,
            app_key=app_key,
            base_url=base_url,
        )
        mapped_status, progress_pct, error_message = map_mathpix_job_status(status_payload)
        pages = extract_mathpix_pages(status_payload)
        latest_status_payload = status_payload
        latest_pages = pages

        if mapped_status == "completed":
            try:
                lines_result = fetch_mathpix_pdf_lines(
                    provider_job_id=provider_job_id,
                    app_id=app_id,
                    app_key=app_key,
                    base_url=base_url,
                )
                line_pages = extract_mathpix_pages_from_lines(lines_result)
                if line_pages:
                    latest_pages = merge_mathpix_pages(status_pages=pages, line_pages=line_pages)
            except Exception:
                pass
            return mapped_status, Decimal("100"), None, latest_status_payload, latest_pages

        if mapped_status in {"failed", "cancelled"}:
            return mapped_status, progress_pct, error_message, latest_status_payload, latest_pages

        time_module.sleep(max(0.2, poll_interval_sec))

    return (
        "failed",
        Decimal("0"),
        f"Mathpix processing timeout after {max_polls} polls",
        latest_status_payload,
        latest_pages,
    )


def _upsert_mathpix_pages(*, conn, job_id: UUID, mapped_status: str, pages: list[dict]) -> int:
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
                    page.get("extracted_text"),
                    page.get("extracted_latex"),
                    Json(_json_ready(page.get("raw_payload") or {})),
                ),
            )
            pages_upserted += 1
    return pages_upserted


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
                    CASE
                        WHEN pg.total_pages > 0 THEN pg.total_pages
                        WHEN COALESCE(j.raw_response #>> '{{mathpix_status,num_pages}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{mathpix_status,num_pages}}')::int
                        ELSE 0
                    END AS total_pages,
                    CASE
                        WHEN pg.total_pages > 0 THEN pg.processed_pages
                        WHEN COALESCE(j.raw_response #>> '{{mathpix_status,num_pages_completed}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{mathpix_status,num_pages_completed}}')::int
                        ELSE 0
                    END AS processed_pages,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{workflow,done}}', '') IN ('true', 'false')
                            THEN (j.raw_response #>> '{{workflow,done}}')::boolean
                        ELSE NULL
                    END AS ai_done,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{workflow,total_candidates}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{workflow,total_candidates}}')::int
                        ELSE NULL
                    END AS ai_total_candidates,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{workflow,processed_candidates}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{workflow,processed_candidates}}')::int
                        ELSE NULL
                    END AS ai_candidates_processed,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{workflow,accepted_candidates}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{workflow,accepted_candidates}}')::int
                        ELSE NULL
                    END AS ai_candidates_accepted,
                    NULLIF(j.raw_response #>> '{{workflow,provider}}', '') AS ai_provider,
                    NULLIF(j.raw_response #>> '{{workflow,model}}', '') AS ai_model
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
                    ON CONFLICT (sha256) DO UPDATE
                    SET
                        storage_key = EXCLUDED.storage_key,
                        original_filename = EXCLUDED.original_filename,
                        mime_type = EXCLUDED.mime_type,
                        file_size_bytes = EXCLUDED.file_size_bytes
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


@router.delete("/{job_id}", response_model=OCRJobDeleteResponse)
def delete_ocr_job(
    job_id: UUID,
    delete_source: bool = Query(default=True),
) -> OCRJobDeleteResponse:
    source_deleted = False
    should_try_source_delete = False
    storage_key = ""

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, j.document_id, d.storage_key
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

            document_id = row["document_id"]
            storage_key = row["storage_key"] or ""

            cur.execute(
                "DELETE FROM ocr_jobs WHERE id = %s RETURNING id",
                (str(job_id),),
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"OCR job not found: {job_id}",
                )

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM ocr_jobs WHERE document_id = %s",
                (str(document_id),),
            )
            remain_row = cur.fetchone()
            remaining_jobs = int(remain_row["cnt"]) if remain_row else 0

            if remaining_jobs == 0:
                cur.execute("DELETE FROM ocr_documents WHERE id = %s", (str(document_id),))
                should_try_source_delete = delete_source and storage_key.startswith("s3://")

        conn.commit()

    if should_try_source_delete:
        try:
            bucket, key = parse_storage_key(storage_key)
            client = create_s3_client()
            delete_object(client=client, bucket=bucket, key=key)
            source_deleted = True
        except Exception:
            source_deleted = False

    return OCRJobDeleteResponse(
        job_id=job_id,
        document_id=document_id,
        source_deleted=source_deleted,
    )


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


@router.get("/{job_id}/pages", response_model=OCRJobPagesResponse)
def list_ocr_job_pages(
    job_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> OCRJobPagesResponse:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id
                FROM ocr_jobs j
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

            cur.execute(
                """
                SELECT id, page_no, status::text AS status, extracted_text, extracted_latex, updated_at
                FROM ocr_pages
                WHERE job_id = %s
                ORDER BY page_no
                LIMIT %s OFFSET %s
                """,
                (str(job_id), limit, offset),
            )
            rows = cur.fetchall()

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM ocr_pages WHERE job_id = %s",
                (str(job_id),),
            )
            total_row = cur.fetchone()
            total = int(total_row["cnt"]) if total_row else 0

    items = [OCRPagePreviewItem(**row) for row in rows]
    return OCRJobPagesResponse(
        job_id=job_id,
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}/questions", response_model=OCRJobQuestionsResponse)
def list_ocr_job_questions(
    job_id: UUID,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> OCRJobQuestionsResponse:
    job_storage_key: str | None = None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, d.storage_key
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
            job_storage_key = str(job.get("storage_key") or "").strip()

            cur.execute(
                """
                SELECT id, page_no, extracted_text, extracted_latex, raw_payload, updated_at
                FROM ocr_pages
                WHERE job_id = %s
                ORDER BY page_no
                """,
                (str(job_id),),
            )
            pages = cur.fetchall()

    materialized_asset_map = _load_materialized_asset_preview_map(job_id)
    preview_asset_extractor: ProblemAssetExtractor | None = None
    preview_asset_s3_client = None
    if job_storage_key and job_storage_key.startswith("s3://"):
        try:
            source_bucket, source_key = parse_storage_key(job_storage_key)
            preview_asset_s3_client = create_s3_client()
            source_pdf_bytes = get_object_bytes(
                client=preview_asset_s3_client,
                bucket=source_bucket,
                key=source_key,
            )
            try:
                target_bucket = ensure_s3_bucket()
            except Exception:
                target_bucket = source_bucket

            preview_asset_extractor = ProblemAssetExtractor(
                pdf_bytes=source_pdf_bytes,
                s3_client=preview_asset_s3_client,
                bucket=target_bucket,
                job_id=job_id,
                prefix="ocr-preview-assets",
            )
            if not preview_asset_extractor.is_available:
                preview_asset_extractor = None
        except Exception:
            preview_asset_extractor = None
            preview_asset_s3_client = None

    all_items: list[OCRQuestionPreviewItem] = []
    try:
        for page in pages:
            all_items.extend(
                _build_question_preview_items_for_page(
                    job_id=job_id,
                    page=page,
                    materialized_asset_map=materialized_asset_map,
                    preview_asset_extractor=preview_asset_extractor,
                    preview_asset_s3_client=preview_asset_s3_client,
                )
            )
    finally:
        if preview_asset_extractor:
            preview_asset_extractor.close()
    all_items.sort(key=lambda item: (item.page_no, item.candidate_no))

    total = len(all_items)
    sliced = all_items[offset : offset + limit]
    return OCRJobQuestionsResponse(
        job_id=job_id,
        items=sliced,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{job_id}/workflow/run", response_model=OCRJobWorkflowRunResponse)
def run_ocr_job_workflow(job_id: UUID, payload: OCRJobWorkflowRunRequest) -> OCRJobWorkflowRunResponse:
    app_id, app_key, base_url = _resolve_mathpix_credentials(
        app_id=payload.app_id,
        app_key=payload.app_key,
        base_url=payload.base_url,
    )
    gemini_api_key, gemini_base_url, gemini_model = _resolve_gemini_credentials(
        api_key=payload.gemini_api_key,
        base_url=payload.gemini_base_url,
        model=payload.gemini_model,
        default_model=get_gemini_preprocess_model(),
    )
    source_category, source_type = _validate_source_category_type(payload.source_category, payload.source_type)

    if payload.default_response_type not in {"five_choice", "short_answer"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_response_type must be one of five_choice, short_answer",
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    j.id,
                    j.provider,
                    d.storage_key AS document_storage_key,
                    d.original_filename
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

            source_id: UUID | None = payload.source_id
            if source_id:
                cur.execute("SELECT id FROM problem_sources WHERE id = %s", (str(source_id),))
                source_row = cur.fetchone()
                if not source_row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"problem source not found: {source_id}",
                    )
            else:
                source_code = f"OCRBOOK:{job_id}"
                source_title = (
                    payload.textbook_title
                    or str(job.get("original_filename") or "").strip()
                    or f"OCR Job {job_id}"
                )
                cur.execute(
                    """
                    INSERT INTO problem_sources (
                        source_code,
                        source_category,
                        source_type,
                        title,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (source_code) DO UPDATE
                    SET
                        source_category = EXCLUDED.source_category,
                        source_type = EXCLUDED.source_type,
                        title = EXCLUDED.title,
                        metadata = COALESCE(problem_sources.metadata, '{}'::jsonb) || EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        source_code,
                        source_category,
                        source_type,
                        source_title,
                        Json(
                            {
                                "ingest": {
                                    "source": "workflow_run",
                                    "job_id": str(job_id),
                                }
                            }
                        ),
                    ),
                )
                source_row = cur.fetchone()
                source_id = source_row["id"] if source_row else None

            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    status = 'processing',
                    progress_pct = 2,
                    started_at = COALESCE(started_at, NOW()),
                    finished_at = NULL,
                    error_code = NULL,
                    error_message = NULL
                WHERE id = %s
                """,
                (str(job_id),),
            )
        conn.commit()

        provider = str(job.get("provider") or "mathpix")
        if provider != "mathpix":
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_PROVIDER_ERROR",
                message=f"Only provider=mathpix is supported, current provider={provider}",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only provider=mathpix is supported, current provider={provider}",
            )

        document_storage_key = str(job.get("document_storage_key") or "").strip()
        if not document_storage_key.startswith("s3://"):
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_INPUT_ERROR",
                message="workflow-run requires document storage_key in s3:// format",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workflow-run requires document storage_key in s3:// format",
            )

        try:
            source_bucket, source_key = parse_storage_key(document_storage_key)
            s3_client = create_s3_client()
            source_pdf_bytes = get_object_bytes(
                client=s3_client,
                bucket=source_bucket,
                key=source_key,
            )
            try:
                target_bucket = ensure_s3_bucket()
            except Exception:
                target_bucket = source_bucket
        except Exception as exc:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_SOURCE_READ_ERROR",
                message=f"Failed to read source PDF: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to read source PDF: {exc}",
            ) from exc

        file_url = _resolve_mathpix_file_url(file_url=None, storage_key=document_storage_key)
        try:
            submit_result = submit_mathpix_pdf(
                file_url=file_url,
                app_id=app_id,
                app_key=app_key,
                base_url=base_url,
                callback_url=None,
                include_diagram_text=payload.include_diagram_text,
            )
        except Exception as exc:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_MATHPIX_SUBMIT_ERROR",
                message=f"Mathpix submit request failed: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Mathpix submit request failed: {exc}",
            ) from exc

        provider_job_id = resolve_provider_job_id(submit_result)
        if not provider_job_id:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_MATHPIX_SUBMIT_ERROR",
                message="Mathpix submit response missing job id",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Mathpix submit response missing job id (expected pdf_id/id/job_id/request_id)",
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    provider_job_id = %s,
                    status = 'processing',
                    progress_pct = 8,
                    raw_response = COALESCE(raw_response, '{}'::jsonb)
                        || jsonb_build_object('mathpix_submit', %s::jsonb)
                WHERE id = %s
                """,
                (provider_job_id, Json(_json_ready(submit_result)), str(job_id)),
            )
        conn.commit()

        try:
            mapped_status, progress_pct, mathpix_error, status_payload, pages = _poll_mathpix_until_completed(
                provider_job_id=provider_job_id,
                app_id=app_id,
                app_key=app_key,
                base_url=base_url,
                max_polls=int(payload.max_mathpix_polls),
                poll_interval_sec=float(payload.poll_interval_sec),
            )
        except Exception as exc:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_MATHPIX_POLL_ERROR",
                message=f"Mathpix status request failed: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Mathpix status request failed: {exc}",
            ) from exc

        if mapped_status != "completed":
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_MATHPIX_FAILED",
                message=mathpix_error or "Mathpix returned non-completed status",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=mathpix_error or "Mathpix returned non-completed status",
            )

        pages_upserted = _upsert_mathpix_pages(conn=conn, job_id=job_id, mapped_status=mapped_status, pages=pages)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    status = 'processing',
                    progress_pct = %s,
                    raw_response = COALESCE(raw_response, '{}'::jsonb)
                        || jsonb_build_object('mathpix_status', %s::jsonb)
                WHERE id = %s
                """,
                (max(Decimal("25"), progress_pct), Json(_json_ready(status_payload)), str(job_id)),
            )
        conn.commit()

        try:
            scanned_pages = scan_pdf_document_with_gemini(
                pdf_bytes=source_pdf_bytes,
                api_key=gemini_api_key,
                base_url=gemini_base_url,
                model=gemini_model,
                max_pages=payload.max_pages,
                render_scale=float(payload.render_scale),
                temperature=float(payload.temperature),
                max_parallel_pages=int(payload.max_parallel_pages),
                max_output_tokens=int(payload.max_output_tokens),
                thinking_budget=(int(payload.thinking_budget) if payload.thinking_budget is not None else None),
            )
        except Exception as exc:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_AI_PREPROCESS_ERROR",
                message=f"Gemini preprocess request failed: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gemini preprocess request failed: {exc}",
            ) from exc

        matched_answers = attach_answer_keys_to_scanned_pages(scanned_pages)
        detected_problems = 0
        detected_answers = 0

        with conn.cursor() as cur:
            for scanned_page in scanned_pages:
                page_no = int(scanned_page.get("page_no") or 0)
                if page_no <= 0:
                    continue
                problems = scanned_page.get("problems")
                answers = scanned_page.get("answer_candidates")
                problem_items = problems if isinstance(problems, list) else []
                answer_items = answers if isinstance(answers, list) else []
                detected_problems += len(problem_items)
                detected_answers += len(answer_items)

                cur.execute(
                    """
                    INSERT INTO ocr_pages (
                        job_id,
                        page_no,
                        status,
                        extracted_text,
                        raw_payload
                    )
                    VALUES (%s, %s, 'processing', NULL, %s::jsonb)
                    ON CONFLICT (job_id, page_no) DO UPDATE
                    SET
                        raw_payload = COALESCE(ocr_pages.raw_payload, '{}'::jsonb) || EXCLUDED.raw_payload,
                        updated_at = NOW()
                    """,
                    (
                        str(job_id),
                        page_no,
                        Json({"ai_preprocess": _json_ready(scanned_page)}),
                    ),
                )

            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    status = 'processing',
                    progress_pct = 45,
                    raw_response = COALESCE(raw_response, '{}'::jsonb)
                        || jsonb_build_object('ai_preprocess', %s::jsonb)
                WHERE id = %s
                """,
                (
                    Json(
                        _json_ready(
                            {
                                "provider": "gemini",
                                "model": gemini_model,
                                "scanned_pages": len(scanned_pages),
                                "detected_problems": detected_problems,
                                "detected_answers": detected_answers,
                                "matched_answers": matched_answers,
                            }
                        )
                    ),
                    str(job_id),
                ),
            )
        conn.commit()

        extractor = ProblemAssetExtractor(
            pdf_bytes=source_pdf_bytes,
            s3_client=s3_client,
            bucket=target_bucket,
            job_id=job_id,
            prefix="ocr-problem-crops",
        )
        if not extractor.is_available:
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_EXTRACTOR_UNAVAILABLE",
                message="Problem OCR extractor is unavailable (PyMuPDF missing)",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Problem OCR extractor is unavailable (PyMuPDF missing)",
            )

        processed_candidates = 0
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        detected_visual_assets = 0
        stored_visual_assets = 0
        accepted_candidates = 0
        results: list[MaterializedProblemResult] = []

        detected_candidates_total = 0
        for page in scanned_pages:
            problems = page.get("problems")
            if isinstance(problems, list):
                detected_candidates_total += len(problems)
        detected_candidates_total = min(detected_candidates_total, int(payload.max_problems))
        progress_denominator = max(1, detected_candidates_total)

        try:
            for scanned_page in scanned_pages:
                if processed_candidates >= payload.max_problems:
                    break

                page_no = int(scanned_page.get("page_no") or 0)
                if page_no <= 0:
                    continue
                problems = scanned_page.get("problems")
                if not isinstance(problems, list):
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id
                        FROM ocr_pages
                        WHERE job_id = %s AND page_no = %s
                        """,
                        (str(job_id), page_no),
                    )
                    page_row = cur.fetchone()
                if not page_row:
                    continue
                ocr_page_id = page_row["id"]

                for index, candidate in enumerate(problems, start=1):
                    if processed_candidates >= payload.max_problems:
                        break
                    processed_candidates += 1

                    if not isinstance(candidate, dict):
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=index,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=_build_external_problem_key(
                                    job_id=job_id,
                                    page_no=page_no,
                                    candidate_index=index,
                                ),
                                reason="candidate payload is not an object",
                            )
                        )
                        continue

                    candidate_no_raw = candidate.get("candidate_no")
                    try:
                        candidate_no = int(candidate_no_raw)
                    except Exception:
                        candidate_no = index

                    confidence = _to_decimal(candidate.get("confidence"))
                    if confidence < payload.min_confidence:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=_build_external_problem_key(
                                    job_id=job_id,
                                    page_no=page_no,
                                    candidate_index=index,
                                ),
                                reason="confidence below threshold",
                            )
                        )
                        continue
                    accepted_candidates += 1

                    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
                    if not isinstance(bbox, dict):
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=_build_external_problem_key(
                                    job_id=job_id,
                                    page_no=page_no,
                                    candidate_index=index,
                                ),
                                reason="candidate bbox missing",
                            )
                        )
                        continue

                    external_problem_key = _build_external_problem_key(
                        job_id=job_id,
                        page_no=page_no,
                        candidate_index=index,
                    )
                    image_bytes, normalized_bbox = extractor.render_clip_png(
                        page_no=page_no,
                        bbox=bbox,
                        asset_type="other",
                        render_scale=2.0,
                    )
                    if not image_bytes:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=external_problem_key,
                                reason="failed to render problem clip",
                            )
                        )
                        continue

                    try:
                        ocr_raw = ocr_mathpix_image(
                            image_bytes=image_bytes,
                            app_id=app_id,
                            app_key=app_key,
                            base_url=base_url,
                            image_filename=f"{external_problem_key}.png",
                        )
                    except Exception as exc:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=external_problem_key,
                                reason=f"Mathpix text OCR failed: {exc}",
                            )
                        )
                        continue

                    extracted_text, extracted_latex = extract_mathpix_text_fields(ocr_raw)
                    final_text = _resolve_problem_text_from_mathpix(
                        extracted_text=extracted_text,
                        extracted_latex=extracted_latex,
                    )
                    statement_text = str(candidate.get("statement_text") or "").strip()
                    if not final_text:
                        final_text = statement_text or None
                    if not final_text:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=external_problem_key,
                                reason="empty OCR output",
                            )
                        )
                        continue

                    subject_code = str(candidate.get("subject_code") or "MATH_II").strip().upper()
                    subject_id = subject_id_by_code.get(subject_code) or subject_id_by_code.get("MATH_II")
                    if not subject_id:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                status="skipped",
                                problem_id=None,
                                external_problem_key=external_problem_key,
                                reason="subject mapping unavailable for curriculum",
                            )
                        )
                        continue

                    answer_key = str(candidate.get("answer_key") or "").strip()
                    response_type = payload.default_response_type
                    if answer_key in {"1", "2", "3", "4", "5"}:
                        response_type = "five_choice"
                    if not answer_key:
                        answer_key = payload.default_answer_key
                    if response_type == "five_choice" and answer_key not in {"1", "2", "3", "4", "5"}:
                        response_type = "short_answer"
                        answer_key = payload.default_answer_key
                    if response_type == "short_answer" and not answer_key:
                        answer_key = "PENDING_REVIEW"

                    point_value_raw = candidate.get("point_value")
                    point_value = point_value_raw if point_value_raw in (2, 3, 4) else payload.default_point_value

                    crop_storage_key: str | None = None
                    if payload.save_problem_images:
                        object_key = (
                            f"ocr-problem-crops/{job_id}/page-{page_no:04d}/"
                            f"candidate-{index:03d}.png"
                        )
                        put_object_bytes(
                            client=s3_client,
                            bucket=target_bucket,
                            key=object_key,
                            body=image_bytes,
                            content_type="image/png",
                        )
                        crop_storage_key = build_storage_key(target_bucket, object_key)

                    if candidate.get("answer_source") == "answer_page":
                        matched_answers += 1

                    asset_hints = collect_problem_asset_hints(
                        statement_text if statement_text else final_text,
                        page_raw_payload=None,
                        candidate_bbox=bbox,
                        candidate_meta=candidate,
                    )
                    detected_visual_assets += len(asset_hints)

                    extracted_assets = []
                    asset_extractor_error: str | None = None
                    if asset_hints:
                        try:
                            extracted_assets = extractor.extract_and_upload(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                external_problem_key=external_problem_key,
                                asset_hints=asset_hints,
                                candidate_bbox=bbox,
                            )
                        except Exception as exc:
                            asset_extractor_error = str(exc)
                    stored_visual_assets += len(extracted_assets)

                    visual_asset_types = _normalize_visual_asset_types(
                        candidate.get("visual_asset_types"),
                        has_visual_asset=bool(candidate.get("has_visual_asset")),
                    )
                    hint_asset_types = {
                        str(item.get("asset_type") or "").strip().lower()
                        for item in asset_hints
                        if str(item.get("asset_type") or "").strip().lower() in ALLOWED_ASSET_TYPES
                    }
                    extracted_asset_types = {
                        str(item.asset_type).strip().lower()
                        for item in extracted_assets
                        if str(item.asset_type).strip().lower() in ALLOWED_ASSET_TYPES
                    }
                    for asset_type in sorted(hint_asset_types | extracted_asset_types):
                        if asset_type not in visual_asset_types:
                            visual_asset_types.append(asset_type)
                    visual_asset_types.sort()

                    metadata = {
                        "needs_review": True,
                        "ingest": {
                            "source": "workflow_run",
                            "provider": "mathpix+gemini",
                            "job_id": str(job_id),
                            "page_no": page_no,
                            "candidate_no": candidate_no,
                            "confidence": float(confidence),
                            "subject_code": subject_code,
                            "problem_type": candidate.get("problem_type"),
                            "question_no": candidate.get("question_no"),
                            "answer_source": candidate.get("answer_source"),
                        },
                        "visual_assets": {
                            "has_visual_asset": bool(candidate.get("has_visual_asset")) or bool(visual_asset_types),
                            "types": visual_asset_types,
                            "detected_count": len(asset_hints),
                            "stored_count": len(extracted_assets),
                            "stored_storage_keys": [item.storage_key for item in extracted_assets],
                            "extraction_error": asset_extractor_error,
                        },
                        "ocr": {
                            "mathpix_text": extracted_text,
                            "mathpix_latex": extracted_latex,
                            "raw": _json_ready(ocr_raw),
                        },
                        "textbook": {
                            "title": payload.textbook_title,
                            "source_category": source_category,
                            "source_type": source_type,
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
                                problem_text_latex,
                                problem_text_final,
                                metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
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
                                problem_text_latex = EXCLUDED.problem_text_latex,
                                problem_text_final = EXCLUDED.problem_text_final,
                                metadata = COALESCE(problems.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                                updated_at = NOW()
                            RETURNING id, (xmax = 0) AS inserted
                            """,
                            (
                                str(curriculum_id),
                                str(source_id) if source_id else None,
                                str(ocr_page_id),
                                external_problem_key,
                                str(subject_id),
                                response_type,
                                point_value,
                                answer_key,
                                None,
                                f"P{page_no}-C{candidate_no}",
                                extracted_text or final_text,
                                extracted_latex,
                                final_text,
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

                    if crop_storage_key:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO problem_assets (
                                    problem_id,
                                    asset_type,
                                    storage_key,
                                    page_no,
                                    bbox,
                                    metadata
                                )
                                VALUES (%s, 'image', %s, %s, %s, %s::jsonb)
                                ON CONFLICT (problem_id, storage_key) DO UPDATE
                                SET
                                    page_no = EXCLUDED.page_no,
                                    bbox = EXCLUDED.bbox,
                                    metadata = COALESCE(problem_assets.metadata, '{}'::jsonb) || EXCLUDED.metadata
                                """,
                                (
                                    str(problem_id),
                                    crop_storage_key,
                                    page_no,
                                    Json(_json_ready(normalized_bbox)) if isinstance(normalized_bbox, dict) else None,
                                    Json(
                                        _json_ready(
                                            {
                                                "needs_review": True,
                                                "ingest": {
                                                    "source": "workflow_run",
                                                    "job_id": str(job_id),
                                                    "page_no": page_no,
                                                    "candidate_no": candidate_no,
                                                },
                                            }
                                        )
                                    ),
                                ),
                            )

                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            DELETE FROM problem_assets
                            WHERE problem_id = %s
                              AND COALESCE(metadata #>> '{ingest,source}', '') = 'workflow_run_asset_extract'
                            """,
                            (str(problem_id),),
                        )
                        for asset_index, extracted in enumerate(extracted_assets, start=1):
                            cur.execute(
                                """
                                INSERT INTO problem_assets (
                                    problem_id,
                                    asset_type,
                                    storage_key,
                                    page_no,
                                    bbox,
                                    metadata
                                )
                                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                                ON CONFLICT (problem_id, storage_key) DO UPDATE
                                SET
                                    asset_type = EXCLUDED.asset_type,
                                    page_no = EXCLUDED.page_no,
                                    bbox = EXCLUDED.bbox,
                                    metadata = COALESCE(problem_assets.metadata, '{}'::jsonb) || EXCLUDED.metadata
                                """,
                                (
                                    str(problem_id),
                                    extracted.asset_type,
                                    extracted.storage_key,
                                    extracted.page_no,
                                    Json(_json_ready(extracted.bbox)) if isinstance(extracted.bbox, dict) else None,
                                    Json(
                                        _json_ready(
                                            {
                                                "needs_review": True,
                                                "ingest": {
                                                    "source": "workflow_run_asset_extract",
                                                    "job_id": str(job_id),
                                                    "page_no": page_no,
                                                    "candidate_no": candidate_no,
                                                    "candidate_key": external_problem_key,
                                                    "asset_index": asset_index,
                                                    **(extracted.metadata or {}),
                                                },
                                            }
                                        )
                                    ),
                                ),
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

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ocr_pages
                        SET
                            status = 'completed',
                            updated_at = NOW()
                        WHERE job_id = %s AND page_no = %s
                        """,
                        (str(job_id), page_no),
                    )
                    progress_ratio = min(Decimal(processed_candidates) / Decimal(progress_denominator), Decimal("1"))
                    progress_pct = Decimal("45") + (Decimal("50") * progress_ratio)
                    cur.execute(
                        """
                        UPDATE ocr_jobs
                        SET
                            status = 'processing',
                            progress_pct = %s
                        WHERE id = %s
                        """,
                        (progress_pct, str(job_id)),
                    )

            with conn.cursor() as cur:
                summary_payload = {
                    "provider": "mathpix+gemini",
                    "model": f"{gemini_model}+mathpix-text",
                    "done": True,
                    "total_candidates": detected_candidates_total,
                    "processed_candidates": processed_candidates,
                    "accepted_candidates": accepted_candidates,
                    "inserted_count": inserted_count,
                    "updated_count": updated_count,
                    "skipped_count": skipped_count,
                    "matched_answers": matched_answers,
                    "detected_visual_assets": detected_visual_assets,
                    "stored_visual_assets": stored_visual_assets,
                    "pages_upserted": pages_upserted,
                    "provider_job_id": provider_job_id,
                }
                cur.execute(
                    """
                    UPDATE ocr_jobs
                    SET
                        status = 'completed',
                        progress_pct = 100,
                        started_at = COALESCE(started_at, NOW()),
                        finished_at = NOW(),
                        error_code = NULL,
                        error_message = NULL,
                        raw_response = COALESCE(raw_response, '{}'::jsonb)
                            || jsonb_build_object('workflow', %s::jsonb)
                    WHERE id = %s
                    """,
                    (Json(_json_ready(summary_payload)), str(job_id)),
                )
            conn.commit()
        except Exception as exc:
            extractor.close()
            _mark_job_failed(
                conn=conn,
                job_id=job_id,
                error_code="WORKFLOW_RUN_ERROR",
                message=str(exc),
            )
            raise

        extractor.close()

    return OCRJobWorkflowRunResponse(
        job_id=job_id,
        provider_job_id=provider_job_id,
        status="completed",
        progress_pct=Decimal("100"),
        provider="mathpix+gemini",
        model=f"{gemini_model}+mathpix-text",
        pages_upserted=pages_upserted,
        processed_candidates=processed_candidates,
        inserted_count=inserted_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        matched_answers=matched_answers,
        detected_visual_assets=detected_visual_assets,
        stored_visual_assets=stored_visual_assets,
        results=results,
    )
