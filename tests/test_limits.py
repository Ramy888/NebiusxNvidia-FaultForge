import pytest
from fastapi.testclient import TestClient

from faultforge.api import create_app
from faultforge.limits import RateLimiter


def test_rate_limiter_allows_up_to_the_limit_per_client_then_says_when_to_retry():
    clock = [1000.0]
    limiter = RateLimiter(max_requests=2, window_s=60, clock=lambda: clock[0])

    assert limiter.check("a") == 0
    assert limiter.check("a") == 0
    retry_after = limiter.check("a")
    assert 0 < retry_after <= 60
    assert limiter.check("b") == 0


def test_rate_limiter_forgets_requests_outside_the_window():
    clock = [1000.0]
    limiter = RateLimiter(max_requests=1, window_s=60, clock=lambda: clock[0])
    limiter.check("a")

    clock[0] += 61

    assert limiter.check("a") == 0


def test_api_answers_429_with_retry_after_when_a_client_starts_too_many_runs():
    app = create_app(mode="demo", runs_per_window=1)
    with TestClient(app) as client:
        assert client.post("/api/runs", json={"example": "order-service"}).status_code == 202
        limited = client.post("/api/runs", json={"example": "order-service"})

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_api_refuses_new_runs_when_too_many_are_active():
    app = create_app(mode="demo", max_active_runs=0)
    with TestClient(app) as client:
        response = client.post("/api/runs", json={"example": "order-service"})

    assert response.status_code == 503


def test_only_the_most_recent_runs_are_kept():
    app = create_app(mode="demo", keep_runs=2, runs_per_window=100)
    with TestClient(app) as client:
        ids = [
            client.post("/api/runs", json={"example": "order-service"}).json()["id"]
            for _ in range(3)
        ]
        assert client.get(f"/api/runs/{ids[0]}").status_code == 404
        assert client.get(f"/api/runs/{ids[2]}").status_code == 200


def test_live_mode_refuses_to_run_model_written_code_in_the_local_sandbox(monkeypatch):
    monkeypatch.setenv("FAULTFORGE_SANDBOX", "local")
    monkeypatch.delenv("FAULTFORGE_ALLOW_LOCAL_LIVE", raising=False)

    with pytest.raises(RuntimeError, match="isolated sandbox"):
        create_app(mode="live")
