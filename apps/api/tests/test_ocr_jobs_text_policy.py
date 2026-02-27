from app.routers.ocr_jobs import _build_ai_preprocess_extracted_text, _resolve_problem_text_from_mathpix


def test_ai_preprocess_does_not_persist_ai_statement_text():
    problem_items = [
        {"candidate_no": 1, "statement_text": "AI가 읽은 문장"},
        {"candidate_no": 2, "statement_text": "두 번째 문장"},
    ]

    result = _build_ai_preprocess_extracted_text(problem_items=problem_items)

    assert result is None


def test_problem_text_uses_mathpix_text_only():
    result = _resolve_problem_text_from_mathpix(
        extracted_text="  Mathpix OCR text  ",
        extracted_latex=r"\frac{1}{2}",
    )

    assert result == "Mathpix OCR text"


def test_problem_text_falls_back_to_mathpix_latex_when_text_empty():
    result = _resolve_problem_text_from_mathpix(
        extracted_text="",
        extracted_latex=r"  x^2 + 1 = 0  ",
    )

    assert result == r"x^2 + 1 = 0"


def test_problem_text_is_none_when_mathpix_outputs_are_empty():
    result = _resolve_problem_text_from_mathpix(
        extracted_text="   ",
        extracted_latex="   ",
    )

    assert result is None
