from app.services.ai_classifier import collect_problem_asset_hints


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
    assert any(item.get("bbox") == candidate_bbox for item in graph_hints)


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
