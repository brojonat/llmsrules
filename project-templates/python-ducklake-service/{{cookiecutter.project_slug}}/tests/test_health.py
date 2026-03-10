"""Health check endpoint tests."""

import os

import pytest


def test_health_endpoint():
    """Test that /health returns 200 with healthy status.

    Note: This test requires running services (Postgres, MinIO).
    Skip in CI without services by setting SKIP_INTEGRATION=1.
    """
    if os.environ.get("SKIP_INTEGRATION"):
        pytest.skip("SKIP_INTEGRATION set")

    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
