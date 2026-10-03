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


def test_behind_a_trusted_proxy_the_client_is_the_entry_the_proxy_appended():
    from types import SimpleNamespace

    from faultforge.api import _client_key

    request = SimpleNamespace(
        headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"},
        client=SimpleNamespace(host="10.0.0.1"),
    )

    assert _client_key(request, trust_proxy=True) == "203.0.113.9"
    assert _client_key(request, trust_proxy=False) == "10.0.0.1"


def test_rate_limiter_drops_idle_clients():
    clock = [1000.0]
    limiter = RateLimiter(max_requests=1, window_s=60, clock=lambda: clock[0])
    for n in range(50):
        limiter.check(f"client-{n}")

    clock[0] += 61
    limiter.check("fresh")

    assert limiter.tracked_clients() == 1


def test_a_busy_server_does_not_use_up_the_clients_rate_limit():
    app = create_app(mode="demo", max_active_runs=0, runs_per_window=1)
    with TestClient(app) as client:
        first = client.post("/api/runs", json={"example": "order-service"})
        second = client.post("/api/runs", json={"example": "order-service"})

    assert (first.status_code, second.status_code) == (503, 503)


def test_event_stream_resumes_after_the_last_event_id():
    from tests.test_api import wait_for

    with TestClient(create_app(mode="demo")) as client:
        run_id = client.post("/api/runs", json={"example": "order-service"}).json()["id"]
        wait_for(client, run_id)
        with client.stream(
            "GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "3"}
        ) as stream:
            body = "".join(stream.iter_text())

    first_id = next(line for line in body.splitlines() if line.startswith("id: "))
    assert first_id == "id: 4"


def test_a_failed_run_streams_its_failure_before_ending(monkeypatch):
    from tests.test_api import wait_for

    monkeypatch.setenv("FAULTFORGE_ALLOW_LOCAL_LIVE", "1")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with TestClient(create_app(mode="live")) as client:
        run_id = client.post("/api/runs", json={"example": "order-service"}).json()["id"]
        run = wait_for(client, run_id)
        with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            body = "".join(stream.iter_text())

    assert run["state"] == "failed" and "NEBIUS_API_KEY" in run["error"]
    assert body.index("run_failed") < body.index("event: end")
