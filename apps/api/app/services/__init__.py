from app.services.ai_classifier import classify_candidate, collect_problem_asset_hints, extract_problem_candidates
from app.services.gemini_document_scanner import (
    attach_answer_keys_to_scanned_pages,
    scan_pdf_document_with_gemini,
)
from app.services.mathpix_client import (
    extract_mathpix_text_fields,
    extract_mathpix_pages,
    extract_mathpix_pages_from_lines,
    fetch_mathpix_pdf_lines,
    fetch_mathpix_pdf_status,
    map_mathpix_job_status,
    ocr_mathpix_image,
    resolve_provider_job_id,
    submit_mathpix_pdf,
)
from app.services.problem_asset_extractor import ExtractedAsset, ProblemAssetExtractor
from app.services.s3_storage import (
    build_object_key,
    build_storage_key,
    create_s3_client,
    delete_object,
    ensure_s3_bucket,
    generate_presigned_get_url,
    generate_presigned_put_url,
    get_object_bytes,
    parse_storage_key,
    put_object_bytes,
)

__all__ = [
    "classify_candidate",
    "collect_problem_asset_hints",
    "extract_problem_candidates",
    "scan_pdf_document_with_gemini",
    "attach_answer_keys_to_scanned_pages",
    "submit_mathpix_pdf",
    "ocr_mathpix_image",
    "fetch_mathpix_pdf_status",
    "fetch_mathpix_pdf_lines",
    "resolve_provider_job_id",
    "map_mathpix_job_status",
    "extract_mathpix_pages",
    "extract_mathpix_pages_from_lines",
    "extract_mathpix_text_fields",
    "ProblemAssetExtractor",
    "ExtractedAsset",
    "create_s3_client",
    "ensure_s3_bucket",
    "build_object_key",
    "build_storage_key",
    "delete_object",
    "get_object_bytes",
    "put_object_bytes",
    "parse_storage_key",
    "generate_presigned_put_url",
    "generate_presigned_get_url",
]
