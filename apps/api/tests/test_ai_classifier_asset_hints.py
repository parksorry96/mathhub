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
