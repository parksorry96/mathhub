import json
import random
import time
from decimal import Decimal

import httpx

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_MATHPIX_RETRIES = 3


def submit_mathpix_pdf(
    *,
    file_url: str,
    app_id: str,
    app_key: str,
    base_url: str,
    callback_url: str | None = None,
    include_diagram_text: bool = True,
) -> dict:
    payload: dict = {
        "url": file_url,
        # Keep diagram/chart internal text in lines.json to improve graph detection.
        "include_diagram_text": include_diagram_text,
    }
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


def ocr_mathpix_image(
    *,
    image_bytes: bytes,
    app_id: str,
    app_key: str,
    base_url: str,
    image_filename: str = "problem.png",
    content_type: str = "image/png",
    options: dict | None = None,
) -> dict:
    options_json = options or {"formats": ["text", "latex_styled", "data"]}
    with httpx.Client(timeout=60.0) as client:
        for attempt in range(1, _MAX_MATHPIX_RETRIES + 1):
            try:
                response = client.post(
                    f"{base_url.rstrip('/')}/text",
                    headers={
                        "app_id": app_id,
                        "app_key": app_key,
                    },
                    files={
                        "file": (image_filename, image_bytes, content_type),
                        "options_json": (None, json.dumps(options_json), "application/json"),
                    },
                )
                response.raise_for_status()
                data = response.json()
                if data.get("error") or data.get("error_info"):
                    error_message = data.get("error")
                    if not error_message and isinstance(data.get("error_info"), dict):
                        error_message = data["error_info"].get("message") or data["error_info"].get("id")
                    if not error_message:
                        error_message = json.dumps(data.get("error_info"), ensure_ascii=False)
                    raise RuntimeError(f"Mathpix text OCR error: {error_message}")
                return data
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in _TRANSIENT_STATUS_CODES or attempt >= _MAX_MATHPIX_RETRIES:
                    raise
                _sleep_before_retry(attempt=attempt, retry_after=exc.response.headers.get("retry-after"))
            except httpx.RequestError:
                if attempt >= _MAX_MATHPIX_RETRIES:
                    raise
                _sleep_before_retry(attempt=attempt, retry_after=None)

    raise RuntimeError("Mathpix text OCR failed after retries")


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


def fetch_mathpix_pdf_lines(
    *,
    provider_job_id: str,
    app_id: str,
    app_key: str,
    base_url: str,
) -> dict:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(
            f"{base_url.rstrip('/')}/pdf/{provider_job_id}.lines.json",
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
        lines = [_extract_line_text(line) for line in line_data if isinstance(line, dict)]
        lines = [line for line in lines if isinstance(line, str) and line]
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


def extract_mathpix_pages_from_lines(payload: dict) -> list[dict]:
    pages: list[dict] = []
    source_pages = payload.get("pages")
    if not isinstance(source_pages, list):
        return pages

    for index, item in enumerate(source_pages):
        if not isinstance(item, dict):
            continue

        page_no_raw = item.get("page") or item.get("page_no") or item.get("number") or (index + 1)
        try:
            page_no = int(page_no_raw)
        except Exception:
            page_no = index + 1

        lines = item.get("lines")
        text_lines: list[str] = []
        if isinstance(lines, list):
            for line in lines:
                if not isinstance(line, dict):
                    continue
                text = _extract_line_text(line)
                if text:
                    text_lines.append(text)

        extracted_text = "\n".join(text_lines).strip() if text_lines else None
        extracted_latex = _first_non_empty_str(item, ("latex_styled", "latex"))

        pages.append(
            {
                "page_no": page_no,
                "extracted_text": extracted_text or None,
                "extracted_latex": extracted_latex,
                "raw_payload": item,
            }
        )

    return pages


def merge_mathpix_pages(
    *,
    status_pages: list[dict],
    line_pages: list[dict],
) -> list[dict]:
    """Merge status-derived pages with lines.json pages (preferring lines raw payload)."""
    merged_by_page_no: dict[int, dict] = {}

    for index, page in enumerate(status_pages, start=1):
        if not isinstance(page, dict):
            continue
        page_no = _to_page_no(page.get("page_no"), fallback=index)
        merged_by_page_no[page_no] = {
            "page_no": page_no,
            "extracted_text": page.get("extracted_text"),
            "extracted_latex": page.get("extracted_latex"),
            "raw_payload": page.get("raw_payload"),
        }

    for index, page in enumerate(line_pages, start=1):
        if not isinstance(page, dict):
            continue
        page_no = _to_page_no(page.get("page_no"), fallback=index)
        line_raw = page.get("raw_payload")
        existing = merged_by_page_no.get(page_no)
        if not existing:
            merged_by_page_no[page_no] = {
                "page_no": page_no,
                "extracted_text": page.get("extracted_text"),
                "extracted_latex": page.get("extracted_latex"),
                "raw_payload": line_raw,
            }
            continue

        status_raw = existing.get("raw_payload")
        merged_raw: dict | object
        if isinstance(line_raw, dict):
            merged_raw = dict(line_raw)
            if isinstance(status_raw, dict):
                for key, value in status_raw.items():
                    merged_raw.setdefault(key, value)
                merged_raw["_mathpix_status_page"] = status_raw
        else:
            merged_raw = status_raw if status_raw is not None else line_raw

        existing["extracted_text"] = page.get("extracted_text") or existing.get("extracted_text")
        existing["extracted_latex"] = existing.get("extracted_latex") or page.get("extracted_latex")
        existing["raw_payload"] = merged_raw

    return [merged_by_page_no[page_no] for page_no in sorted(merged_by_page_no)]


def extract_mathpix_text_fields(payload: dict) -> tuple[str | None, str | None]:
    text = _first_non_empty_str(payload, ("text", "text_display", "markdown", "md", "html"))
    latex = _first_non_empty_str(payload, ("latex_styled", "latex"))
    if text is None and isinstance(payload.get("line_data"), list):
        lines = [_extract_line_text(line) for line in payload["line_data"] if isinstance(line, dict)]
        merged = "\n".join(line for line in lines if isinstance(line, str) and line).strip()
        text = merged or None
    return text, latex


def _to_page_no(value: object, *, fallback: int) -> int:
    try:
        page_no = int(value)  # type: ignore[arg-type]
    except Exception:
        page_no = fallback
    if page_no <= 0:
        return fallback
    return page_no


def _extract_line_text(line: dict) -> str | None:
    text = line.get("text")
    if isinstance(text, str):
        stripped = text.strip()
        if stripped:
            return stripped

    conversion_output = line.get("conversion_output")
    if isinstance(conversion_output, str):
        stripped = conversion_output.strip()
        if stripped:
            return stripped
    if isinstance(conversion_output, dict):
        for key in ("text", "markdown", "latex_styled", "latex", "value"):
            value = conversion_output.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
    return None


def _first_non_empty_str(source: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _sleep_before_retry(*, attempt: int, retry_after: str | None) -> None:
    delay = _parse_retry_after(retry_after)
    if delay is None:
        delay = min(6.0, 0.6 * (2 ** (attempt - 1)))
    delay += random.uniform(0, 0.2)
    time.sleep(delay)


def _parse_retry_after(retry_after: str | None) -> float | None:
    if retry_after is None:
        return None
    stripped = retry_after.strip()
    if not stripped:
        return None
    try:
        parsed = float(stripped)
    except Exception:
        return None
    return max(0.0, min(parsed, 10.0))
