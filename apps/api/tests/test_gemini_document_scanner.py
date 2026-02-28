import httpx

from app.services import gemini_document_scanner as scanner
from app.services.gemini_document_scanner import (
    _build_generation_config,
    _create_gemini_http_client,
    _normalize_problem_item,
    _scan_page_with_gemini,
    attach_answer_keys_to_scanned_pages,
)


def test_attach_answer_keys_to_scanned_pages_matches_question_number():
    pages = [
        {
            "page_no": 1,
            "problems": [
                {
                    "candidate_no": 1,
                    "question_no": 12,
                    "statement_text": "12번 문제를 풀이하시오.",
                    "bbox": {"x0_ratio": 0.1, "y0_ratio": 0.2, "x1_ratio": 0.5, "y1_ratio": 0.6},
                }
            ],
            "answer_candidates": [],
        },
        {
            "page_no": 20,
            "problems": [],
            "answer_candidates": [
                {"question_no": 12, "answer_key": "4"},
            ],
        },
    ]

    matched = attach_answer_keys_to_scanned_pages(pages)

    assert matched == 1
    first_problem = pages[0]["problems"][0]
    assert first_problem["answer_key"] == "4"
    assert first_problem["answer_source"] == "answer_page"


def test_normalize_problem_item_clamps_bbox_and_subject_code():
    normalized = _normalize_problem_item(
        {
            "candidate_no": "3",
            "question_no": "7",
            "statement_text": "좌표평면 위 그래프를 보고 답하시오.",
            "subject_code": "calculus",
            "bbox": {"x0_ratio": -0.2, "y0_ratio": 0.1, "x1_ratio": 1.5, "y1_ratio": 0.8},
            "confidence": "120",
        },
        fallback_index=1,
        model="gemini-test",
    )

    assert normalized is not None
    assert normalized["candidate_no"] == 3
    assert normalized["question_no"] == 7
    assert normalized["subject_code"] == "CALCULUS"
    assert normalized["confidence"] == 100.0
    assert normalized["bbox"]["x0_ratio"] == 0.0
    assert normalized["bbox"]["x1_ratio"] == 1.0


def test_normalize_problem_item_keeps_visual_asset_types():
    normalized = _normalize_problem_item(
        {
            "candidate_no": 2,
            "statement_text": "그래프와 표를 보고 답하시오.",
            "bbox": {"x0_ratio": 0.2, "y0_ratio": 0.2, "x1_ratio": 0.8, "y1_ratio": 0.9},
            "has_visual_asset": True,
            "visual_asset_types": ["graph", "table", "unknown", "graph"],
        },
        fallback_index=1,
        model="gemini-test",
    )

    assert normalized is not None
    assert normalized["has_visual_asset"] is True
    assert normalized["visual_asset_types"] == ["graph", "table", "other"]


def test_normalize_problem_item_keeps_visual_asset_bboxes():
    normalized = _normalize_problem_item(
        {
            "candidate_no": 2,
            "statement_text": "그래프를 보고 답하시오.",
            "bbox": {"x0_ratio": 0.1, "y0_ratio": 0.2, "x1_ratio": 0.9, "y1_ratio": 0.8},
            "visual_assets": [
                {
                    "asset_type": "graph",
                    "bbox": {"x0_ratio": 0.45, "y0_ratio": 0.4, "x1_ratio": 0.78, "y1_ratio": 0.75},
                }
            ],
        },
        fallback_index=1,
        model="gemini-test",
    )

    assert normalized is not None
    assert normalized["visual_assets"] == [
        {
            "asset_type": "graph",
            "bbox": {"x0_ratio": 0.45, "y0_ratio": 0.4, "x1_ratio": 0.78, "y1_ratio": 0.75},
        }
    ]
    assert normalized["visual_asset_types"] == ["graph"]


def test_scan_page_with_gemini_retries_on_503_then_succeeds(monkeypatch):
    calls: list[str] = []

    def responder(*, url: str, headers: dict, json_payload: dict) -> httpx.Response:
        del headers, json_payload
        calls.append(url)
        if len(calls) == 1:
            return _response_for(url=url, status_code=503, payload={"error": {"message": "unavailable"}})
        return _response_for(
            url=url,
            status_code=200,
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"page_type":"problem","page_summary":"ok",'
                                        '"problems":[],"answer_candidates":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(scanner.httpx, "Client", _client_factory(responder))
    monkeypatch.setattr(scanner.time, "sleep", lambda _: None)
    monkeypatch.setattr(scanner.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(scanner, "_MAX_GEMINI_RETRIES_PER_MODEL", 3)

    payload, used_model = _scan_page_with_gemini(
        image_bytes=b"test-image",
        page_no=1,
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-pro",
        temperature=0.1,
    )

    assert used_model == "gemini-2.5-pro"
    assert payload["page_type"] == "problem"
    assert len(calls) == 2


def test_scan_page_with_gemini_falls_back_to_flash_after_transient_failures(monkeypatch):
    calls: list[str] = []

    def responder(*, url: str, headers: dict, json_payload: dict) -> httpx.Response:
        del headers, json_payload
        calls.append(url)
        if "gemini-2.5-pro" in url:
            return _response_for(url=url, status_code=503, payload={"error": {"message": "overloaded"}})
        return _response_for(
            url=url,
            status_code=200,
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"page_type":"mixed","page_summary":"fallback-ok",'
                                        '"problems":[],"answer_candidates":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(scanner.httpx, "Client", _client_factory(responder))
    monkeypatch.setattr(scanner.time, "sleep", lambda _: None)
    monkeypatch.setattr(scanner.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(scanner, "_MAX_GEMINI_RETRIES_PER_MODEL", 1)

    payload, used_model = _scan_page_with_gemini(
        image_bytes=b"test-image",
        page_no=2,
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-pro",
        temperature=0.1,
    )

    assert payload["page_summary"] == "fallback-ok"
    assert used_model == "gemini-2.5-flash"
    assert any("gemini-2.5-pro" in item for item in calls)
    assert any("gemini-2.5-flash" in item for item in calls)


def test_build_generation_config_applies_speed_defaults_for_flash():
    config = _build_generation_config(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=999999,
        thinking_budget=0,
    )

    assert config["candidateCount"] == 1
    assert config["maxOutputTokens"] == 8192
    assert config["thinkingConfig"]["thinkingBudget"] == 0


def test_build_generation_config_skips_thinking_budget_for_pro():
    config = _build_generation_config(
        model="gemini-2.5-pro",
        temperature=0.1,
        max_output_tokens=10,
        thinking_budget=0,
    )

    assert config["maxOutputTokens"] == 256
    assert "thinkingConfig" not in config


def test_create_gemini_http_client_falls_back_when_h2_missing(monkeypatch):
    captured: dict = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        class _DummyClient:
            pass
        return _DummyClient()

    monkeypatch.setattr(scanner.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(scanner.httpx, "Client", fake_client)

    _create_gemini_http_client()

    assert captured["http2"] is False


def _client_factory(responder):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url: str, headers: dict, json: dict):
            return responder(url=url, headers=headers, json_payload=json)

    return _FakeClient


def _response_for(*, url: str, status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(status_code=status_code, request=request, json=payload)
