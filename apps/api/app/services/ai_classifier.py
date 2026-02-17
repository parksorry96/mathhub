import json
import re
from decimal import Decimal

import httpx

ALLOWED_SUBJECT_CODES = {"MATH_I", "MATH_II", "PROB_STATS", "CALCULUS", "GEOMETRY"}
ALLOWED_SOURCE_CATEGORIES = {"past_exam", "linked_textbook", "other"}
ALLOWED_SOURCE_TYPES = {
    "csat",
    "kice_mock",
    "office_mock",
    "ebs_linked",
    "private_mock",
    "workbook",
    "school_exam",
    "teacher_made",
    "other",
}
ALLOWED_VALIDATION_STATUSES = {"valid", "needs_review", "invalid"}

CANDIDATE_SPLIT_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*[\.)]\s+")


def extract_problem_candidates(text: str) -> list[dict]:
    cleaned = text.strip()
    if not cleaned:
        return []

    matches = list(CANDIDATE_SPLIT_RE.finditer(cleaned))
    if not matches:
        return [{"candidate_no": 1, "statement_text": cleaned}]

    candidates: list[dict] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        statement_text = cleaned[start:end].strip()
        if not statement_text:
            continue
        candidates.append(
            {
                "candidate_no": int(match.group(1)),
                "statement_text": statement_text,
            }
        )
    return candidates


def classify_candidate(
    statement_text: str,
    api_key: str | None,
    api_base_url: str,
    model: str,
) -> dict:
    if api_key:
        try:
            ai_result = _classify_candidate_via_api(
                statement_text=statement_text,
                api_key=api_key,
                api_base_url=api_base_url,
                model=model,
            )
            return _normalize_result(ai_result, provider="api", model=model)
        except Exception:
            # Fallback keeps the pipeline alive when API output is malformed or unavailable.
            pass

    heuristic = _heuristic_classification(statement_text)
    return _normalize_result(heuristic, provider="heuristic", model=model)


def _classify_candidate_via_api(
    statement_text: str,
    api_key: str,
    api_base_url: str,
    model: str,
) -> dict:
    prompt = (
        "너는 한국 고등학교 수학 문항 분류기다. 아래 문항을 보고 반드시 JSON 객체만 반환해. "
        "키는 subject_code, unit_code, point_value, source_category, source_type, "
        "validation_status, confidence, reason 를 사용해. "
        "subject_code는 MATH_I/MATH_II/PROB_STATS/CALCULUS/GEOMETRY 중 하나 또는 null. "
        "point_value는 2/3/4 또는 null. "
        "source_category는 past_exam/linked_textbook/other 또는 null. "
        "source_type은 csat/kice_mock/office_mock/ebs_linked/private_mock/workbook/school_exam/teacher_made/other 또는 null. "
        "validation_status는 valid/needs_review/invalid 중 하나. "
        "confidence는 0~100 숫자.\n\n"
        f"문항:\n{statement_text}"
    )

    url = f"{api_base_url.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": prompt,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    output_text = _extract_output_text(data)
    if not output_text:
        raise ValueError("AI API returned empty output")

    json_match = re.search(r"\{.*\}", output_text, re.DOTALL)
    if not json_match:
        raise ValueError("AI API output is not JSON")

    return json.loads(json_match.group(0))


def _extract_output_text(response_json: dict) -> str:
    direct = response_json.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    output = response_json.get("output")
    if not isinstance(output, list):
        return ""

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def _heuristic_classification(statement_text: str) -> dict:
    lowered = statement_text.lower()

    subject_code = "MATH_II"
    if any(keyword in statement_text for keyword in ["벡터", "포물선", "타원", "쌍곡선", "공간좌표"]):
        subject_code = "GEOMETRY"
    elif any(keyword in statement_text for keyword in ["확률", "통계", "조합", "이항정리", "조건부"]):
        subject_code = "PROB_STATS"
    elif any(keyword in statement_text for keyword in ["적분", "미분", "급수", "도함수"]):
        subject_code = "CALCULUS"
    elif any(keyword in statement_text for keyword in ["지수", "로그", "삼각함수", "수열"]):
        subject_code = "MATH_I"

    point_value = 3
    if any(keyword in statement_text for keyword in ["킬러", "최고난도"]):
        point_value = 4
    elif len(statement_text) < 80:
        point_value = 2

    validation_status = "needs_review"
    if len(statement_text) >= 30 and "?" in statement_text:
        validation_status = "valid"

    confidence = 35
    if "보기" in statement_text or "다음" in statement_text or "옳은" in statement_text:
        confidence = 55

    reason = "Heuristic classification (API key missing or API call failed)."
    if "mathpix" in lowered:
        reason = "Heuristic classification from OCR text."

    return {
        "subject_code": subject_code,
        "unit_code": None,
        "point_value": point_value,
        "source_category": "other",
        "source_type": "other",
        "validation_status": validation_status,
        "confidence": confidence,
        "reason": reason,
    }


def _normalize_result(result: dict, provider: str, model: str) -> dict:
    subject_code = result.get("subject_code")
    if subject_code not in ALLOWED_SUBJECT_CODES:
        subject_code = None

    unit_code = result.get("unit_code")
    if unit_code is not None:
        unit_code = str(unit_code)

    point_value = result.get("point_value")
    if point_value not in (2, 3, 4):
        point_value = None

    source_category = result.get("source_category")
    source_type = result.get("source_type")
    if source_category not in ALLOWED_SOURCE_CATEGORIES or source_type not in ALLOWED_SOURCE_TYPES:
        source_category = None
        source_type = None

    validation_status = result.get("validation_status")
    if validation_status not in ALLOWED_VALIDATION_STATUSES:
        validation_status = "needs_review"

    try:
        confidence_value = Decimal(str(result.get("confidence", 0)))
    except Exception:
        confidence_value = Decimal("0")
    confidence_value = max(Decimal("0"), min(Decimal("100"), confidence_value))

    reason = result.get("reason")
    if reason is not None:
        reason = str(reason)

    return {
        "subject_code": subject_code,
        "unit_code": unit_code,
        "point_value": point_value,
        "source_category": source_category,
        "source_type": source_type,
        "validation_status": validation_status,
        "confidence": confidence_value,
        "reason": reason,
        "provider": provider,
        "model": model,
    }
