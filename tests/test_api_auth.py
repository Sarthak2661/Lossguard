from __future__ import annotations

from fastapi.testclient import TestClient

from apps.scoring_api.main import app, service
from lossguard.config import get_settings

client = TestClient(app)


def test_root_describes_browser_entrypoints() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["documentation"] == "/docs"
    assert response.json()["health"] == "/health"


def test_health_remains_available_for_container_checks() -> None:
    assert client.get("/health").status_code == 200


def test_score_requires_scoring_api_key() -> None:
    assert client.post("/score", json={}).status_code == 401
    assert client.post("/score", json={}, headers={"X-API-Key": "wrong"}).status_code == 401

    response = client.post(
        "/score",
        json={},
        headers={"X-API-Key": get_settings().scoring_api_key},
    )

    assert response.status_code == 422


def test_reload_requires_distinct_admin_key(monkeypatch) -> None:
    assert client.post("/reload").status_code == 401
    assert (
        client.post(
            "/reload",
            headers={"X-Admin-Key": get_settings().scoring_api_key},
        ).status_code
        == 401
    )
    reload_calls = 0

    def fake_reload(raise_on_error: bool = False) -> bool:
        nonlocal reload_calls
        reload_calls += 1
        return True

    monkeypatch.setattr(service, "reload", fake_reload)
    response = client.post(
        "/reload",
        headers={"X-Admin-Key": get_settings().admin_api_key},
    )

    assert response.status_code == 200
    assert reload_calls == 1
