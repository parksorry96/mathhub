from app.services.ai_classifier import collect_problem_asset_hints, extract_problem_candidates


def test_extract_problem_candidates_reads_ai_preprocess_payload():
    payload = {
        "ai_preprocess": {
            "problems": [
                {
                    "candidate_no": 4,
                    "statement_text": "4번 문항 본문",
                    "bbox": {"x0_ratio": 0.1, "y0_ratio": 0.2, "x1_ratio": 0.6, "y1_ratio": 0.7},
                },
                {
                    "candidate_no": 5,
                    "statement_text": "5번 문항 본문",
                },
            ]
        }
    }

    candidates = extract_problem_candidates("", payload)

    assert len(candidates) == 2
    assert [item["candidate_no"] for item in candidates] == [4, 5]
    assert all(item["split_strategy"] == "ai_preprocess" for item in candidates)
    assert candidates[0]["bbox"]["x0_ratio"] == 0.1


def test_extract_problem_candidates_dedupes_ai_preprocess_candidate_numbers():
    payload = {
        "ai_preprocess": {
            "problems": [
                {"candidate_no": 1, "statement_text": "첫 번째"},
                {"candidate_no": 1, "statement_text": "중복 번호"},
                {"statement_text": "번호 없음"},
                {"candidate_no": -3, "statement_text": "음수 번호"},
                {"candidate_no": 3, "statement_text": "세 번째"},
            ]
        }
    }

    candidates = extract_problem_candidates("", payload)

    assert [item["candidate_no"] for item in candidates] == [1, 2, 3, 4, 5]


def test_collect_problem_asset_hints_uses_ai_candidate_visual_types():
    candidate_bbox = {"x1": 200, "y1": 240, "x2": 680, "y2": 820}

    hints = collect_problem_asset_hints(
        "문항을 풀이하시오.",
        {},
        candidate_bbox=candidate_bbox,
        candidate_meta={"has_visual_asset": True, "visual_asset_types": ["graph", "table"]},
    )

    ai_type_hints = [item for item in hints if item.get("source") == "ai_candidate_type"]
    assert len(ai_type_hints) == 2
    assert {item.get("asset_type") for item in ai_type_hints} == {"graph", "table"}
    assert all(item.get("bbox") == candidate_bbox for item in ai_type_hints)


def test_collect_problem_asset_hints_uses_ai_candidate_visual_asset_bboxes():
    candidate_bbox = {"x1": 120, "y1": 180, "x2": 760, "y2": 940}
    graph_bbox = {"x0_ratio": 0.42, "y0_ratio": 0.38, "x1_ratio": 0.81, "y1_ratio": 0.82}

    hints = collect_problem_asset_hints(
        "문항을 풀이하시오.",
        {},
        candidate_bbox=candidate_bbox,
        candidate_meta={
            "has_visual_asset": True,
            "visual_assets": [{"asset_type": "graph", "bbox": graph_bbox}],
        },
    )

    ai_bbox_hints = [item for item in hints if item.get("source") == "ai_candidate_visual_asset"]
    assert ai_bbox_hints
    assert ai_bbox_hints[0]["asset_type"] == "graph"
    assert ai_bbox_hints[0]["bbox"] == graph_bbox


def test_collect_problem_asset_hints_prefers_payload_bbox_over_statement_hint():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
        "lines": [
            {
                "id": "chart-in-candidate",
                "type": "chart",
                "subtype": "line",
                "cnt": [[610, 620], [710, 620], [710, 730], [610, 730]],
            },
            {
                "id": "chart-outside-candidate",
                "type": "chart",
                "subtype": "line",
                "cnt": [[120, 120], [220, 120], [220, 210], [120, 210]],
            },
        ],
    }
    candidate_bbox = {"x1": 560, "y1": 560, "x2": 760, "y2": 780}

    hints = collect_problem_asset_hints(
        "다음 그래프를 보고 함수 값을 구하시오.",
        payload,
        candidate_bbox=candidate_bbox,
    )

    graph_hints = [item for item in hints if item.get("asset_type") == "graph"]
    assert graph_hints
    assert all(isinstance(item.get("bbox"), dict) for item in graph_hints)
    assert all(item.get("source") != "statement_text" for item in graph_hints)
    assert all(float(item["bbox"]["x1"]) >= 500 for item in graph_hints if isinstance(item.get("bbox"), dict))


