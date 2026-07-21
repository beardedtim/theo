"""Shared fixtures for the API test suite. These are integration tests --
they run the real FastAPI app in-process (via TestClient) against whatever
data is currently ingested into the dev database, rather than mocking
theo.db.get_connection(). Run `task db:up` and the ingest_*.py scripts
first (see README.md's Data pipeline section) before running the suite.
"""

import pytest
from fastapi.testclient import TestClient

from theo.server import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client
