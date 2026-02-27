from __future__ import annotations

import base64
import json
import random
import re
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from decimal import Decimal

import httpx

try:
    import pymupdf  # type: ignore
except Exception:  # pragma: no cover - runtime fallback for older wheels
    try:
        import fitz as pymupdf  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        pymupdf = None  # type: ignore


PAGE_TYPES = {
    "cover",
    "toc",
    "concept",
    "problem",
    "answer",
    "explanation",
    "mixed",
    "other",
}
ALLOWED_SUBJECT_CODES = {"MATH_I", "MATH_II", "PROB_STATS", "CALCULUS", "GEOMETRY"}
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_GEMINI_RETRIES_PER_MODEL = 4
_RETRY_BASE_DELAY_SECONDS = 0.8
_RETRY_MAX_DELAY_SECONDS = 8.0
_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"
_DEFAULT_MAX_PARALLEL_PAGES = 3
_DEFAULT_MAX_OUTPUT_TOKENS = 2048
_DEFAULT_FLASH_THINKING_BUDGET = 0


_GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_type": {
            "type": "string",
            "enum": ["cover", "toc", "concept", "problem", "answer", "explanation", "mixed", "other"],
        },
        "page_summary": {"type": "string"},
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_no": {"type": "integer"},
                    "question_no": {"type": "integer"},
                    "statement_text": {"type": "string"},
                    "subject_code": {"type": "string"},
                    "problem_type": {"type": "string"},
                    "answer_key": {"type": "string"},
                    "has_visual_asset": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "bbox": {
                        "type": "object",
                        "properties": {
                            "x0_ratio": {"type": "number"},
                            "y0_ratio": {"type": "number"},
                            "x1_ratio": {"type": "number"},
                            "y1_ratio": {"type": "number"},
                        },
                        "required": ["x0_ratio", "y0_ratio", "x1_ratio", "y1_ratio"],
                    },
                },
                "required": ["statement_text", "bbox"],
            },
        },
        "answer_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_no": {"type": "integer"},
                    "answer_key": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["question_no", "answer_key"],
            },
        },
    },
}


def scan_pdf_document_with_gemini(
    *,
    pdf_bytes: bytes,
    api_key: str,
    base_url: str,
    model: str,
    max_pages: int,
    render_scale: float = 1.6,
    temperature: float = 0.1,
    max_parallel_pages: int = _DEFAULT_MAX_PARALLEL_PAGES,
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    thinking_budget: int | None = _DEFAULT_FLASH_THINKING_BUDGET,
) -> list[dict]:
    if not pymupdf:
        raise RuntimeError("PyMuPDF is unavailable in runtime environment.")
    if max_pages <= 0:
        return []

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        total_pages = min(len(doc), max_pages)
        if total_pages <= 0:
            return []
        parallel = max(1, int(max_parallel_pages))
        normalized_max_output_tokens = _clamp_int(max_output_tokens, lower=256, upper=8192)
        if parallel == 1:
            with _create_gemini_http_client() as client:
                pages: list[dict] = []
                for page_no in range(1, total_pages + 1):
                    image_bytes = _render_pdf_page_to_png(doc=doc, page_no=page_no, render_scale=render_scale)
                    pages.append(
                        _scan_rendered_page_with_gemini(
                            image_bytes=image_bytes,
                            page_no=page_no,
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            temperature=temperature,
                            max_output_tokens=normalized_max_output_tokens,
                            thinking_budget=thinking_budget,
                            client=client,
                        )
                    )
                return pages
        return _scan_document_pages_in_parallel(
            doc=doc,
            total_pages=total_pages,
            render_scale=render_scale,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_parallel_pages=parallel,
            max_output_tokens=normalized_max_output_tokens,
            thinking_budget=thinking_budget,
        )
    finally:
        doc.close()


