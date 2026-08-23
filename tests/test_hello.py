from fastapi.testclient import TestClient

from services.hello.main import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_hello() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "sentinel-hello"
