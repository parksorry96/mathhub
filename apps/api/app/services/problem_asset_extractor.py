from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from botocore.client import BaseClient

from app.services.s3_storage import build_storage_key, put_object_bytes

try:
    import pymupdf  # type: ignore
except Exception:  # pragma: no cover - runtime fallback for older wheels
    try:
        import fitz as pymupdf  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        pymupdf = None  # type: ignore


@dataclass
class ExtractedAsset:
    asset_type: str
    storage_key: str
    page_no: int
    bbox: dict | None
    metadata: dict


class ProblemAssetExtractor:
    def __init__(
        self,
        *,
        pdf_bytes: bytes,
        s3_client: BaseClient,
        bucket: str,
        job_id: UUID | str,
        prefix: str = "ocr-assets",
    ) -> None:
        self.s3_client = s3_client
        self.bucket = bucket
        self.job_id = str(job_id)
        self.prefix = prefix.strip("/") or "ocr-assets"
        self._available = bool(pymupdf)
        self._doc = None

        if not self._available:
            return
        self._doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    @property
    def is_available(self) -> bool:
        return self._doc is not None and self._available

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def render_clip_png(
        self,
        *,
        page_no: int,
        bbox: dict,
        asset_type: str = "other",
        render_scale: float = 2.0,
    ) -> tuple[bytes | None, dict | None]:
        if not self.is_available or page_no <= 0:
            return None, None
        page_index = page_no - 1
        if page_index >= len(self._doc):
            return None, None

        page = self._doc[page_index]
        clip_rect, normalized_bbox = _resolve_clip_rect(page=page, bbox=bbox, asset_type=asset_type)
        if clip_rect is None:
            return None, None

        matrix = pymupdf.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=matrix, clip=clip_rect, alpha=False)
        body = pix.tobytes("png")
        if not body:
            return None, None
        return body, normalized_bbox

    def extract_and_upload(
        self,
        *,
        page_no: int,
        candidate_no: int,
        external_problem_key: str,
        asset_hints: list[dict],
        candidate_bbox: dict | None = None,
    ) -> list[ExtractedAsset]:
        if not self.is_available or page_no <= 0:
            return []

        page_index = page_no - 1
        if page_index >= len(self._doc):
            return []

        selected_hints = _select_asset_hints(asset_hints)
        if not selected_hints:
            return []

        extracted: list[ExtractedAsset] = []
        for idx, hint in enumerate(selected_hints, start=1):
            asset_type = str(hint.get("asset_type") or "other").strip().lower()
            if asset_type not in {"image", "table", "graph", "other"}:
                asset_type = "other"

            hint_bbox = hint.get("bbox") if isinstance(hint.get("bbox"), dict) else None
            fallback_bbox = candidate_bbox if isinstance(candidate_bbox, dict) else None
            resolved_bbox = hint_bbox if hint_bbox is not None else fallback_bbox
            if not isinstance(resolved_bbox, dict):
                continue
            body, normalized_bbox = self.render_clip_png(
                page_no=page_no,
                bbox=resolved_bbox,
                asset_type=asset_type,
                render_scale=2.0,
            )
            if not body:
                continue

            object_key = (
                f"{self.prefix}/{self.job_id}/page-{page_no:04d}/"
                f"candidate-{candidate_no:03d}/{idx:02d}-{asset_type}.png"
            )
            put_object_bytes(
                client=self.s3_client,
                bucket=self.bucket,
                key=object_key,
                body=body,
                content_type="image/png",
            )
            storage_key = build_storage_key(self.bucket, object_key)
            extracted.append(
                ExtractedAsset(
                    asset_type=asset_type,
                    storage_key=storage_key,
                    page_no=page_no,
                    bbox=normalized_bbox,
                    metadata={
                        "source_hint": hint.get("source"),
                        "evidence": hint.get("evidence"),
                        "bbox_source": "hint" if hint_bbox is not None else "candidate_fallback",
                        "external_problem_key": external_problem_key,
                        "render_scale": 2.0,
                    },
                )
            )
        return extracted


def _select_asset_hints(asset_hints: list[dict]) -> list[dict]:
    if not asset_hints:
        return []

    normalized_hints: list[dict] = []
    for hint in asset_hints:
        if not isinstance(hint, dict):
            continue
        asset_type = str(hint.get("asset_type") or "other").strip().lower()
        if asset_type not in {"image", "table", "graph", "other"}:
            asset_type = "other"
        normalized_hints.append({**hint, "asset_type": asset_type})

    if not normalized_hints:
        return []

    ranked_hints = sorted(normalized_hints, key=_hint_rank_key, reverse=True)
    selected: list[dict] = []
    per_type_count: defaultdict[str, int] = defaultdict(int)
    for hint in ranked_hints:
        asset_type = str(hint.get("asset_type") or "other").strip().lower()
        if per_type_count[asset_type] >= 2:
            continue
        selected.append(hint)
        per_type_count[asset_type] += 1
        if len(selected) >= 6:
            break
    return selected


