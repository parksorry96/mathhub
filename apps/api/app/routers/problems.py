from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from psycopg.types.json import Json

from app.config import get_s3_bucket
from app.db import get_db_connection
from app.schemas.problems import (
    ProblemAssetItem,
    ProblemListItem,
    ProblemListResponse,
    ProblemReviewRequest,
    ProblemReviewResponse,
)
from app.services.s3_storage import create_s3_client, generate_presigned_get_url, parse_storage_key

router = APIRouter(prefix="/problems", tags=["problems"])

_REVIEW_STATUS_EXPR = (
    "COALESCE(p.metadata->>'review_status', CASE WHEN p.is_verified THEN 'approved' ELSE 'pending' END)"
)


def _resolve_preview_url(storage_key: str, s3_client) -> str | None:
    if not storage_key.startswith("s3://") or s3_client is None:
        return None
    try:
        bucket, key = parse_storage_key(storage_key)
        return generate_presigned_get_url(
            client=s3_client,
            bucket=bucket,
            key=key,
            expires_in=1800,
        )
    except Exception:
        return None


def _build_problem_assets(raw_assets: object, s3_client) -> list[ProblemAssetItem]:
    if not isinstance(raw_assets, list):
        return []

    assets: list[ProblemAssetItem] = []
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        raw_storage_key = item.get("storage_key")
        if raw_id is None or not isinstance(raw_storage_key, str):
            continue
        try:
            asset_id = UUID(str(raw_id))
        except Exception:
            continue

        bbox = item.get("bbox")
        assets.append(
            ProblemAssetItem(
                id=asset_id,
                asset_type=str(item.get("asset_type") or "other"),
                storage_key=raw_storage_key,
                preview_url=_resolve_preview_url(raw_storage_key, s3_client),
                page_no=int(item["page_no"]) if item.get("page_no") is not None else None,
                bbox=bbox if isinstance(bbox, dict) else None,
            )
        )
    return assets


def _build_problem_filters(
    *,
    q: str | None,
    review_status: str | None,
    ai_reviewed: bool | None,
    include_review_status: bool,
) -> tuple[str, list]:
    where_clauses: list[str] = []
    params: list = []

    if q:
        where_clauses.append(
            "COALESCE(p.problem_text_final, p.problem_text_raw, p.problem_text_latex, '') ILIKE %s"
        )
        params.append(f"%{q.strip()}%")

    if include_review_status and review_status:
        where_clauses.append(f"{_REVIEW_STATUS_EXPR} = %s")
        params.append(review_status)

    if ai_reviewed is True:
        where_clauses.append("COALESCE(p.metadata #>> '{ingest,source}', '') = 'ocr_ai_classification'")
    elif ai_reviewed is False:
        where_clauses.append("COALESCE(p.metadata #>> '{ingest,source}', '') <> 'ocr_ai_classification'")

    if not where_clauses:
        return "", params
    return f"WHERE {' AND '.join(where_clauses)}", params


