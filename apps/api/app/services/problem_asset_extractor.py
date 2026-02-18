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

    def extract_and_upload(
        self,
        *,
        page_no: int,
        candidate_no: int,
        external_problem_key: str,
        asset_hints: list[dict],
    ) -> list[ExtractedAsset]:
        if not self.is_available or page_no <= 0:
            return []

        page_index = page_no - 1
        if page_index >= len(self._doc):
            return []

        page = self._doc[page_index]
        selected_hints = _select_asset_hints(asset_hints)
        if not selected_hints:
            return []

        extracted: list[ExtractedAsset] = []
        for idx, hint in enumerate(selected_hints, start=1):
            asset_type = str(hint.get("asset_type") or "other").strip().lower()
            if asset_type not in {"image", "table", "graph", "other"}:
                asset_type = "other"

            clip_rect, normalized_bbox = _resolve_clip_rect(page=page, bbox=hint.get("bbox"))
            matrix = pymupdf.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=matrix, clip=clip_rect, alpha=False)
            body = pix.tobytes("png")
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
                        "external_problem_key": external_problem_key,
                        "render_scale": 2.0,
                    },
                )
            )
        return extracted


def _select_asset_hints(asset_hints: list[dict]) -> list[dict]:
    if not asset_hints:
        return []

    selected: list[dict] = []
    per_type_count: defaultdict[str, int] = defaultdict(int)
    for hint in asset_hints:
        if not isinstance(hint, dict):
            continue
        asset_type = str(hint.get("asset_type") or "other").strip().lower()
        if asset_type not in {"image", "table", "graph", "other"}:
            asset_type = "other"
        if per_type_count[asset_type] >= 2:
            continue
        selected.append({**hint, "asset_type": asset_type})
        per_type_count[asset_type] += 1
        if len(selected) >= 6:
            break
    return selected


def _resolve_clip_rect(*, page, bbox: dict | None) -> tuple[object | None, dict | None]:
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
        # Scale down pixel-like coordinates if they are much larger than page points.
        if x1 > page_w * 1.8 or y1 > page_h * 1.8:
            scale_x = page_w / max(x1, page_w)
            scale_y = page_h / max(y1, page_h)
            x0 *= scale_x
            x1 *= scale_x
            y0 *= scale_y
            y1 *= scale_y

    pad_x = max(6.0, (x1 - x0) * 0.06)
    pad_y = max(6.0, (y1 - y0) * 0.06)
    x0 = max(0.0, x0 - pad_x)
    y0 = max(0.0, y0 - pad_y)
    x1 = min(page_w, x1 + pad_x)
    y1 = min(page_h, y1 + pad_y)
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
