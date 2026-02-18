from fastapi import APIRouter, HTTPException, status

from app.schemas.storage import S3PresignUploadRequest, S3PresignUploadResponse
from app.services.s3_storage import (
    build_object_key,
    build_storage_key,
    create_s3_client,
    ensure_s3_bucket,
    generate_presigned_get_url,
    generate_presigned_put_url,
)

router = APIRouter(prefix="/storage", tags=["storage"])


@router.post("/s3/presign-upload", response_model=S3PresignUploadResponse)
def presign_s3_upload(payload: S3PresignUploadRequest) -> S3PresignUploadResponse:
    if payload.content_type.lower() != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only application/pdf is supported",
        )

    try:
        bucket = ensure_s3_bucket()
        client = create_s3_client()
        key = build_object_key(payload.filename, prefix=payload.prefix)
        upload_url = generate_presigned_put_url(
            client=client,
            bucket=bucket,
            key=key,
            content_type=payload.content_type,
            expires_in=payload.expires_in_sec,
        )
        download_url = generate_presigned_get_url(
            client=client,
            bucket=bucket,
            key=key,
            expires_in=payload.expires_in_sec,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate S3 presigned URL: {exc}",
        ) from exc

    return S3PresignUploadResponse(
        bucket=bucket,
        key=key,
        storage_key=build_storage_key(bucket, key),
        upload_url=upload_url,
        download_url=download_url,
        upload_headers={"Content-Type": payload.content_type},
        expires_in_sec=payload.expires_in_sec,
    )
