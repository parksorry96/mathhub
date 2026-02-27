import httpx

from app.services import mathpix_client


def test_ocr_mathpix_image_retries_on_503_then_succeeds(monkeypatch):
    calls: list[str] = []

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def post(self, url: str, headers: dict, files: dict):
            del headers, files
            calls.append(url)
            if len(calls) == 1:
                return _response_for(url=url, status_code=503, payload={"error": "temporary unavailable"})
            return _response_for(
                url=url,
                status_code=200,
                payload={"text": "OCR OK", "latex_styled": r"x^2 + 1 = 0"},
            )

    monkeypatch.setattr(mathpix_client.httpx, "Client", _FakeClient)
    monkeypatch.setattr(mathpix_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(mathpix_client.random, "uniform", lambda _a, _b: 0.0)

    result = mathpix_client.ocr_mathpix_image(
        image_bytes=b"test",
        app_id="id",
        app_key="key",
        base_url="https://api.mathpix.com/v3",
    )

    assert result["text"] == "OCR OK"
    assert len(calls) == 2


def _response_for(*, url: str, status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(status_code=status_code, json=payload, request=request)