def _scan_document_pages_in_parallel(
    *,
    doc,
    total_pages: int,
    render_scale: float,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_parallel_pages: int,
    max_output_tokens: int,
    thinking_budget: int | None,
) -> list[dict]:
    if total_pages <= 0:
        return []

    max_workers = min(total_pages, max(1, max_parallel_pages))
    page_results: dict[int, dict] = {}
    future_to_page_no: dict[Future[dict], int] = {}
    next_page_no = 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while next_page_no <= total_pages and len(future_to_page_no) < max_workers:
            image_bytes = _render_pdf_page_to_png(doc=doc, page_no=next_page_no, render_scale=render_scale)
            future = executor.submit(
                _scan_rendered_page_with_gemini,
                image_bytes=image_bytes,
                page_no=next_page_no,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
            )
            future_to_page_no[future] = next_page_no
            next_page_no += 1

        while future_to_page_no:
            done, _ = wait(set(future_to_page_no.keys()), return_when=FIRST_COMPLETED)
            for finished in done:
                page_no = future_to_page_no.pop(finished)
                page_results[page_no] = finished.result()
                if next_page_no <= total_pages:
                    image_bytes = _render_pdf_page_to_png(doc=doc, page_no=next_page_no, render_scale=render_scale)
                    future = executor.submit(
                        _scan_rendered_page_with_gemini,
                        image_bytes=image_bytes,
                        page_no=next_page_no,
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        thinking_budget=thinking_budget,
                    )
                    future_to_page_no[future] = next_page_no
                    next_page_no += 1

    return [page_results[page_no] for page_no in range(1, total_pages + 1)]


def _render_pdf_page_to_png(*, doc, page_no: int, render_scale: float) -> bytes:
    page = doc[page_no - 1]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False)
    return pix.tobytes("png")


def _scan_rendered_page_with_gemini(
    *,
    image_bytes: bytes,
    page_no: int,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    thinking_budget: int | None,
    client: httpx.Client | None = None,
) -> dict:
    result, used_model = _scan_page_with_gemini(
        image_bytes=image_bytes,
        page_no=page_no,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_budget=thinking_budget,
        client=client,
    )
    return _normalize_scanned_page(result, page_no=page_no, model=used_model)


def attach_answer_keys_to_scanned_pages(scanned_pages: list[dict]) -> int:
    answer_map: dict[int, str] = {}
    for page in scanned_pages:
        answer_candidates = page.get("answer_candidates")
        if not isinstance(answer_candidates, list):
            continue
        for answer_item in answer_candidates:
            if not isinstance(answer_item, dict):
                continue
            question_no = _to_positive_int(answer_item.get("question_no"))
            answer_key = _normalize_answer_key(answer_item.get("answer_key"))
            if question_no and answer_key and question_no not in answer_map:
                answer_map[question_no] = answer_key

    if not answer_map:
        return 0

    matched = 0
    for page in scanned_pages:
        problems = page.get("problems")
        if not isinstance(problems, list):
            continue
        for problem in problems:
            if not isinstance(problem, dict):
                continue
            question_no = _to_positive_int(problem.get("question_no"))
            if not question_no:
                continue
            if problem.get("answer_key"):
                continue
            answer_key = answer_map.get(question_no)
            if not answer_key:
                continue
            problem["answer_key"] = answer_key
            problem["answer_source"] = "answer_page"
            matched += 1
    return matched


def _scan_page_with_gemini(
    *,
    image_bytes: bytes,
    page_no: int,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    thinking_budget: int | None = _DEFAULT_FLASH_THINKING_BUDGET,
    client: httpx.Client | None = None,
) -> tuple[dict, str]:
    if client is None:
        with _create_gemini_http_client() as managed_client:
            return _scan_page_with_gemini(
                image_bytes=image_bytes,
                page_no=page_no,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
                client=managed_client,
            )

    model_candidates = _build_model_candidates(model)
    transient_failure: _GeminiTransientModelFailure | None = None
    attempted_models: list[str] = []
    for model_candidate in model_candidates:
        try:
            result = _scan_page_with_gemini_model(
                image_bytes=image_bytes,
                page_no=page_no,
                api_key=api_key,
                base_url=base_url,
                model=model_candidate,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
                client=client,
            )
            return result, model_candidate
        except _GeminiTransientModelFailure as exc:
            transient_failure = exc
            attempted_models.append(model_candidate)
            continue

    if transient_failure:
        attempted = ", ".join(attempted_models)
        raise RuntimeError(
            f"Gemini transient failure on page {page_no} after retries "
            f"(attempted models: {attempted}): {transient_failure}"
        ) from transient_failure
    raise RuntimeError(f"Gemini scan failed on page {page_no}")


