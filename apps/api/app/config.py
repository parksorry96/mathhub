import os
from pathlib import Path

from dotenv import load_dotenv


_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_PATH, override=False)


def _get_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def get_database_url() -> str:
    """Return Postgres DSN for API runtime.

    Default points to local Docker Postgres from this workspace.
    """
    return _get_env("DATABASE_URL") or "postgresql+psycopg://mathhub:mathhub_dev@localhost:5432/mathhub"


def get_mathpix_app_id() -> str | None:
    return _get_env("MATHPIX_APP_ID")


def get_mathpix_app_key() -> str | None:
    return _get_env("MATHPIX_APP_KEY")


def get_mathpix_base_url() -> str:
    return _get_env("MATHPIX_BASE_URL") or "https://api.mathpix.com/v3"


def get_openai_api_key() -> str | None:
    return _get_env("OPENAI_API_KEY")


def get_openai_base_url() -> str:
    return _get_env("OPENAI_BASE_URL") or "https://api.openai.com/v1"


def get_openai_model() -> str:
    return _get_env("OPENAI_MODEL") or "gpt-5-mini"


def get_ai_api_key() -> str | None:
    return _get_env("AI_API_KEY") or get_openai_api_key()


def get_ai_api_base_url() -> str:
    return _get_env("AI_API_BASE_URL") or get_openai_base_url()


def get_ai_model() -> str:
    return _get_env("AI_MODEL") or get_openai_model()


def get_s3_bucket() -> str | None:
    return _get_env("S3_BUCKET")


def get_s3_region() -> str:
    return _get_env("S3_REGION") or "ap-northeast-2"


def get_s3_access_key_id() -> str | None:
    return _get_env("S3_ACCESS_KEY_ID")


def get_s3_secret_access_key() -> str | None:
    return _get_env("S3_SECRET_ACCESS_KEY")


def get_s3_session_token() -> str | None:
    return _get_env("S3_SESSION_TOKEN")


def get_s3_endpoint_url() -> str | None:
    return _get_env("S3_ENDPOINT_URL")