def _hint_rank_key(hint: dict) -> tuple[int, int, float]:
    source = str(hint.get("source") or "").strip().lower()
    source_priority = {
        "raw_payload_node": 4,
        "statement_text_bbox_fallback": 3,
        "statement_text": 2,
        "raw_payload_text": 1,
    }.get(source, 0)

    bbox = hint.get("bbox")
    xyxy = _to_xyxy(bbox) if isinstance(bbox, dict) else None
    if not xyxy:
        return (0, source_priority, 0.0)

    x0, y0, x1, y1 = xyxy
    area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return (1, source_priority, area)


def _resolve_clip_rect(
    *,
    page,
    bbox: dict | None,
    asset_type: str = "other",
) -> tuple[object | None, dict | None]:
    if not isinstance(bbox, dict):
        return None, None

    points = _to_xyxy(bbox)
    if not points:
        return None, None
    x0, y0, x1, y1 = points
    if x1 <= x0 or y1 <= y0:
        return None, None

    page_rect = page.rect
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)

    # Normalized [0, 1] coordinates
    if 0 <= x0 <= 1 and 0 <= y0 <= 1 and 0 <= x1 <= 1 and 0 <= y1 <= 1:
        x0, x1 = x0 * page_w, x1 * page_w
        y0, y1 = y0 * page_h, y1 * page_h
    else:
        source_dimensions = _resolve_source_dimensions(bbox)
        if source_dimensions:
            source_w, source_h = source_dimensions
            scale_x = page_w / source_w
            scale_y = page_h / source_h
            x0 *= scale_x
            x1 *= scale_x
            y0 *= scale_y
            y1 *= scale_y
        # Scale down pixel-like coordinates if they are much larger than page points.
        elif x1 > page_w * 1.8 or y1 > page_h * 1.8:
            scale_x = page_w / max(x1, page_w)
            scale_y = page_h / max(y1, page_h)
            x0 *= scale_x
            x1 *= scale_x
            y0 *= scale_y
            y1 *= scale_y

    pad_ratio, min_pad, min_crop_w, min_crop_h = _resolve_crop_profile(asset_type)
    pad_x = max(min_pad, (x1 - x0) * pad_ratio)
    pad_y = max(min_pad, (y1 - y0) * pad_ratio)
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(page_w, x1 + pad_x)
    y1 = min(page_h, y1 + pad_y)
    x0, y0, x1, y1 = _enforce_min_crop_size(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        page_w=page_w,
        page_h=page_h,
        min_width=min_crop_w,
        min_height=min_crop_h,
    )
    if x1 <= x0 or y1 <= y0:
        return None, None

    rect = pymupdf.Rect(x0, y0, x1, y1)
    normalized_bbox = {
        "x0_ratio": round(x0 / page_w, 6),
        "y0_ratio": round(y0 / page_h, 6),
        "x1_ratio": round(x1 / page_w, 6),
        "y1_ratio": round(y1 / page_h, 6),
    }
    return rect, normalized_bbox


def _to_xyxy(bbox: dict) -> tuple[float, float, float, float] | None:
    if {"x0_ratio", "y0_ratio", "x1_ratio", "y1_ratio"} <= set(bbox):
        try:
            return (
                float(bbox["x0_ratio"]),
                float(bbox["y0_ratio"]),
                float(bbox["x1_ratio"]),
                float(bbox["y1_ratio"]),
            )
        except Exception:
            return None
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


def _resolve_source_dimensions(bbox: dict) -> tuple[float, float] | None:
    source_w = _to_positive_float(
        bbox.get("source_page_width") or bbox.get("page_width") or bbox.get("source_width")
    )
    source_h = _to_positive_float(
        bbox.get("source_page_height") or bbox.get("page_height") or bbox.get("source_height")
    )
    if source_w and source_h:
        return source_w, source_h
    return None


def _resolve_crop_profile(asset_type: str) -> tuple[float, float, float, float]:
    normalized = asset_type.strip().lower()
    if normalized == "graph":
        return (0.18, 14.0, 120.0, 120.0)
    if normalized == "table":
        return (0.1, 10.0, 72.0, 72.0)
    if normalized == "image":
        return (0.08, 8.0, 64.0, 64.0)
    return (0.06, 6.0, 56.0, 56.0)


def _enforce_min_crop_size(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_w: float,
    page_h: float,
    min_width: float,
    min_height: float,
) -> tuple[float, float, float, float]:
    width = x1 - x0
    height = y1 - y0

    if width < min_width:
        grow = (min_width - width) / 2.0
        x0 = max(0.0, x0 - grow)
        x1 = min(page_w, x1 + grow)
        width = x1 - x0
        if width < min_width:
            if x0 <= 0.0:
                x1 = min(page_w, x0 + min_width)
            elif x1 >= page_w:
                x0 = max(0.0, x1 - min_width)

    if height < min_height:
        grow = (min_height - height) / 2.0
        y0 = max(0.0, y0 - grow)
        y1 = min(page_h, y1 + grow)
        height = y1 - y0
        if height < min_height:
            if y0 <= 0.0:
                y1 = min(page_h, y0 + min_height)
            elif y1 >= page_h:
                y0 = max(0.0, y1 - min_height)

    return x0, y0, x1, y1


def _to_positive_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if parsed > 0:
        return parsed
    return None