@router.get("", response_model=ProblemListResponse)
def list_problems(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    review_status: str | None = Query(default=None),
    ai_reviewed: bool | None = Query(default=None),
) -> ProblemListResponse:
    allowed_review_statuses = {"pending", "approved", "rejected"}
    if review_status and review_status not in allowed_review_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="review_status must be one of pending, approved, rejected",
        )

    where_sql, params = _build_problem_filters(
        q=q,
        review_status=review_status,
        ai_reviewed=ai_reviewed,
        include_review_status=True,
    )
    count_where_sql, count_params = _build_problem_filters(
        q=q,
        review_status=review_status,
        ai_reviewed=ai_reviewed,
        include_review_status=False,
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    p.id,
                    p.ocr_page_id,
                    op.job_id AS ocr_job_id,
                    p.external_problem_key,
                    p.source_problem_no,
                    p.source_problem_label,
                    COALESCE(p.problem_text_final, p.problem_text_raw, p.problem_text_latex) AS content,
                    p.point_value,
                    s.code AS subject_code,
                    s.name_ko AS subject_name_ko,
                    u.code AS unit_code,
                    u.name_ko AS unit_name_ko,
                    ps.title AS source_title,
                    ps.source_category::text AS source_category,
                    ps.source_type::text AS source_type,
                    d.original_filename AS document_filename,
                    {_REVIEW_STATUS_EXPR} AS review_status,
                    CASE
                        WHEN (p.metadata #>> '{{ingest,confidence}}') ~ '^[0-9]+(\\.[0-9]+)?$'
                        THEN (p.metadata #>> '{{ingest,confidence}}')::numeric
                        ELSE NULL
                    END AS confidence,
                    (COALESCE(p.metadata #>> '{{ingest,source}}', '') = 'ocr_ai_classification') AS ai_reviewed,
                    NULLIF(p.metadata #>> '{{ingest,provider}}', '') AS ai_provider,
                    NULLIF(p.metadata #>> '{{ingest,model}}', '') AS ai_model,
                    COALESCE(pa.assets, '[]'::jsonb) AS assets,
                    p.is_verified,
                    p.created_at,
                    p.updated_at
                FROM problems p
                JOIN math_subjects s ON s.id = p.primary_subject_id
                LEFT JOIN problem_unit_map pum
                    ON pum.problem_id = p.id
                   AND pum.is_primary = TRUE
                LEFT JOIN math_units u ON u.id = pum.unit_id
                LEFT JOIN problem_sources ps ON ps.id = p.source_id
                LEFT JOIN ocr_pages op ON op.id = p.ocr_page_id
                LEFT JOIN ocr_jobs oj ON oj.id = op.job_id
                LEFT JOIN ocr_documents d ON d.id = oj.document_id
                LEFT JOIN LATERAL (
                    SELECT COALESCE(
                        jsonb_agg(
                            jsonb_build_object(
                                'id', pa.id,
                                'asset_type', pa.asset_type::text,
                                'storage_key', pa.storage_key,
                                'page_no', pa.page_no,
                                'bbox', pa.bbox
                            )
                            ORDER BY pa.created_at ASC
                        ),
                        '[]'::jsonb
                    ) AS assets
                    FROM problem_assets pa
                    WHERE pa.problem_id = p.id
                ) pa ON TRUE
                {where_sql}
                ORDER BY p.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM problems p
                {where_sql}
                """,
                tuple(params),
            )
            total_row = cur.fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            cur.execute(
                f"""
                SELECT
                    {_REVIEW_STATUS_EXPR} AS review_status,
                    COUNT(*) AS cnt
                FROM problems p
                {count_where_sql}
                GROUP BY {_REVIEW_STATUS_EXPR}
                """,
                tuple(count_params),
            )
            review_count_rows = cur.fetchall()

    review_counts = {"pending": 0, "approved": 0, "rejected": 0}
    for row in review_count_rows:
        key = row["review_status"]
        if key in review_counts:
            review_counts[key] = int(row["cnt"])

    try:
        s3_client = create_s3_client() if get_s3_bucket() else None
    except Exception:
        s3_client = None

    items: list[ProblemListItem] = []
    for row in rows:
        payload = dict(row)
        payload["assets"] = _build_problem_assets(row.get("assets"), s3_client)
        items.append(ProblemListItem(**payload))
    return ProblemListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        review_counts=review_counts,
    )


@router.patch("/{problem_id}/review", response_model=ProblemReviewResponse)
def review_problem(problem_id: UUID, payload: ProblemReviewRequest) -> ProblemReviewResponse:
    review_status = "approved" if payload.action == "approve" else "rejected"
    metadata_patch: dict[str, object] = {
        "review_status": review_status,
    }
    if payload.note is not None:
        metadata_patch["review_note"] = payload.note

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE problems
                SET
                    is_verified = %s,
                    verified_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    COALESCE(metadata->>'review_status', CASE WHEN is_verified THEN 'approved' ELSE 'pending' END) AS review_status,
                    is_verified,
                    verified_at,
                    updated_at
                """,
                (
                    payload.action == "approve",
                    payload.action == "approve",
                    Json(metadata_patch),
                    str(problem_id),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem not found: {problem_id}",
        )

    return ProblemReviewResponse(**row)
