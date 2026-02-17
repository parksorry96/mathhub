import os


def get_database_url() -> str:
    """Return Postgres DSN for API runtime.

    Default points to local Docker Postgres from this workspace.
    """
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://mathhub:mathhub_dev@localhost:5432/mathhub",
    )


def get_mathpix_app_id() -> str | None:
    return os.getenv("MATHPIX_APP_ID")


def get_mathpix_app_key() -> str | None:
    return os.getenv("MATHPIX_APP_KEY")


def get_mathpix_base_url() -> str:
    return os.getenv("MATHPIX_BASE_URL", "https://api.mathpix.com/v3")


def get_openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY")


def get_openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5-mini")


def get_ai_api_key() -> str | None:
    return os.getenv("AI_API_KEY") or get_openai_api_key()


def get_ai_api_base_url() -> str:
    return os.getenv("AI_API_BASE_URL") or get_openai_base_url()


def get_ai_model() -> str:
    return os.getenv("AI_MODEL") or get_openai_model()
