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
