import os


def get_database_url() -> str:
    """Return Postgres DSN for API runtime.

    Default points to local Docker Postgres from this workspace.
    """
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://mathhub:mathhub_dev@localhost:5432/mathhub",
    )
