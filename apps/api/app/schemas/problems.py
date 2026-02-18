from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ProblemAssetItem(BaseModel):
    id: UUID
    asset_type: str
    storage_key: str
    preview_url: str | None = None
    page_no: int | None = None
    bbox: dict | None = None


class ProblemListItem(BaseModel):
    id: UUID
    ocr_page_id: UUID | None
    ocr_job_id: UUID | None
    external_problem_key: str | None
    source_problem_no: int | None
    source_problem_label: str | None
    content: str | None
    point_value: int
    subject_code: str | None
    subject_name_ko: str | None
    unit_code: str | None
    unit_name_ko: str | None
    source_title: str | None
    source_category: str | None
    source_type: str | None
    document_filename: str | None
    review_status: str
    confidence: Decimal | None
    ai_reviewed: bool
    ai_provider: str | None
    ai_model: str | None
    assets: list[ProblemAssetItem]
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class ProblemListResponse(BaseModel):
    items: list[ProblemListItem]
    total: int
    limit: int
    offset: int
    review_counts: dict[str, int]


class ProblemReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(approve|reject)$")
    note: str | None = Field(default=None, max_length=1000)


class ProblemReviewResponse(BaseModel):
    id: UUID
    review_status: str
    is_verified: bool
    verified_at: datetime | None
    updated_at: datetime
