import json
from decimal import Decimal

import httpx


def submit_mathpix_pdf(
    *,
    file_url: str,
    app_id: str,
    app_key: str,
    base_url: str,
    callback_url: str | None = None,
) -> dict:
    payload: dict = {"url": file_url}
    if callback_url:
        payload["callback"] = callback_url

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/pdf",
            headers={
                "app_id": app_id,
                "app_key": app_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        has_job_id = any(data.get(key) for key in ("pdf_id", "id", "job_id", "request_id"))
        if not has_job_id and (data.get("error") or data.get("error_info")):
            error_message = data.get("error")
            if not error_message and isinstance(data.get("error_info"), dict):
                error_message = data["error_info"].get("message") or data["error_info"].get("id")
            if not error_message:
                error_message = json.dumps(data.get("error_info"), ensure_ascii=False)
            raise RuntimeError(f"Mathpix submit error: {error_message}")

        return data


def fetch_mathpix_pdf_status(
    *,
    provider_job_id: str,
    app_id: str,
    app_key: str,
    base_url: str,
) -> dict:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(
            f"{base_url.rstrip('/')}/pdf/{provider_job_id}",
            headers={
                "app_id": app_id,
                "app_key": app_key,
            },
        )
        response.raise_for_status()
        return response.json()


def resolve_provider_job_id(payload: dict) -> str | None:
    for key in ("pdf_id", "id", "job_id", "request_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def map_mathpix_job_status(payload: dict) -> tuple[str, Decimal, str | None]:
    raw_status = str(payload.get("status") or payload.get("state") or "").strip().lower()
    error_message = None

    if isinstance(payload.get("error"), dict):
        error_message = payload["error"].get("message") or json.dumps(payload["error"], ensure_ascii=False)
    elif payload.get("error"):
        error_message = str(payload.get("error"))

    progress_value = (
        payload.get("percent_done")
        or payload.get("progress_pct")
        or payload.get("progress")
        or payload.get("percent")
        or 0
    )
    try:
        progress = Decimal(str(progress_value))
    except Exception:
        progress = Decimal("0")

    if progress <= Decimal("1"):
        progress = progress * Decimal("100")
    progress = max(Decimal("0"), min(Decimal("100"), progress))

    completed = bool(payload.get("completed")) or raw_status in {
        "completed",
        "complete",
        "done",
        "success",
        "succeeded",
    }
    failed = bool(error_message) or raw_status in {"failed", "failure", "error", "cancelled", "canceled"}

    if completed:
        return "completed", Decimal("100"), None
    if failed:
        return "failed", progress, error_message or "Mathpix returned failure status"
    if raw_status in {"queued", "uploaded", "uploading"}:
        return "uploading", progress, None
    return "processing", progress, None


def extract_mathpix_pages(payload: dict) -> list[dict]:
    pages: list[dict] = []
    source_pages = payload.get("pages")
    if isinstance(source_pages, list):
        for index, item in enumerate(source_pages):
            if not isinstance(item, dict):
                continue
            page_no_raw = item.get("page") or item.get("page_no") or item.get("number") or (index + 1)
            try:
                page_no = int(page_no_raw)
            except Exception:
                page_no = index + 1

            extracted_text = _first_non_empty_str(
                item,
                (
                    "text",
                    "markdown",
                    "md",
                    "content",
                    "html",
                    "latex_styled",
                    "latex",
                ),
            )
            extracted_latex = _first_non_empty_str(item, ("latex_styled", "latex"))

            pages.append(
                {
                    "page_no": page_no,
                    "extracted_text": extracted_text,
                    "extracted_latex": extracted_latex,
                    "raw_payload": item,
                }
            )
        return pages

    line_data = payload.get("line_data")
    if isinstance(line_data, list):
        lines = [line.get("text") for line in line_data if isinstance(line, dict) and isinstance(line.get("text"), str)]
        pages.append(
            {
                "page_no": 1,
                "extracted_text": "\n".join(lines).strip() if lines else None,
                "extracted_latex": None,
                "raw_payload": {"line_data": line_data},
            }
        )
        return pages

    text_value = payload.get("text")
    if isinstance(text_value, str) and text_value.strip():
        pages.append(
            {
                "page_no": 1,
                "extracted_text": text_value.strip(),
                "extracted_latex": None,
                "raw_payload": {"text": text_value},
            }
        )
    return pages


def _first_non_empty_str(source: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None
