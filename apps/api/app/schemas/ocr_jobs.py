from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OCRJobCreateRequest(BaseModel):
    storage_key: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    file_size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    provider: str = Field(default="mathpix", min_length=1)


class OCRJobCreateResponse(BaseModel):
    id: UUID
    document_id: UUID
    provider: str
    status: str
    progress_pct: Decimal
    requested_at: datetime


class OCRDocumentSummary(BaseModel):
    id: UUID
    storage_key: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    created_at: datetime


class OCRJobDetailResponse(BaseModel):
    id: UUID
    document_id: UUID
    provider: str
    provider_job_id: str | None
    status: str
    progress_pct: Decimal
    error_code: str | None
    error_message: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    document: OCRDocumentSummary


class OCRJobAIClassifyRequest(BaseModel):
    api_key: str | None = None
    api_base_url: str | None = None
    model: str | None = None
    max_pages: int = Field(default=20, ge=1, le=1000)
    min_confidence: Decimal = Field(default=0, ge=0, le=100)


class AICandidateClassification(BaseModel):
    candidate_no: int
    statement_text: str
    subject_code: str | None
    unit_code: str | None
    point_value: int | None
    source_category: str | None
    source_type: str | None
    validation_status: str
    confidence: Decimal
    reason: str | None
    provider: str
    model: str


class AIPageClassification(BaseModel):
    page_id: UUID
    page_no: int
    candidate_count: int
    candidates: list[AICandidateClassification]


class OCRJobAIClassifyResponse(BaseModel):
    job_id: UUID
    provider: str
    model: str
    pages_processed: int
    candidates_processed: int
    candidates_accepted: int
    page_results: list[AIPageClassification]
