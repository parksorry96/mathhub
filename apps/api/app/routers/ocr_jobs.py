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
    get_gemini_base_url,
    get_gemini_api_key,
    get_gemini_model,
    get_gemini_preprocess_model,
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
    OCRJobAIPreprocessPageSummary,
    OCRJobAIPreprocessRequest,
    OCRJobAIPreprocessResponse,
    OCRJobAIClassifyRequest,
    OCRJobAIClassifyResponse,
    OCRJobAIClassifyStepResponse,
    OCRJobCreateRequest,
    OCRJobCreateResponse,
    OCRJobDeleteResponse,
    OCRJobDetailResponse,
    OCRJobListItem,
    OCRJobListResponse,
    OCRJobMaterializeProblemsRequest,
    OCRJobMaterializeProblemsResponse,
    OCRJobMathpixSubmitRequest,
    OCRJobMathpixSubmitResponse,
    OCRJobMathpixSyncRequest,
    OCRJobMathpixSyncResponse,
    OCRJobProblemOCRRequest,
    OCRJobProblemOCRResponse,
    OCRJobPagesResponse,
    OCRQuestionAssetPreview,
    OCRJobQuestionsResponse,
    OCRPagePreviewItem,
    OCRQuestionPreviewItem,
)
from app.services.ai_classifier import classify_candidate, collect_problem_asset_hints, extract_problem_candidates
from app.services.gemini_document_scanner import (
    attach_answer_keys_to_scanned_pages,
    scan_pdf_document_with_gemini,
)
from app.services.problem_asset_extractor import ProblemAssetExtractor
from app.services.mathpix_client import (
    extract_mathpix_text_fields,
    extract_mathpix_pages,
    extract_mathpix_pages_from_lines,
    fetch_mathpix_pdf_lines,
    fetch_mathpix_pdf_status,
    map_mathpix_job_status,
    ocr_mathpix_image,
    merge_mathpix_pages,
    resolve_provider_job_id,
    submit_mathpix_pdf,
)
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
    ai_classification = raw_payload.get("ai_classification")
    ai_candidates = ai_classification.get("candidates") if isinstance(ai_classification, dict) else None
    source_candidates = (
        ai_candidates
        if isinstance(ai_candidates, list)
        else extract_problem_candidates(page_text, raw_payload if isinstance(raw_payload, dict) else None)
    )

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

        split_strategy = str(candidate.get("split_strategy") or "").strip()
        if not split_strategy:
            split_strategy = "ai_classification" if isinstance(ai_candidates, list) else "numbered"

        candidate_bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
        asset_hints = collect_problem_asset_hints(
            statement_text,
            raw_payload,
            candidate_bbox=candidate_bbox,
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


def _build_ai_candidate_output(*, candidate: dict, classified: dict) -> AICandidateClassification:
    return AICandidateClassification(
        candidate_no=int(candidate["candidate_no"]),
        statement_text=candidate["statement_text"],
        split_strategy=str(candidate.get("split_strategy")) if candidate.get("split_strategy") is not None else None,
        bbox=candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None,
        layout_column=int(candidate.get("layout_column")) if candidate.get("layout_column") is not None else None,
        layout_mode=str(candidate.get("layout_mode")) if candidate.get("layout_mode") is not None else None,
        subject_code=classified["subject_code"],
        unit_code=classified["unit_code"],
        point_value=classified["point_value"],
        source_category=classified["source_category"],
        source_type=classified["source_type"],
        validation_status=classified["validation_status"],
        confidence=Decimal(str(classified["confidence"])),
        reason=classified["reason"],
        provider=classified["provider"],
        model=classified["model"],
    )


def _build_ai_preprocess_extracted_text(*, problem_items: list[dict]) -> str | None:
    # Gemini pre-process is only for page/candidate segmentation and classification.
    # OCR text persistence is intentionally disabled to keep Mathpix as single text source.
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
    resolved_model = model or default_model or get_gemini_model()

    if not resolved_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="gemini credentials missing: provide api_key or set GEMINI_API_KEY",
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
                        WHEN COALESCE(j.raw_response #>> '{{ai_classification,done}}', '') IN ('true', 'false')
                            THEN (j.raw_response #>> '{{ai_classification,done}}')::boolean
                        ELSE NULL
                    END AS ai_done,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{ai_classification,total_candidates}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{ai_classification,total_candidates}}')::int
                        ELSE NULL
                    END AS ai_total_candidates,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{ai_classification,candidates_processed}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{ai_classification,candidates_processed}}')::int
                        ELSE NULL
                    END AS ai_candidates_processed,
                    CASE
                        WHEN COALESCE(j.raw_response #>> '{{ai_classification,candidates_accepted}}', '') ~ '^[0-9]+$'
                            THEN (j.raw_response #>> '{{ai_classification,candidates_accepted}}')::int
                        ELSE NULL
                    END AS ai_candidates_accepted,
                    NULLIF(j.raw_response #>> '{{ai_classification,provider}}', '') AS ai_provider,
                    NULLIF(j.raw_response #>> '{{ai_classification,model}}', '') AS ai_model
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


@router.post("/{job_id}/ai-preprocess", response_model=OCRJobAIPreprocessResponse)
def preprocess_ocr_job_with_ai(
    job_id: UUID,
    payload: OCRJobAIPreprocessRequest,
) -> OCRJobAIPreprocessResponse:
    api_key, api_base_url, model = _resolve_gemini_credentials(
        api_key=payload.api_key,
        base_url=payload.api_base_url,
        model=payload.model,
        default_model=get_gemini_preprocess_model(),
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    j.id,
                    d.storage_key AS document_storage_key
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

        document_storage_key = str(job.get("document_storage_key") or "").strip()
        if not document_storage_key.startswith("s3://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ai-preprocess requires document storage_key in s3:// format",
            )

        try:
            source_bucket, source_key = parse_storage_key(document_storage_key)
            s3_client = create_s3_client()
            source_pdf_bytes = get_object_bytes(
                client=s3_client,
                bucket=source_bucket,
                key=source_key,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to read source PDF for ai-preprocess: {exc}",
            ) from exc

        try:
            scanned_pages = scan_pdf_document_with_gemini(
                pdf_bytes=source_pdf_bytes,
                api_key=api_key,
                base_url=api_base_url,
                model=model,
                max_pages=payload.max_pages,
                render_scale=float(payload.render_scale),
                temperature=float(payload.temperature),
                max_parallel_pages=int(payload.max_parallel_pages),
                max_output_tokens=int(payload.max_output_tokens),
                thinking_budget=(
                    int(payload.thinking_budget) if payload.thinking_budget is not None else None
                ),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gemini preprocess request failed: {exc}",
            ) from exc

        matched_answers = attach_answer_keys_to_scanned_pages(scanned_pages)

        page_summaries: list[OCRJobAIPreprocessPageSummary] = []
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

                page_type = str(scanned_page.get("page_type") or "other")
                page_summaries.append(
                    OCRJobAIPreprocessPageSummary(
                        page_no=page_no,
                        page_type=page_type,
                        problem_count=len(problem_items),
                        answer_count=len(answer_items),
                    )
                )
                page_pre_text = _build_ai_preprocess_extracted_text(problem_items=problem_items)

                cur.execute(
                    """
                    INSERT INTO ocr_pages (
                        job_id,
                        page_no,
                        status,
                        extracted_text,
                        raw_payload
                    )
                    VALUES (%s, %s, 'processing', %s, %s::jsonb)
                    ON CONFLICT (job_id, page_no) DO UPDATE
                    SET
                        extracted_text = COALESCE(ocr_pages.extracted_text, EXCLUDED.extracted_text),
                        raw_payload = COALESCE(ocr_pages.raw_payload, '{}'::jsonb) || EXCLUDED.raw_payload,
                        updated_at = NOW()
                    """,
                    (
                        str(job_id),
                        page_no,
                        page_pre_text,
                        Json({"ai_preprocess": _json_ready(scanned_page)}),
                    ),
                )

            preprocess_summary = {
                "provider": "gemini",
                "model": model,
                "scanned_pages": len(page_summaries),
                "detected_problems": detected_problems,
                "detected_answers": detected_answers,
                "matched_answers": matched_answers,
            }
            cur.execute(
                """
                UPDATE ocr_jobs
                SET raw_response = COALESCE(raw_response, '{}'::jsonb)
                    || jsonb_build_object('ai_preprocess', %s::jsonb)
                WHERE id = %s
                """,
                (Json(_json_ready(preprocess_summary)), str(job_id)),
            )
        conn.commit()

    return OCRJobAIPreprocessResponse(
        job_id=job_id,
        provider="gemini",
        model=model,
        scanned_pages=len(page_summaries),
        detected_problems=detected_problems,
        detected_answers=detected_answers,
        matched_answers=matched_answers,
        pages=page_summaries,
    )


@router.post("/{job_id}/problem-ocr", response_model=OCRJobProblemOCRResponse)
def run_problem_level_ocr_pipeline(
    job_id: UUID,
    payload: OCRJobProblemOCRRequest,
) -> OCRJobProblemOCRResponse:
    app_id, app_key, base_url = _resolve_mathpix_credentials(
        app_id=payload.app_id,
        app_key=payload.app_key,
        base_url=payload.base_url,
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
                                    "source": "ai_problem_ocr",
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
                detail=(
                    "No OCR pages available. Run /ocr/jobs/{job_id}/ai-preprocess first "
                    "to generate problem candidates."
                ),
            )

        document_storage_key = str(job.get("document_storage_key") or "").strip()
        if not document_storage_key.startswith("s3://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="problem-ocr requires document storage_key in s3:// format",
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to read source PDF for problem-ocr: {exc}",
            ) from exc

        extractor = ProblemAssetExtractor(
            pdf_bytes=source_pdf_bytes,
            s3_client=s3_client,
            bucket=target_bucket,
            job_id=job_id,
            prefix="ocr-problem-crops",
        )
        if not extractor.is_available:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Problem OCR extractor is unavailable (PyMuPDF missing)",
            )

        processed_candidates = 0
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        matched_answers = 0
        results: list[MaterializedProblemResult] = []

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ocr_jobs
                SET
                    status = 'processing',
                    progress_pct = 10,
                    started_at = COALESCE(started_at, NOW()),
                    finished_at = NULL,
                    error_code = NULL,
                    error_message = NULL
                WHERE id = %s
                """,
                (str(job_id),),
            )
        conn.commit()

        try:
            for page in pages:
                if processed_candidates >= payload.max_problems:
                    break
                page_no = int(page["page_no"])
                raw_payload = page.get("raw_payload")
                raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
                ai_preprocess = raw_payload.get("ai_preprocess")
                if not isinstance(ai_preprocess, dict):
                    continue
                problems = ai_preprocess.get("problems")
                if not isinstance(problems, list):
                    continue

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
                                external_problem_key=f"OCRAI:{job_id}:P{page_no}:I{index}",
                                reason="candidate payload is not an object",
                            )
                        )
                        continue

                    confidence = _to_decimal(candidate.get("confidence"))
                    if confidence < payload.min_confidence:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=int(candidate.get("candidate_no") or index),
                                status="skipped",
                                problem_id=None,
                                external_problem_key=f"OCRAI:{job_id}:P{page_no}:I{index}",
                                reason="confidence below threshold",
                            )
                        )
                        continue

                    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
                    if not isinstance(bbox, dict):
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=int(candidate.get("candidate_no") or index),
                                status="skipped",
                                problem_id=None,
                                external_problem_key=f"OCRAI:{job_id}:P{page_no}:I{index}",
                                reason="candidate bbox missing",
                            )
                        )
                        continue

                    external_problem_key = f"OCRAI:{job_id}:P{page_no}:I{index}"
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
                                candidate_no=int(candidate.get("candidate_no") or index),
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
                                candidate_no=int(candidate.get("candidate_no") or index),
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
                    if not final_text:
                        skipped_count += 1
                        results.append(
                            MaterializedProblemResult(
                                page_no=page_no,
                                candidate_no=int(candidate.get("candidate_no") or index),
                                status="skipped",
                                problem_id=None,
                                external_problem_key=external_problem_key,
                                reason="empty Mathpix OCR output",
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
                                candidate_no=int(candidate.get("candidate_no") or index),
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

                    metadata = {
                        "needs_review": True,
                        "ingest": {
                            "source": "ai_problem_ocr",
                            "provider": "gemini+mathpix",
                            "job_id": str(job_id),
                            "page_no": page_no,
                            "candidate_no": int(candidate.get("candidate_no") or index),
                            "confidence": float(confidence),
                            "subject_code": subject_code,
                            "problem_type": candidate.get("problem_type"),
                            "question_no": candidate.get("question_no"),
                            "answer_source": candidate.get("answer_source"),
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
                                str(page["id"]),
                                external_problem_key,
                                str(subject_id),
                                response_type,
                                point_value,
                                answer_key,
                                None,
                                f"P{page_no}-C{int(candidate.get('candidate_no') or index)}",
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
                        asset_metadata = {
                            "needs_review": True,
                            "ingest": {
                                "source": "ai_problem_ocr",
                                "job_id": str(job_id),
                                "page_no": page_no,
                                "candidate_no": int(candidate.get("candidate_no") or index),
                            },
                        }
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
                                    Json(_json_ready(asset_metadata)),
                                ),
                            )

                    results.append(
                        MaterializedProblemResult(
                            page_no=page_no,
                            candidate_no=int(candidate.get("candidate_no") or index),
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
                        WHERE id = %s
                        """,
                        (str(page["id"]),),
                    )

            with conn.cursor() as cur:
                summary_payload = {
                    "provider": "gemini+mathpix",
                    "model": "gemini-preprocess+mathpix-text",
                    "processed_candidates": processed_candidates,
                    "inserted_count": inserted_count,
                    "updated_count": updated_count,
                    "skipped_count": skipped_count,
                    "matched_answers": matched_answers,
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
                            || jsonb_build_object('ai_problem_ocr', %s::jsonb)
                    WHERE id = %s
                    """,
                    (Json(_json_ready(summary_payload)), str(job_id)),
                )
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ocr_jobs
                        SET
                            status = 'failed',
                            error_code = 'PROBLEM_OCR_ERROR',
                            error_message = %s,
                            finished_at = NOW()
                        WHERE id = %s
                        """,
                        (str(exc), str(job_id)),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
            raise
        finally:
            extractor.close()

    return OCRJobProblemOCRResponse(
        job_id=job_id,
        provider="gemini+mathpix",
        model="gemini-preprocess+mathpix-text",
        processed_candidates=processed_candidates,
        inserted_count=inserted_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        matched_answers=matched_answers,
        results=results,
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

        file_url = _resolve_mathpix_file_url(
            file_url=payload.file_url,
            storage_key=job["storage_key"],
        )

        try:
            submit_result = submit_mathpix_pdf(
                file_url=file_url,
                app_id=app_id,
                app_key=app_key,
                base_url=base_url,
                callback_url=payload.callback_url,
                include_diagram_text=payload.include_diagram_text,
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
                    pages = merge_mathpix_pages(status_pages=pages, line_pages=line_pages)
            except Exception:
                # Keep the original status path; page extraction can be retried with next sync.
                pass
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
                detail=f"No OCR pages available. Run /ocr/jobs/{job_id}/mathpix/sync and check /ocr/jobs/{job_id}/pages first.",
            )

        page_results: list[AIPageClassification] = []
        candidates_processed = 0
        candidates_accepted = 0
        api_candidates = 0

        for page in pages:
            page_text = (page.get("extracted_text") or page.get("extracted_latex") or "").strip()
            raw_payload = page.get("raw_payload")
            candidates = extract_problem_candidates(page_text, raw_payload if isinstance(raw_payload, dict) else None)
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

                candidate_out = _build_ai_candidate_output(candidate=candidate, classified=classified)
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


@router.post("/{job_id}/ai-classify/step", response_model=OCRJobAIClassifyStepResponse)
def classify_ocr_job_step(job_id: UUID, payload: OCRJobAIClassifyRequest) -> OCRJobAIClassifyStepResponse:
    api_key = payload.api_key or get_ai_api_key()
    api_base_url = payload.api_base_url or get_ai_api_base_url()
    model = payload.model or get_ai_model()

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
                detail=f"No OCR pages available. Run /ocr/jobs/{job_id}/mathpix/sync and check /ocr/jobs/{job_id}/pages first.",
            )

        total_candidates = 0
        candidates_processed = 0
        candidates_accepted = 0
        api_candidates = 0
        pages_processed = 0
        max_candidates_per_call = payload.max_candidates_per_call
        page_states: dict[str, dict] = {}
        target_candidates: list[tuple[str, dict]] = []

        for page in pages:
            page_text = (page.get("extracted_text") or page.get("extracted_latex") or "").strip()
            raw_payload = page.get("raw_payload")
            page_candidates = extract_problem_candidates(
                page_text,
                raw_payload if isinstance(raw_payload, dict) else None,
            )
            total_candidates += len(page_candidates)

            raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
            ai_classification = raw_payload.get("ai_classification") if isinstance(raw_payload, dict) else None
            existing_candidates = ai_classification.get("candidates") if isinstance(ai_classification, dict) else None
            existing_list = existing_candidates if isinstance(existing_candidates, list) else []
            if existing_list:
                pages_processed += 1

            existing_candidate_no: set[int] = set()
            for existing in existing_list:
                if not isinstance(existing, dict):
                    continue
                try:
                    existing_no = int(existing.get("candidate_no"))
                except Exception:
                    continue
                existing_candidate_no.add(existing_no)
                candidates_processed += 1

                confidence = _to_decimal(existing.get("confidence"))
                if confidence >= payload.min_confidence:
                    candidates_accepted += 1

                if existing.get("provider") == "api":
                    api_candidates += 1

            page_key = str(page["id"])
            page_states[page_key] = {
                "page": page,
                "candidates": [item for item in existing_list if isinstance(item, dict)],
                "had_candidates": bool(existing_list),
                "touched": False,
            }

            if len(target_candidates) >= max_candidates_per_call:
                continue

            for candidate in page_candidates:
                try:
                    candidate_no = int(candidate["candidate_no"])
                except Exception:
                    continue
                if candidate_no in existing_candidate_no:
                    continue
                target_candidates.append((page_key, candidate))
                existing_candidate_no.add(candidate_no)
                if len(target_candidates) >= max_candidates_per_call:
                    break

        if total_candidates == 0:
            summary_payload = {
                "provider": "heuristic",
                "model": model,
                "pages_processed": 0,
                "candidates_processed": 0,
                "candidates_accepted": 0,
                "total_candidates": 0,
                "done": True,
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
            return OCRJobAIClassifyStepResponse(
                job_id=job_id,
                done=True,
                processed_in_call=0,
                total_candidates=0,
                candidates_processed=0,
                candidates_accepted=0,
                provider="heuristic",
                model=model,
            )

        if not target_candidates:
            final_provider = "api" if api_candidates > 0 else "heuristic"
            summary_payload = {
                "provider": final_provider,
                "model": model,
                "pages_processed": pages_processed,
                "candidates_processed": candidates_processed,
                "candidates_accepted": candidates_accepted,
                "total_candidates": total_candidates,
                "done": True,
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
            return OCRJobAIClassifyStepResponse(
                job_id=job_id,
                done=True,
                processed_in_call=0,
                total_candidates=total_candidates,
                candidates_processed=candidates_processed,
                candidates_accepted=candidates_accepted,
                provider=final_provider,
                model=model,
            )

        last_page_no: int | None = None
        last_candidate_no: int | None = None
        last_candidate_provider: str | None = None
        for page_key, target_candidate in target_candidates:
            classified = classify_candidate(
                statement_text=target_candidate["statement_text"],
                api_key=api_key,
                api_base_url=api_base_url,
                model=model,
            )
            candidate_out = _build_ai_candidate_output(candidate=target_candidate, classified=classified)

            state = page_states[page_key]
            existing_items = state["candidates"]
            updated_candidates: list[dict] = []
            replaced = False
            for existing in existing_items:
                try:
                    existing_no = int(existing.get("candidate_no"))
                except Exception:
                    existing_no = None
                if existing_no == candidate_out.candidate_no:
                    updated_candidates.append(candidate_out.model_dump())
                    replaced = True
                else:
                    updated_candidates.append(existing)
            if not replaced:
                updated_candidates.append(candidate_out.model_dump())

            updated_candidates.sort(key=lambda item: int(item.get("candidate_no", 0)))
            state["candidates"] = updated_candidates
            state["touched"] = True

            candidates_processed += 1
            if candidate_out.confidence >= payload.min_confidence:
                candidates_accepted += 1
            if candidate_out.provider == "api":
                api_candidates += 1

            last_page_no = int(state["page"]["page_no"])
            last_candidate_no = candidate_out.candidate_no
            last_candidate_provider = candidate_out.provider

        with conn.cursor() as cur:
            for state in page_states.values():
                if not state.get("touched"):
                    continue
                if not state.get("had_candidates") and state.get("candidates"):
                    pages_processed += 1

                page = state["page"]
                page_ai_payload = {
                    "page_id": str(page["id"]),
                    "page_no": page["page_no"],
                    "candidate_count": len(state["candidates"]),
                    "candidates": state["candidates"],
                }
                cur.execute(
                    """
                    UPDATE ocr_pages
                    SET
                        raw_payload = COALESCE(raw_payload, '{}'::jsonb)
                            || jsonb_build_object('ai_classification', %s::jsonb),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (Json(_json_ready(page_ai_payload)), str(page["id"])),
                )

            final_provider = "api" if api_candidates > 0 else "heuristic"
            done = candidates_processed >= total_candidates
            summary_payload = {
                "provider": final_provider,
                "model": model,
                "pages_processed": pages_processed,
                "candidates_processed": candidates_processed,
                "candidates_accepted": candidates_accepted,
                "total_candidates": total_candidates,
                "done": done,
            }
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

    return OCRJobAIClassifyStepResponse(
        job_id=job_id,
        done=done,
        processed_in_call=len(target_candidates),
        total_candidates=total_candidates,
        candidates_processed=candidates_processed,
        candidates_accepted=candidates_accepted,
        provider=final_provider,
        model=model,
        current_page_no=last_page_no,
        current_candidate_no=last_candidate_no,
        current_candidate_provider=last_candidate_provider,
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
            cur.execute(
                """
                SELECT j.id, d.storage_key AS document_storage_key
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
            document_storage_key = str(job.get("document_storage_key") or "").strip()

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
                SELECT id, page_no, extracted_text, extracted_latex, raw_payload
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

        asset_extractor = None
        asset_extractor_error: str | None = None
        if document_storage_key.startswith("s3://"):
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

                asset_extractor = ProblemAssetExtractor(
                    pdf_bytes=source_pdf_bytes,
                    s3_client=s3_client,
                    bucket=target_bucket,
                    job_id=job_id,
                )
                if not asset_extractor.is_available:
                    asset_extractor_error = "PyMuPDF is unavailable in runtime environment."
            except Exception as exc:
                asset_extractor_error = str(exc)
        else:
            asset_extractor_error = "document storage_key is not s3://, asset extraction skipped."

        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        results: list[MaterializedProblemResult] = []
        heuristic_api_base_url = get_ai_api_base_url()
        heuristic_model = get_ai_model()
        try:
            for page in pages:
                page_no = page["page_no"]
                raw_payload = page.get("raw_payload") or {}
                ai_classification = raw_payload.get("ai_classification")

                fallback_layout_by_no: dict[int, dict] = {}
                page_text = (page.get("extracted_text") or page.get("extracted_latex") or "").strip()
                fallback_candidates = extract_problem_candidates(
                    page_text,
                    raw_payload if isinstance(raw_payload, dict) else None,
                )
                for derived in fallback_candidates:
                    if not isinstance(derived, dict):
                        continue
                    try:
                        derived_no = int(derived.get("candidate_no"))
                    except Exception:
                        continue
                    fallback_layout_by_no[derived_no] = derived

                source_candidates: list[dict] = []
                ai_candidates = ai_classification.get("candidates") if isinstance(ai_classification, dict) else None
                if isinstance(ai_candidates, list) and ai_candidates:
                    for candidate in ai_candidates:
                        if not isinstance(candidate, dict):
                            continue
                        source_candidates.append(
                            {
                                **candidate,
                                "_ingest_source": "ocr_ai_classification",
                            }
                        )
                else:
                    for candidate in fallback_candidates:
                        if not isinstance(candidate, dict):
                            continue
                        statement_text = str(candidate.get("statement_text") or "").strip()
                        if not statement_text:
                            continue
                        classified = classify_candidate(
                            statement_text=statement_text,
                            api_key=None,
                            api_base_url=heuristic_api_base_url,
                            model=heuristic_model,
                        )
                        source_candidates.append(
                            {
                                **candidate,
                                **classified,
                                "_ingest_source": "ocr_heuristic_materialize",
                            }
                        )

                if not source_candidates:
                    continue

                for index, candidate in enumerate(source_candidates):
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

                    ingest_source = str(candidate.get("_ingest_source") or "ocr_heuristic_materialize")
                    candidate_no_raw = candidate.get("candidate_no")
                    try:
                        candidate_no = int(candidate_no_raw)
                    except Exception:
                        candidate_no = index + 1

                    candidate_index = index + 1
                    external_problem_key = _build_external_problem_key(
                        job_id=job_id,
                        page_no=page_no,
                        candidate_index=candidate_index,
                    )
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
                    candidate_bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
                    if candidate_bbox is None:
                        fallback_candidate = fallback_layout_by_no.get(candidate_no)
                        if isinstance(fallback_candidate, dict) and isinstance(fallback_candidate.get("bbox"), dict):
                            candidate_bbox = fallback_candidate.get("bbox")
                    asset_hints = collect_problem_asset_hints(
                        statement_text,
                        raw_payload,
                        candidate_bbox=candidate_bbox,
                    )
                    asset_types = sorted(
                        {
                            str(asset.get("asset_type")).strip().lower()
                            for asset in asset_hints
                            if str(asset.get("asset_type")).strip().lower() in ALLOWED_ASSET_TYPES
                        }
                    )
                    extracted_assets = []
                    if asset_extractor and asset_extractor.is_available and asset_hints:
                        try:
                            extracted_assets = asset_extractor.extract_and_upload(
                                page_no=page_no,
                                candidate_no=candidate_no,
                                external_problem_key=external_problem_key,
                                asset_hints=asset_hints,
                                candidate_bbox=candidate_bbox,
                            )
                        except Exception as exc:
                            asset_extractor_error = str(exc)
                    extracted_asset_storage_keys = [item.storage_key for item in extracted_assets]
                    extracted_asset_types = sorted({item.asset_type for item in extracted_assets})
                    for asset_type in extracted_asset_types:
                        if asset_type not in asset_types:
                            asset_types.append(asset_type)
                    asset_types.sort()

                    metadata = {
                        "needs_review": True,
                        "ingest": {
                            "source": ingest_source,
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
                        "visual_assets": {
                            "detected_count": len(asset_hints),
                            "stored_count": len(extracted_assets),
                            "stored_storage_keys": extracted_asset_storage_keys,
                            "types": asset_types,
                            "extraction_error": asset_extractor_error,
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

                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            DELETE FROM problem_assets
                            WHERE problem_id = %s
                              AND COALESCE(metadata #>> '{ingest,source}', '') = 'ocr_asset_hint'
                            """,
                            (str(problem_id),),
                        )
                        if extracted_assets:
                            for asset_index, extracted in enumerate(extracted_assets, start=1):
                                asset_metadata = {
                                    "needs_review": True,
                                    "ingest": {
                                        "source": "ocr_asset_extract",
                                        "job_id": str(job_id),
                                        "page_no": page_no,
                                        "candidate_no": candidate_no,
                                        "candidate_key": external_problem_key,
                                        "asset_index": asset_index,
                                        **(extracted.metadata or {}),
                                    },
                                }
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
                                        Json(_json_ready(asset_metadata)),
                                    ),
                                )
                        else:
                            for asset_index, asset in enumerate(asset_hints, start=1):
                                asset_type = str(asset.get("asset_type") or "other").strip().lower()
                                if asset_type not in ALLOWED_ASSET_TYPES:
                                    asset_type = "other"
                                bbox = asset.get("bbox")
                                storage_key = f"ocr-asset://{job_id}/p{page_no}/c{candidate_no}/{asset_type}/{asset_index}"
                                asset_metadata = {
                                    "needs_review": True,
                                    "ingest": {
                                        "source": "ocr_asset_hint",
                                        "job_id": str(job_id),
                                        "page_no": page_no,
                                        "candidate_no": candidate_no,
                                        "candidate_key": external_problem_key,
                                        "asset_index": asset_index,
                                        "detected_by": asset.get("source"),
                                        "evidence": asset.get("evidence"),
                                        "extraction_error": asset_extractor_error,
                                    },
                                }
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
                                        asset_type,
                                        storage_key,
                                        page_no,
                                        Json(_json_ready(bbox)) if isinstance(bbox, dict) else None,
                                        Json(_json_ready(asset_metadata)),
                                    ),
                                )

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
        finally:
            if asset_extractor:
                asset_extractor.close()

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
