"""Shared pytest fixture: a test client on a freshly reset ticket store."""

import pytest
from fastapi.testclient import TestClient

from ticket_api.main import app, store


@pytest.fixture
def client():
    # Every test starts from the same 3 seed tickets (ids 1-3; id 3 is RESOLVED).
    store.reset()
    with TestClient(app) as test_client:
        yield test_client
