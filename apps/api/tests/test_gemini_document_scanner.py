from app.services.gemini_document_scanner import (
    _normalize_problem_item,
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
