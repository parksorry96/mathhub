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


def extract_problem_candidates(text: str, page_raw_payload: dict | None = None) -> list[dict]:
    if isinstance(page_raw_payload, dict):
        structured = _extract_problem_candidates_from_layout(page_raw_payload)
        if structured:
            return structured

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


def collect_problem_asset_hints(
    statement_text: str,
    page_raw_payload: dict | None = None,
    *,
    candidate_bbox: dict | None = None,
) -> list[dict]:
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
        payload_hints = _collect_payload_asset_hints(page_raw_payload)
        if isinstance(candidate_bbox, dict):
            payload_hints = _filter_asset_hints_by_candidate_bbox(payload_hints, candidate_bbox)
        hints.extend(payload_hints)
        if candidate_bbox is None:
            hints.extend(_collect_payload_text_hints(page_raw_payload))

    # When OCR text strongly suggests a graph but payload lacks explicit graph nodes,
    # fallback to candidate bbox so extraction can still crop the local question area.
    if (
        isinstance(candidate_bbox, dict)
        and any(keyword.lower() in normalized for keyword in TEXT_ASSET_KEYWORDS["graph"])
        and not any(str(item.get("asset_type")) == "graph" for item in hints)
    ):
        hints.append(
            {
                "asset_type": "graph",
                "source": "statement_text_bbox_fallback",
                "bbox": candidate_bbox,
                "evidence": ["keyword_graph"],
            }
        )

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
    for key in ("bbox", "cnt"):
        xyxy = _to_bbox_xyxy(node.get(key))
        if xyxy:
            return _bbox_dict_from_xyxy(xyxy)

    region = node.get("region")
    if isinstance(region, dict):
        width = region.get("width")
        height = region.get("height")
        top_left_x = region.get("top_left_x")
        top_left_y = region.get("top_left_y")
        if all(value is not None for value in (width, height, top_left_x, top_left_y)):
            try:
                x1 = float(top_left_x)
                y1 = float(top_left_y)
                x2 = x1 + float(width)
                y2 = y1 + float(height)
                return _bbox_dict_from_xyxy((x1, y1, x2, y2))
            except Exception:
                pass

    xyxy = _to_bbox_xyxy(node)
    if xyxy:
        return _bbox_dict_from_xyxy(xyxy)
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


def _extract_problem_candidates_from_layout(payload: dict) -> list[dict]:
    lines_raw = payload.get("lines")
    if not isinstance(lines_raw, list):
        return []

    nodes = [item for item in lines_raw if isinstance(item, dict)]
    if len(nodes) < 3:
        return []

    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    root_candidates: list[dict] = []
    for node in nodes:
        if str(node.get("type") or "").strip().lower() != "column":
            continue
        children = node.get("children_ids")
        if not isinstance(children, list) or not children:
            continue

        root_bbox = _extract_bbox(node)
        if not root_bbox:
            continue

        descendants = [node, *_collect_descendants(node, node_by_id)]
        statement_text = _build_statement_text(descendants)
        candidate_no = _infer_candidate_no(descendants)
        has_choice_block = any(
            str(item.get("type") or "").strip().lower() == "multiple_choice_block"
            for item in descendants
            if isinstance(item, dict)
        )
        if not statement_text and not has_choice_block:
            continue

        root_candidates.append(
            {
                "candidate_no": candidate_no,
                "statement_text": statement_text,
                "bbox": root_bbox,
                "split_strategy": "layout_columns",
            }
        )

    if not root_candidates:
        return []

    page_width = _resolve_page_width(payload, root_candidates)
    layout_mode, split_x = _detect_layout_mode(root_candidates, page_width)
    ordered = sorted(
        root_candidates,
        key=lambda item: _candidate_layout_sort_key(item, layout_mode=layout_mode, split_x=split_x),
    )

    used_candidate_no: set[int] = set()
    finalized: list[dict] = []
    for index, item in enumerate(ordered, start=1):
        bbox = _extract_bbox(item) if not isinstance(item.get("bbox"), dict) else item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        xyxy = _to_bbox_xyxy(bbox)
        if not xyxy:
            continue
        bbox = _bbox_dict_from_xyxy(xyxy)
        x1, _, x2, _ = xyxy
        center_x = (x1 + x2) / 2.0

        candidate_no = item.get("candidate_no")
        if not isinstance(candidate_no, int) or candidate_no <= 0 or candidate_no in used_candidate_no:
            candidate_no = index
            while candidate_no in used_candidate_no:
                candidate_no += 1
        used_candidate_no.add(candidate_no)

        layout_column = 1
        if layout_mode == "two_column":
            layout_column = 1 if center_x <= split_x else 2

        split_strategy = "layout_columns_two" if layout_mode == "two_column" else "layout_columns_single"
        statement_text = str(item.get("statement_text") or "").strip()
        if not statement_text:
            statement_text = f"{candidate_no}번 문항"

        finalized.append(
            {
                "candidate_no": candidate_no,
                "statement_text": statement_text,
                "split_strategy": split_strategy,
                "bbox": bbox,
                "layout_column": layout_column,
                "layout_mode": layout_mode,
            }
        )

    return finalized