def test_collect_problem_asset_hints_uses_candidate_bbox_when_only_text_hint_exists():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
        "lines": [
            {
                "id": "plain-text-line",
                "type": "text",
                "text": "4. lim 값을 구하시오.",
                "cnt": [[120, 120], [520, 120], [520, 160], [120, 160]],
            }
        ],
    }
    candidate_bbox = {"x1": 500, "y1": 580, "x2": 760, "y2": 800}

    hints = collect_problem_asset_hints(
        "그래프를 참고하여 극한값을 구하시오.",
        payload,
        candidate_bbox=candidate_bbox,
    )

    graph_hints = [item for item in hints if item.get("asset_type") == "graph"]
    assert graph_hints
    assert any(
        isinstance(item.get("bbox"), dict)
        and float(item["bbox"]["x1"]) == 500.0
        and float(item["bbox"]["y1"]) == 580.0
        and float(item["bbox"]["x2"]) == 760.0
        and float(item["bbox"]["y2"]) == 800.0
        for item in graph_hints
    )


def test_collect_problem_asset_hints_skips_raw_payload_text_when_bbox_hints_exist():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
        "lines": [
            {
                "id": "graph-node",
                "type": "chart",
                "subtype": "scatter",
                "cnt": [[500, 500], [700, 500], [700, 700], [500, 700]],
            }
        ],
    }

    hints = collect_problem_asset_hints(
        "문항을 풀이하시오.",
        payload,
        candidate_bbox=None,
    )

    assert any(item.get("source") == "raw_payload_node" for item in hints)
    assert all(item.get("source") != "raw_payload_text" for item in hints)


def test_collect_problem_asset_hints_keeps_large_graph_covering_candidate_bbox():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
        "lines": [
            {
                "id": "large-graph",
                "type": "chart",
                "subtype": "line",
                "cnt": [[380, 380], [920, 380], [920, 930], [380, 930]],
            }
        ],
    }
    candidate_bbox = {"x1": 520, "y1": 520, "x2": 690, "y2": 760}

    hints = collect_problem_asset_hints(
        "문항을 풀이하시오.",
        payload,
        candidate_bbox=candidate_bbox,
    )

    graph_hints = [
        item
        for item in hints
        if item.get("asset_type") == "graph" and item.get("source") == "raw_payload_node"
    ]
    assert graph_hints
    assert any(isinstance(item.get("bbox"), dict) for item in graph_hints)


def test_collect_problem_asset_hints_filters_payload_graphs_with_ratio_candidate_bbox():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
        "lines": [
            {
                "id": "chart-in-candidate",
                "type": "chart",
                "subtype": "line",
                "cnt": [[560, 560], [760, 560], [760, 760], [560, 760]],
            },
            {
                "id": "chart-outside-candidate",
                "type": "chart",
                "subtype": "line",
                "cnt": [[120, 120], [260, 120], [260, 260], [120, 260]],
            },
        ],
    }
    ratio_candidate_bbox = {"x0_ratio": 0.5, "y0_ratio": 0.5, "x1_ratio": 0.82, "y1_ratio": 0.82}

    hints = collect_problem_asset_hints(
        "다음 그래프를 이용하여 값을 구하시오.",
        payload,
        candidate_bbox=ratio_candidate_bbox,
    )

    graph_hints = [item for item in hints if item.get("asset_type") == "graph"]
    assert graph_hints
    assert all(float(item["bbox"]["x1"]) >= 500 for item in graph_hints if isinstance(item.get("bbox"), dict))
    assert all(float(item["bbox"]["x2"]) <= 850 for item in graph_hints if isinstance(item.get("bbox"), dict))


def test_collect_problem_asset_hints_normalizes_ai_visual_asset_ratio_bbox():
    payload = {
        "page_width": 1000,
        "page_height": 1000,
    }

    hints = collect_problem_asset_hints(
        "문항을 풀이하시오.",
        payload,
        candidate_bbox={"x0_ratio": 0.2, "y0_ratio": 0.2, "x1_ratio": 0.9, "y1_ratio": 0.9},
        candidate_meta={
            "visual_assets": [
                {
                    "asset_type": "graph",
                    "bbox": {"x0_ratio": 0.55, "y0_ratio": 0.42, "x1_ratio": 0.78, "y1_ratio": 0.76},
                }
            ]
        },
    )

    ai_bbox_hints = [item for item in hints if item.get("source") == "ai_candidate_visual_asset"]
    assert ai_bbox_hints
    graph_bbox = ai_bbox_hints[0]["bbox"]
    assert graph_bbox["x1"] == 550.0
    assert graph_bbox["y1"] == 420.0
    assert graph_bbox["x2"] == 780.0
    assert graph_bbox["y2"] == 760.0
