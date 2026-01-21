from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_whoami_unauthorized():
    response = client.get("/whoami")
    # HTTPBearer returns 401 when no credentials provided
    assert response.status_code == 401