def _collect_descendants(root: dict, node_by_id: dict[str, dict]) -> list[dict]:
    descendants: list[dict] = []
    queue = [str(item) for item in (root.get("children_ids") or []) if item]
    seen: set[str] = set()
    while queue:
        current_id = queue.pop(0)
        if current_id in seen:
            continue
        seen.add(current_id)
        node = node_by_id.get(current_id)
        if not isinstance(node, dict):
            continue
        descendants.append(node)
        children = node.get("children_ids")
        if isinstance(children, list):
            queue.extend(str(item) for item in children if item)
    return descendants


def _extract_node_text(node: dict) -> str:
    for key in ("text", "text_display"):
        value = node.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped

    conversion_output = node.get("conversion_output")
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
    return ""


def _build_statement_text(nodes: list[dict]) -> str:
    rows: list[tuple[float, float, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").strip().lower()
        if node_type in {"page_info", "column"}:
            continue
        text = _extract_node_text(node)
        if not text:
            continue
        bbox = _extract_bbox(node)
        xyxy = _to_bbox_xyxy(bbox)
        if xyxy:
            x1, y1, _, _ = xyxy
        else:
            x1, y1 = (0.0, 0.0)
        rows.append((y1, x1, text))

    if not rows:
        return ""
    rows.sort(key=lambda item: (item[0], item[1]))
    deduped: list[str] = []
    seen: set[str] = set()
    for _, _, text in rows:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text.strip())
    return "\n".join(deduped).strip()


def _infer_candidate_no(nodes: list[dict]) -> int | None:
    rows: list[tuple[float, float, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        text = _extract_node_text(node)
        if not text:
            continue
        bbox = _extract_bbox(node)
        xyxy = _to_bbox_xyxy(bbox)
        if xyxy:
            x1, y1, _, _ = xyxy
        else:
            x1, y1 = (0.0, 0.0)
        rows.append((y1, x1, text))
    rows.sort(key=lambda item: (item[0], item[1]))
    for _, _, text in rows[:8]:
        match = re.match(r"^\s*(\d{1,2})\s*[\.)\]]\s*", text)
        if match:
            return int(match.group(1))
        match = re.match(r"^\s*문항\s*(\d{1,2})\s*(?:번)?", text)
        if match:
            return int(match.group(1))
        match = re.match(r"^\s*(\d{1,2})\s*번\s+", text)
        if match:
            return int(match.group(1))
    return None


def _resolve_page_width(payload: dict, candidates: list[dict]) -> float:
    page_width_raw = payload.get("page_width")
    try:
        page_width = float(page_width_raw)
        if page_width > 0:
            return page_width
    except Exception:
        pass

    max_x2 = 0.0
    for item in candidates:
        xyxy = _to_bbox_xyxy(item.get("bbox"))
        if not xyxy:
            continue
        max_x2 = max(max_x2, xyxy[2])
    return max(max_x2, 1.0)


def _detect_layout_mode(candidates: list[dict], page_width: float) -> tuple[str, float]:
    centers: list[float] = []
    for item in candidates:
        xyxy = _to_bbox_xyxy(item.get("bbox"))
        if not xyxy:
            continue
        centers.append((xyxy[0] + xyxy[2]) / 2.0)
    if len(centers) < 2:
        return "single_column", page_width / 2.0

    sorted_centers = sorted(centers)
    max_gap = 0.0
    split_index = 0
    for idx in range(len(sorted_centers) - 1):
        gap = sorted_centers[idx + 1] - sorted_centers[idx]
        if gap > max_gap:
            max_gap = gap
            split_index = idx

    if max_gap < page_width * 0.14:
        return "single_column", page_width / 2.0

    split_x = (sorted_centers[split_index] + sorted_centers[split_index + 1]) / 2.0
    left_count = sum(1 for value in sorted_centers if value <= split_x)
    right_count = len(sorted_centers) - left_count
    if left_count < 1 or right_count < 1:
        return "single_column", page_width / 2.0
    return "two_column", split_x


def _candidate_layout_sort_key(candidate: dict, *, layout_mode: str, split_x: float) -> tuple[int, float, float]:
    xyxy = _to_bbox_xyxy(candidate.get("bbox"))
    if not xyxy:
        return (0, 0.0, 0.0)
    x1, y1, x2, _ = xyxy
    if layout_mode == "two_column":
        column_rank = 0 if ((x1 + x2) / 2.0) <= split_x else 1
        return (column_rank, y1, x1)
    return (0, y1, x1)


def _filter_asset_hints_by_candidate_bbox(hints: list[dict], candidate_bbox: dict) -> list[dict]:
    candidate_xyxy = _to_bbox_xyxy(candidate_bbox)
    if not candidate_xyxy:
        return hints

    filtered: list[dict] = []
    for hint in hints:
        hint_bbox = hint.get("bbox")
        hint_xyxy = _to_bbox_xyxy(hint_bbox)
        if not hint_xyxy:
            continue
        overlap = _bbox_intersection_area(candidate_xyxy, hint_xyxy)
        if overlap <= 0:
            continue
        hint_area = _bbox_area(hint_xyxy)
        if hint_area <= 0:
            continue
        if overlap / hint_area >= 0.15:
            filtered.append(hint)
    return filtered


def _to_bbox_xyxy(bbox: Any) -> tuple[float, float, float, float] | None:
    if isinstance(bbox, dict):
        if {"x1", "y1", "x2", "y2"} <= set(bbox):
            try:
                return float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"])
            except Exception:
                return None
        if {"left", "top", "right", "bottom"} <= set(bbox):
            try:
                return float(bbox["left"]), float(bbox["top"]), float(bbox["right"]), float(bbox["bottom"])
            except Exception:
                return None
        if {"x", "y", "w", "h"} <= set(bbox):
            try:
                x = float(bbox["x"])
                y = float(bbox["y"])
                w = float(bbox["w"])
                h = float(bbox["h"])
                return x, y, x + w, y + h
            except Exception:
                return None
        if {"x", "y", "width", "height"} <= set(bbox):
            try:
                x = float(bbox["x"])
                y = float(bbox["y"])
                w = float(bbox["width"])
                h = float(bbox["height"])
                return x, y, x + w, y + h
            except Exception:
                return None
        return None

    if isinstance(bbox, list):
        if len(bbox) == 4 and all(isinstance(item, (int, float)) for item in bbox):
            try:
                return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            except Exception:
                return None
        if len(bbox) >= 3 and all(isinstance(item, list) and len(item) >= 2 for item in bbox):
            try:
                xs = [float(item[0]) for item in bbox]
                ys = [float(item[1]) for item in bbox]
                return min(xs), min(ys), max(xs), max(ys)
            except Exception:
                return None
    return None


def _bbox_dict_from_xyxy(xyxy: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = xyxy
    return {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2)}


def _bbox_area(xyxy: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = xyxy
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _bbox_intersection_area(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    ix1 = max(lx1, rx1)
    iy1 = max(ly1, ry1)
    ix2 = min(lx2, rx2)
    iy2 = min(ly2, ry2)
    return _bbox_area((ix1, iy1, ix2, iy2))


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
