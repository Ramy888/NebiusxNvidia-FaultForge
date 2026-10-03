import json
import time

import pytest
from fastapi.testclient import TestClient

from faultforge.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app(mode="demo")) as test_client:
        yield test_client


def wait_for(client: TestClient, run_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] in ("finished", "failed"):
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_lists_the_prepared_examples(client):
    examples = client.get("/api/examples").json()

    assert {e["id"] for e in examples} == {"order-service", "webhook-service"}
    assert all(e["description"] for e in examples)


def test_starting_a_run_returns_its_id(client):
    response = client.post("/api/runs", json={"example": "order-service"})

    assert response.status_code == 202
    assert response.json()["id"]


def test_unknown_examples_are_rejected(client):
    response = client.post("/api/runs", json={"example": "../../etc"})

    assert response.status_code == 404


def test_finished_run_has_structured_evidence(client):
    run_id = client.post("/api/runs", json={"example": "order-service"}).json()["id"]

    run = wait_for(client, run_id)

    assert run["state"] == "finished"
    result = run["result"]
    assert result["status"] == "repaired"
    assert result["winner"] == "idempotency_key"
    [scenario] = result["scenarios"]
    assert scenario["baseline"]["outcome"] == "failed"
    ranked = {c["id"]: c for c in result["candidates"]}
    assert ranked["idempotency_key"]["scenarios"][scenario["id"]]["outcome"] == "passed"
    assert "Idempotency-Key" in ranked["idempotency_key"]["diff"]
    assert "# FaultForge report" in result["markdown"]


def test_event_stream_replays_the_whole_run(client):
    run_id = client.post("/api/runs", json={"example": "order-service"}).json()["id"]
    wait_for(client, run_id)

    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        body = "".join(stream.iter_text())

    blocks = [block for block in body.split("\n\n") if block.strip()]
    events = [
        json.loads(block.split("data: ", 1)[1]) for block in blocks if "event: end" not in block
    ]
    assert "event: end" in blocks[-1]
    assert events[0]["type"] == "pipeline_started"
    assert events[-1]["type"] == "pipeline_finished"
    assert [e["seq"] for e in events] == list(range(len(events)))


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/nope").status_code == 404


def test_pull_request_preview_for_a_repaired_run(client):
    run_id = client.post("/api/runs", json={"example": "order-service"}).json()["id"]
    wait_for(client, run_id)

    preview = client.post(f"/api/runs/{run_id}/pull-request").json()

    assert preview["dry_run"] is True
    assert preview["branch"] == "faultforge/idempotency_key"
    assert "orders/fulfillment.py" in preview["files"]


def test_pull_request_for_an_unfinished_or_unknown_run(client):
    assert client.post("/api/runs/nope/pull-request").status_code == 404