def _scan_page_with_gemini_model(
    *,
    image_bytes: bytes,
    page_no: int,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
    thinking_budget: int | None,
    client: httpx.Client,
) -> dict:
    prompt = (
        "You analyze one textbook page image for Korean high-school math ingestion.\n"
        "Return ONLY JSON.\n"
        "Tasks:\n"
        "1) classify page_type as cover/toc/concept/problem/answer/explanation/mixed/other.\n"
        "2) extract problem candidates only when they are real question statements.\n"
        "3) for each problem, provide normalized bbox ratios x0_ratio,y0_ratio,x1_ratio,y1_ratio in [0,1].\n"
        "4) if answer keys are visible (answer/explanation pages), extract answer_candidates as {question_no, answer_key}.\n"
        "5) use subject_code only from MATH_I,MATH_II,PROB_STATS,CALCULUS,GEOMETRY when inferable.\n"
        f"Current page number: {page_no}"
    )
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": image_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            **_build_generation_config(
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_budget=thinking_budget,
            )
        },
    }

    last_status: int | None = None
    for attempt in range(1, _MAX_GEMINI_RETRIES_PER_MODEL + 1):
        try:
            response = client.post(
                url,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return _parse_gemini_response_payload(data)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code not in _TRANSIENT_STATUS_CODES:
                raise
            last_status = status_code
            if attempt >= _MAX_GEMINI_RETRIES_PER_MODEL:
                break
            _sleep_before_retry(attempt=attempt, retry_after=exc.response.headers.get("retry-after"))
        except httpx.RequestError:
            if attempt >= _MAX_GEMINI_RETRIES_PER_MODEL:
                break
            _sleep_before_retry(attempt=attempt, retry_after=None)

    raise _GeminiTransientModelFailure(
        page_no=page_no,
        model=model,
        max_attempts=_MAX_GEMINI_RETRIES_PER_MODEL,
        last_status=last_status,
    )


def _parse_gemini_response_payload(data: dict) -> dict:
    text = _extract_gemini_text(data)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}


def _build_model_candidates(primary_model: str) -> list[str]:
    candidates: list[str] = []
    normalized_primary = primary_model.strip()
    if normalized_primary:
        candidates.append(normalized_primary)
    if _GEMINI_FALLBACK_MODEL not in candidates:
        candidates.append(_GEMINI_FALLBACK_MODEL)
    return candidates


def _create_gemini_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=90.0,
        http2=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def _build_generation_config(
    *,
    model: str,
    temperature: float,
    max_output_tokens: int,
    thinking_budget: int | None,
) -> dict:
    generation_config: dict = {
        "temperature": temperature,
        "responseMimeType": "application/json",
        "responseSchema": _GEMINI_RESPONSE_SCHEMA,
        "candidateCount": 1,
        "maxOutputTokens": _clamp_int(max_output_tokens, lower=256, upper=8192),
    }

    if thinking_budget is not None and _should_include_thinking_budget(model):
        generation_config["thinkingConfig"] = {
            "thinkingBudget": _clamp_int(thinking_budget, lower=0, upper=24576),
        }

    return generation_config


def _should_include_thinking_budget(model: str) -> bool:
    model_name = model.strip().lower()
    return "2.5" in model_name and "flash" in model_name


