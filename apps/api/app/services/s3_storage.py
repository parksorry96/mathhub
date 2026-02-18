from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

import boto3
from botocore.client import BaseClient

from app.config import (
    get_s3_access_key_id,
    get_s3_bucket,
    get_s3_endpoint_url,
    get_s3_region,
    get_s3_secret_access_key,
    get_s3_session_token,
)


def create_s3_client() -> BaseClient:
    access_key = get_s3_access_key_id()
    secret_key = get_s3_secret_access_key()
    region = get_s3_region()
    endpoint_url = get_s3_endpoint_url() or f"https://s3.{region}.amazonaws.com"
    if not access_key or not secret_key:
        raise ValueError("S3 credentials missing: set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY")

    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=get_s3_session_token(),
        endpoint_url=endpoint_url,
    )


def ensure_s3_bucket() -> str:
    bucket = get_s3_bucket()
    if not bucket:
        raise ValueError("S3_BUCKET is not set")
    return bucket


def sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", filename).strip("-")
    return cleaned or "file.pdf"


def build_object_key(filename: str, prefix: str = "ocr") -> str:
    safe_filename = sanitize_filename(filename)
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    return f"{prefix}/{today}/{uuid4().hex}-{safe_filename}"


def build_storage_key(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def parse_storage_key(storage_key: str) -> tuple[str, str]:
    if not storage_key.startswith("s3://"):
        raise ValueError("storage_key must start with s3://")
    without_scheme = storage_key[5:]
    if "/" not in without_scheme:
        raise ValueError("storage_key format must be s3://bucket/key")
    bucket, key = without_scheme.split("/", 1)
    if not bucket or not key:
        raise ValueError("storage_key format must be s3://bucket/key")
    return bucket, key


def generate_presigned_put_url(
    *,
    client: BaseClient,
    bucket: str,
    key: str,
    content_type: str,
    expires_in: int = 900,
) -> str:
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )


def generate_presigned_get_url(
    *,
    client: BaseClient,
    bucket: str,
    key: str,
    expires_in: int = 900,
) -> str:
    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
        },
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )
