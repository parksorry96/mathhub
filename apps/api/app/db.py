from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection, connect
from psycopg.rows import dict_row

from app.config import get_database_url


def _to_psycopg_dsn(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


@contextmanager
def get_db_connection() -> Iterator[Connection]:
    """Yield a psycopg connection with dict-row mapping."""
    conn = connect(_to_psycopg_dsn(get_database_url()), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()
