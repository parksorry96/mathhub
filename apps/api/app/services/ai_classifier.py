import json
import re
from decimal import Decimal
from typing import Any

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
BRACKETED_CANDIDATE_SPLIT_RE = re.compile(r"(?m)^\s*\[(\d{1,2})\]\s+")
QUESTION_LABEL_SPLIT_RE = re.compile(r"(?m)^\s*문항\s*(\d{1,2})\s*(?:번)?\s*[:.)]?\s*")
NUMBER_WITH_BEON_SPLIT_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*번\s+")

TEXT_ASSET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "image": ("그림", "도형", "diagram", "figure", "image", "사진"),
    "graph": ("그래프", "좌표평면", "plot", "graph", "chart", "곡선"),
    "table": ("표", "table", "tabular", "도수분포표"),
}

PAYLOAD_ASSET_TOKENS: dict[str, tuple[str, ...]] = {
    "image": ("image", "figure", "diagram", "img", "picture"),
    "graph": ("graph", "plot", "chart", "axis", "coordinate"),
    "table": ("table", "tabular", "grid"),
}


def extract_problem_candidates(text: str) -> list[dict]:
    cleaned = text.strip()
    if not cleaned:
        return []

    matches, split_strategy = _select_best_split_matches(cleaned)
    if not matches:
        return [{"candidate_no": 1, "statement_text": cleaned, "split_strategy": "full_page_fallback"}]

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
                "split_strategy": split_strategy,
            }
        )
    return candidates


def _select_best_split_matches(text: str) -> tuple[list[re.Match], str]:
    patterns = [
        ("numbered", CANDIDATE_SPLIT_RE),
        ("bracketed", BRACKETED_CANDIDATE_SPLIT_RE),
        ("question_label", QUESTION_LABEL_SPLIT_RE),
        ("number_with_beon", NUMBER_WITH_BEON_SPLIT_RE),
    ]

    best_matches: list[re.Match] = []
    best_strategy = "numbered"
    best_score = -1

    for strategy, pattern in patterns:
        matches = list(pattern.finditer(text))
        if not matches:
            continue

        numbers: list[int] = []
        for match in matches:
            try:
                numbers.append(int(match.group(1)))
            except Exception:
                pass
        score = len(matches)
        if _is_likely_problem_sequence(numbers):
            score += 2

        if score > best_score:
            best_score = score
            best_matches = matches
            best_strategy = strategy

    return best_matches, best_strategy


def _is_likely_problem_sequence(numbers: list[int]) -> bool:
    if len(numbers) <= 1:
        return False
    increasing = 0
    for previous, current in zip(numbers, numbers[1:]):
        if 0 < current - previous <= 3:
            increasing += 1
    return increasing >= max(1, len(numbers) - 2)


def collect_problem_asset_hints(statement_text: str, page_raw_payload: dict | None = None) -> list[dict]:
    hints: list[dict] = []
    normalized = statement_text.strip().lower()

    if normalized:
        for asset_type, keywords in TEXT_ASSET_KEYWORDS.items():
            matched = [keyword for keyword in keywords if keyword.lower() in normalized]
            if matched:
                hints.append(
                    {
                        "asset_type": asset_type,
                        "source": "statement_text",
                        "bbox": None,
                        "evidence": matched,
                    }
                )

    if isinstance(page_raw_payload, dict):
        hints.extend(_collect_payload_asset_hints(page_raw_payload))
        hints.extend(_collect_payload_text_hints(page_raw_payload))

    return _dedupe_asset_hints(hints)


def _collect_payload_text_hints(payload: dict) -> list[dict]:
    try:
        serialized = json.dumps(payload, ensure_ascii=False).lower()
    except Exception:
        return []

    hints: list[dict] = []
    for asset_type, tokens in PAYLOAD_ASSET_TOKENS.items():
        matched = [token for token in tokens if token in serialized]
        if not matched:
            continue
        hints.append(
            {
                "asset_type": asset_type,
                "source": "raw_payload_text",
                "bbox": None,
                "evidence": matched[:5],
            }
        )
    return hints


def _collect_payload_asset_hints(payload: Any, depth: int = 0) -> list[dict]:
    if depth > 6:
        return []

    hints: list[dict] = []

    if isinstance(payload, dict):
        inferred_type = _infer_asset_type_from_node(payload)
        if inferred_type:
            hints.append(
                {
                    "asset_type": inferred_type,
                    "source": "raw_payload_node",
                    "bbox": _extract_bbox(payload),
                    "evidence": _collect_node_tokens(payload),
                }
            )
        for value in payload.values():
            hints.extend(_collect_payload_asset_hints(value, depth + 1))
        return hints

    if isinstance(payload, list):
        for item in payload:
            hints.extend(_collect_payload_asset_hints(item, depth + 1))
        return hints

    return hints


def _collect_node_tokens(node: dict) -> list[str]:
    tokens: list[str] = []
    for key in ("type", "kind", "class", "label", "name", "category"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(value.strip().lower())
    return tokens[:6]


def _infer_asset_type_from_node(node: dict) -> str | None:
    tokens = _collect_node_tokens(node)
    combined = " ".join(tokens)
    if not combined:
        return None

    if any(token in combined for token in PAYLOAD_ASSET_TOKENS["graph"]):
        return "graph"
    if any(token in combined for token in PAYLOAD_ASSET_TOKENS["table"]):
        return "table"
    if any(token in combined for token in PAYLOAD_ASSET_TOKENS["image"]):
        return "image"
    return None


def _extract_bbox(node: dict) -> dict | None:
    bbox_value = node.get("bbox")
    if isinstance(bbox_value, dict):
        return bbox_value
    if isinstance(bbox_value, list) and len(bbox_value) == 4:
        try:
            return {
                "x1": float(bbox_value[0]),
                "y1": float(bbox_value[1]),
                "x2": float(bbox_value[2]),
                "y2": float(bbox_value[3]),
            }
        except Exception:
            return None

    left = node.get("left")
    top = node.get("top")
    right = node.get("right")
    bottom = node.get("bottom")
    if all(value is not None for value in (left, top, right, bottom)):
        try:
            return {
                "left": float(left),
                "top": float(top),
                "right": float(right),
                "bottom": float(bottom),
            }
        except Exception:
            return None

    x = node.get("x")
    y = node.get("y")
    width = node.get("w") or node.get("width")
    height = node.get("h") or node.get("height")
    if all(value is not None for value in (x, y, width, height)):
        try:
            return {
                "x": float(x),
                "y": float(y),
                "w": float(width),
                "h": float(height),
            }
        except Exception:
            return None

    return None


def _dedupe_asset_hints(hints: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for hint in hints:
        asset_type = str(hint.get("asset_type") or "other").strip().lower()
        if asset_type not in {"image", "table", "graph", "other"}:
            asset_type = "other"
        source = str(hint.get("source") or "unknown").strip().lower()
        bbox = hint.get("bbox")
        evidence = hint.get("evidence")
        evidence_key = tuple(sorted(str(item) for item in evidence)) if isinstance(evidence, list) else tuple()
        bbox_key = json.dumps(bbox, ensure_ascii=False, sort_keys=True) if isinstance(bbox, dict) else ""
        key = (asset_type, source, bbox_key, evidence_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "asset_type": asset_type,
                "source": source,
                "bbox": bbox if isinstance(bbox, dict) else None,
                "evidence": list(evidence_key) if evidence_key else [],
            }
        )
    return deduped


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
