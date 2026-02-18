from pydantic import BaseModel, Field


class S3PresignUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(default="application/pdf", min_length=1)
    prefix: str = Field(default="ocr", min_length=1)
    expires_in_sec: int = Field(default=900, ge=60, le=3600)


class S3PresignUploadResponse(BaseModel):
    bucket: str
    key: str
    storage_key: str
    upload_url: str
    download_url: str
    upload_method: str = "PUT"
    upload_headers: dict[str, str]
    expires_in_sec: int
