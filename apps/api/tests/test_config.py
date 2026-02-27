from app import config


def test_get_gemini_preprocess_model_falls_back_to_gemini_model(monkeypatch):
    monkeypatch.delenv("GEMINI_PREPROCESS_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro-latest")

    assert config.get_gemini_preprocess_model() == "gemini-2.5-pro-latest"
