import os
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

load_dotenv()


def conninfo() -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ.get("POSTGRES_USER", "theo"),
        password=os.environ.get("POSTGRES_PASSWORD", "theo"),
        dbname=os.environ.get("POSTGRES_DB", "theo"),
    )


@lru_cache(maxsize=1)
def _pool() -> ConnectionPool:
    """Process-wide connection pool, created on first use. Pooling matters
    here because request handlers open several short-lived connections each
    (one per module-level query helper), and register_vector runs a catalog
    query per new connection -- the pool pays both costs once per physical
    connection instead of once per query."""
    return ConnectionPool(
        conninfo(),
        min_size=1,
        max_size=int(os.environ.get("POSTGRES_POOL_SIZE", "10")),
        configure=register_vector,
        # Ping checked-out connections so a database restart surfaces as a
        # reconnect, not a one-off request failure.
        check=ConnectionPool.check_connection,
        open=True,
    )


@contextmanager
def get_connection():
    """A pooled connection, with the same transaction contract as the
    plain `with psycopg.connect(...)` this used to be: commit on clean
    exit, rollback on error. The only change is the connection goes back
    to the pool instead of being closed."""
    with _pool().connection() as conn:
        yield conn
