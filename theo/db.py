import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()


def conninfo() -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ.get("POSTGRES_USER", "theo"),
        password=os.environ.get("POSTGRES_PASSWORD", "theo"),
        dbname=os.environ.get("POSTGRES_DB", "theo"),
    )


@contextmanager
def get_connection():
    with psycopg.connect(conninfo()) as conn:
        register_vector(conn)
        yield conn
