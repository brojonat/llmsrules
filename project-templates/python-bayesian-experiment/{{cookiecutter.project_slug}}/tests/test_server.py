"""Tests for the FastAPI server."""

from fastapi.testclient import TestClient

from {{cookiecutter.package_name}}.server.main import app

client = TestClient(app)


def test_healthz():
    """Test health check endpoint."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_experiments_empty():
    """Test listing experiments when none exist."""
    response = client.get("/experiments")
    assert response.status_code == 200
    assert response.json() == []


def test_create_experiment():
    """Test creating an experiment."""
    response = client.post(
        "/experiments",
        json={"name": "test-exp", "type": "bernoulli", "description": "Test experiment"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test-exp"
    assert data["type"] == "bernoulli"

    # Cleanup
    client.delete("/experiments/test-exp")


def test_create_duplicate_experiment():
    """Test that creating a duplicate experiment fails."""
    # Create first
    client.post(
        "/experiments",
        json={"name": "dup-exp", "type": "bernoulli"},
    )

    # Try to create duplicate
    response = client.post(
        "/experiments",
        json={"name": "dup-exp", "type": "bernoulli"},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]

    # Cleanup
    client.delete("/experiments/dup-exp")


def test_get_nonexistent_experiment():
    """Test getting a nonexistent experiment."""
    response = client.get("/experiments/nonexistent")
    assert response.status_code == 404
