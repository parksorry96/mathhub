from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OCRJobCreateRequest(BaseModel):
    storage_key: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    file_size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    provider: str = Field(default="mathpix", min_length=1)

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, value: str) -> str:
        candidate = value.strip()
        if candidate.startswith(("s3://", "http://", "https://")):
            return candidate
        raise ValueError("storage_key must start with s3:// or http(s)://")


class OCRJobCreateResponse(BaseModel):
    id: UUID
    document_id: UUID
    provider: str
    status: str
    progress_pct: Decimal
    requested_at: datetime


class OCRJobDeleteResponse(BaseModel):
    job_id: UUID
    document_id: UUID
    source_deleted: bool


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


class OCRPagePreviewItem(BaseModel):
    id: UUID
    page_no: int
    status: str
    extracted_text: str | None
    extracted_latex: str | None
    updated_at: datetime


class OCRJobPagesResponse(BaseModel):
    job_id: UUID
    items: list[OCRPagePreviewItem]
    total: int
    limit: int
    offset: int


class OCRQuestionAssetPreview(BaseModel):
    asset_type: str
    storage_key: str
    preview_url: str | None = None
    page_no: int | None = None
    bbox: dict | None = None


class OCRQuestionPreviewItem(BaseModel):
    page_id: UUID
    page_no: int
    candidate_no: int
    candidate_index: int
    candidate_key: str
    external_problem_key: str
    split_strategy: str
    statement_text: str
    confidence: Decimal | None = None
    validation_status: str | None = None
    provider: str | None = None
    model: str | None = None
    has_visual_asset: bool = False
    asset_types: list[str] = Field(default_factory=list)
    asset_previews: list[OCRQuestionAssetPreview] = Field(default_factory=list)
    updated_at: datetime


class OCRJobQuestionsResponse(BaseModel):
    job_id: UUID
    items: list[OCRQuestionPreviewItem]
    total: int
    limit: int
    offset: int


class OCRJobListItem(BaseModel):
    id: UUID
    document_id: UUID
    provider: str
    provider_job_id: str | None
    status: str
    progress_pct: Decimal
    error_message: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    storage_key: str
    original_filename: str
    total_pages: int
    processed_pages: int
    ai_done: bool | None = None
    ai_total_candidates: int | None = None
    ai_candidates_processed: int | None = None
    ai_candidates_accepted: int | None = None
    ai_provider: str | None = None
    ai_model: str | None = None


class OCRJobListResponse(BaseModel):
    items: list[OCRJobListItem]
    total: int
    limit: int
    offset: int
    status_counts: dict[str, int]


class OCRJobAIClassifyRequest(BaseModel):
    api_key: str | None = None
    api_base_url: str | None = None
    model: str | None = None
    max_pages: int = Field(default=20, ge=1, le=1000)
    min_confidence: Decimal = Field(default=0, ge=0, le=100)
    max_candidates_per_call: int = Field(default=5, ge=1, le=50)


class AICandidateClassification(BaseModel):
    candidate_no: int
    statement_text: str
    split_strategy: str | None = None
    bbox: dict | None = None
    layout_column: int | None = None
    layout_mode: str | None = None
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


class OCRJobAIClassifyStepResponse(BaseModel):
    job_id: UUID
    done: bool
    processed_in_call: int
    total_candidates: int
    candidates_processed: int
    candidates_accepted: int
    provider: str
    model: str
    current_page_no: int | None = None
    current_candidate_no: int | None = None
    current_candidate_provider: str | None = None


class OCRJobAIPreprocessRequest(BaseModel):
    api_key: str | None = None
    api_base_url: str | None = None
    model: str | None = None
    max_pages: int = Field(default=500, ge=1, le=1000)
    render_scale: Decimal = Field(default=1.6, ge=1, le=3)
    temperature: Decimal = Field(default=0.1, ge=0, le=1)


class OCRJobAIPreprocessPageSummary(BaseModel):
    page_no: int
    page_type: str
    problem_count: int
    answer_count: int


class OCRJobAIPreprocessResponse(BaseModel):
    job_id: UUID
    provider: str
    model: str
    scanned_pages: int
    detected_problems: int
    detected_answers: int
    matched_answers: int
    pages: list[OCRJobAIPreprocessPageSummary]


class OCRJobMathpixSubmitRequest(BaseModel):
    file_url: str | None = None
    callback_url: str | None = None
    app_id: str | None = None
    app_key: str | None = None
    base_url: str | None = None
    include_diagram_text: bool = True


class OCRJobMathpixSubmitResponse(BaseModel):
    job_id: UUID
    provider_job_id: str
    status: str
    progress_pct: Decimal
    requested_at: datetime
    started_at: datetime | None


class OCRJobMathpixSyncRequest(BaseModel):
    app_id: str | None = None
    app_key: str | None = None
    base_url: str | None = None


class OCRJobMathpixSyncResponse(BaseModel):
    job_id: UUID
    provider_job_id: str
    status: str
    progress_pct: Decimal
    pages_upserted: int
    error_message: str | None


class OCRJobProblemOCRRequest(BaseModel):
    app_id: str | None = None
    app_key: str | None = None
    base_url: str | None = None
    curriculum_code: str = Field(default="CSAT_2027", min_length=1)
    source_id: UUID | None = None
    source_category: str = Field(default="other", min_length=1)
    source_type: str = Field(default="workbook", min_length=1)
    textbook_title: str | None = None
    min_confidence: Decimal = Field(default=0, ge=0, le=100)
    default_point_value: int = Field(default=3, ge=2, le=4)
    default_response_type: str = Field(default="short_answer", min_length=1)
    default_answer_key: str = Field(default="PENDING_REVIEW", min_length=1)
    max_problems: int = Field(default=3000, ge=1, le=20000)
    save_problem_images: bool = True


class OCRJobMaterializeProblemsRequest(BaseModel):
    curriculum_code: str = Field(default="CSAT_2027", min_length=1)
    source_id: UUID | None = None
    min_confidence: Decimal = Field(default=0, ge=0, le=100)
    default_point_value: int = Field(default=3, ge=2, le=4)
    default_response_type: str = Field(default="short_answer", min_length=1)
    default_answer_key: str = Field(default="PENDING_REVIEW", min_length=1)


class MaterializedProblemResult(BaseModel):
    page_no: int
    candidate_no: int
    status: str
    problem_id: UUID | None
    external_problem_key: str
    reason: str | None


class OCRJobProblemOCRResponse(BaseModel):
    job_id: UUID
    provider: str
    model: str
    processed_candidates: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    matched_answers: int
    results: list[MaterializedProblemResult]


class OCRJobMaterializeProblemsResponse(BaseModel):
    job_id: UUID
    curriculum_code: str
    source_id: UUID | None
    inserted_count: int
    updated_count: int
    skipped_count: int
    results: list[MaterializedProblemResult]