def _sleep_before_retry(*, attempt: int, retry_after: str | None) -> None:
    delay = _parse_retry_after(retry_after)
    if delay is None:
        delay = min(_RETRY_MAX_DELAY_SECONDS, _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    delay += random.uniform(0, 0.25)
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
    return max(0.0, min(parsed, _RETRY_MAX_DELAY_SECONDS))


def _clamp_int(value: int, *, lower: int, upper: int) -> int:
    parsed = int(value)
    if parsed < lower:
        return lower
    if parsed > upper:
        return upper
    return parsed


class _GeminiTransientModelFailure(RuntimeError):
    def __init__(self, *, page_no: int, model: str, max_attempts: int, last_status: int | None):
        status_label = str(last_status) if last_status is not None else "request-error"
        super().__init__(
            f"page={page_no}, model={model}, attempts={max_attempts}, last_status={status_label}"
        )


def _extract_gemini_text(data: dict) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _normalize_scanned_page(raw: dict, *, page_no: int, model: str) -> dict:
    page_type = str(raw.get("page_type") or "other").strip().lower()
    if page_type not in PAGE_TYPES:
        page_type = "other"

    page_summary = str(raw.get("page_summary") or "").strip()
    normalized_problems: list[dict] = []
    raw_problems = raw.get("problems")
    if isinstance(raw_problems, list):
        for index, item in enumerate(raw_problems, start=1):
            normalized = _normalize_problem_item(item, fallback_index=index, model=model)
            if normalized:
                normalized_problems.append(normalized)

    normalized_answers: list[dict] = []
    raw_answers = raw.get("answer_candidates")
    if isinstance(raw_answers, list):
        for item in raw_answers:
            normalized = _normalize_answer_item(item)
            if normalized:
                normalized_answers.append(normalized)

    return {
        "page_no": page_no,
        "page_type": page_type,
        "page_summary": page_summary,
        "problems": normalized_problems,
        "answer_candidates": normalized_answers,
    }


def _normalize_problem_item(item: object, *, fallback_index: int, model: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    statement_text = str(item.get("statement_text") or item.get("statement") or "").strip()
    if not statement_text:
        return None

    bbox = _normalize_bbox(item.get("bbox"))
    if bbox is None:
        return None

    candidate_no = _to_positive_int(item.get("candidate_no")) or fallback_index
    question_no = _to_positive_int(item.get("question_no"))
    subject_code_raw = item.get("subject_code")
    subject_code = str(subject_code_raw).strip().upper() if subject_code_raw is not None else None
    if subject_code not in ALLOWED_SUBJECT_CODES:
        subject_code = None

    problem_type = str(item.get("problem_type") or "").strip() or None
    answer_key = _normalize_answer_key(item.get("answer_key"))
    has_visual_asset = bool(item.get("has_visual_asset"))
    confidence = _to_confidence(item.get("confidence"))

    return {
        "candidate_no": candidate_no,
        "question_no": question_no,
        "statement_text": statement_text,
        "split_strategy": "gemini_pdf_scan",
        "bbox": bbox,
        "subject_code": subject_code,
        "problem_type": problem_type,
        "answer_key": answer_key,
        "has_visual_asset": has_visual_asset,
        "confidence": confidence,
        "validation_status": "needs_review",
        "provider": "gemini",
        "model": model,
    }


def _normalize_answer_item(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    question_no = _to_positive_int(item.get("question_no"))
    answer_key = _normalize_answer_key(item.get("answer_key"))
    if not question_no or not answer_key:
        return None
    evidence = str(item.get("evidence") or "").strip() or None
    return {
        "question_no": question_no,
        "answer_key": answer_key,
        "evidence": evidence,
    }


def _normalize_bbox(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    try:
        x0 = float(value.get("x0_ratio"))
        y0 = float(value.get("y0_ratio"))
        x1 = float(value.get("x1_ratio"))
        y1 = float(value.get("y1_ratio"))
    except Exception:
        return None

    x0 = _clamp01(x0)
    y0 = _clamp01(y0)
    x1 = _clamp01(x1)
    y1 = _clamp01(y1)
    if x1 <= x0 or y1 <= y0:
        return None

    min_span = 0.01
    if (x1 - x0) < min_span:
        x1 = min(1.0, x0 + min_span)
    if (y1 - y0) < min_span:
        y1 = min(1.0, y0 + min_span)

    return {
        "x0_ratio": round(x0, 6),
        "y0_ratio": round(y0, 6),
        "x1_ratio": round(x1, 6),
        "y1_ratio": round(y1, 6),
    }


def _to_confidence(value: object) -> float:
    try:
        parsed = Decimal(str(value))
    except Exception:
        parsed = Decimal("65")
    parsed = max(Decimal("0"), min(Decimal("100"), parsed))
    return float(parsed)


def _normalize_answer_key(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"\s+", "", cleaned)
    if len(cleaned) > 40:
        return cleaned[:40]
    return cleaned


def _to_positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except Exception:
        return None
    if parsed > 0:
        return parsed
    return None


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value
