from types import SimpleNamespace

import app.services.problem_asset_extractor as extractor_module
from app.services.problem_asset_extractor import _resolve_clip_rect, _select_asset_hints


class _DummyRect:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _DummyPage:
    def __init__(self, width: float, height: float) -> None:
        self.rect = _DummyRect(width, height)


def test_select_asset_hints_prioritizes_larger_graph_bbox():
    hints = [
        {
            "asset_type": "graph",
            "source": "raw_payload_node",
            "bbox": {"x1": 100, "y1": 100, "x2": 140, "y2": 140},
        },
        {
            "asset_type": "graph",
            "source": "raw_payload_node",
            "bbox": {"x1": 80, "y1": 80, "x2": 360, "y2": 340},
        },
        {
            "asset_type": "graph",
            "source": "raw_payload_node",
            "bbox": {"x1": 10, "y1": 10, "x2": 30, "y2": 30},
        },
    ]

    selected = _select_asset_hints(hints)
    graph_hints = [item for item in selected if item.get("asset_type") == "graph"]

    assert len(graph_hints) == 2
    areas = [
        (hint["bbox"]["x2"] - hint["bbox"]["x1"]) * (hint["bbox"]["y2"] - hint["bbox"]["y1"])
        for hint in graph_hints
    ]
    assert areas[0] >= areas[1]
    assert max(areas) > 50000


def test_resolve_clip_rect_uses_wider_padding_for_graph(monkeypatch):
    monkeypatch.setattr(
        extractor_module,
        "pymupdf",
        SimpleNamespace(Rect=lambda x0, y0, x1, y1: (x0, y0, x1, y1)),
    )
    page = _DummyPage(width=1000.0, height=1000.0)
    bbox = {"x1": 100, "y1": 100, "x2": 200, "y2": 200}

    image_rect, _ = _resolve_clip_rect(page=page, bbox=bbox, asset_type="image")
    graph_rect, _ = _resolve_clip_rect(page=page, bbox=bbox, asset_type="graph")

    assert image_rect is not None
    assert graph_rect is not None
    assert graph_rect[0] < image_rect[0]
    assert graph_rect[1] < image_rect[1]
    assert graph_rect[2] > image_rect[2]
    assert graph_rect[3] > image_rect[3]
