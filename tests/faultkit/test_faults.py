import json
import time

import httpx
import pytest

from faultforge.faultkit import (
    DuplicateDelivery,
    FakeAPI,
    FaultyTransport,
    Malformed,
    RateLimit,
    Timeout,
)

URL = "https://dependency.test/things"


def client(api: FakeAPI, *faults) -> httpx.Client:
    return httpx.Client(transport=FaultyTransport(api, *faults))


def test_fake_api_records_accepted_requests():
    api = FakeAPI()

    response = client(api).post(URL, json={"n": 1})

    assert response.status_code == 201
    assert api.accepted == [{"n": 1}]


def test_fake_api_replays_result_for_repeated_idempotency_key():
    api = FakeAPI()
    http = client(api)

    first = http.post(URL, json={"n": 1}, headers={"Idempotency-Key": "k1"})
    second = http.post(URL, json={"n": 1}, headers={"Idempotency-Key": "k1"})

    assert first.json() == second.json()
    assert len(api.accepted) == 1


def test_timeout_after_processing_raises_but_dependency_still_accepted():
    api = FakeAPI()

    with pytest.raises(httpx.ReadTimeout):
        client(api, Timeout(on_calls={1}, after_processing=True)).post(URL, json={"n": 1})

    assert api.accepted == [{"n": 1}]


def test_timeout_before_processing_leaves_dependency_untouched():
    api = FakeAPI()

    with pytest.raises(httpx.ConnectTimeout):
        client(api, Timeout(on_calls={1}, after_processing=False)).post(URL, json={"n": 1})

    assert api.accepted == []


def test_timeout_only_hits_the_listed_calls():
    api = FakeAPI()
    http = client(api, Timeout(on_calls={1}))

    with pytest.raises(httpx.TimeoutException):
        http.post(URL, json={"n": 1})
    second = http.post(URL, json={"n": 2})

    assert second.status_code == 201


def test_rate_limit_returns_429_with_retry_after_without_processing():
    api = FakeAPI()

    response = client(api, RateLimit(on_calls={1}, retry_after=7)).post(URL, json={"n": 1})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert api.accepted == []


def test_malformed_response_returns_unparseable_body_after_processing():
    api = FakeAPI()

    response = client(api, Malformed(on_calls={1})).post(URL, json={"n": 1})

    assert response.status_code == 200
    with pytest.raises(json.JSONDecodeError):
        response.json()
    assert len(api.accepted) == 1


def test_duplicate_delivery_sends_the_request_to_the_dependency_twice():
    api = FakeAPI()

    client(api, DuplicateDelivery(on_calls={1})).post(URL, json={"n": 1})

    assert api.accepted == [{"n": 1}, {"n": 1}]


def test_transport_counts_calls():
    api = FakeAPI()
    transport = FaultyTransport(api)
    http = httpx.Client(transport=transport)

    http.post(URL, json={"n": 1})
    http.post(URL, json={"n": 2})

    assert transport.calls == 2


def test_faults_never_sleep():
    api = FakeAPI()
    http = client(api, Timeout(on_calls={1}), RateLimit(on_calls={2}, retry_after=60))
    started = time.monotonic()

    with pytest.raises(httpx.TimeoutException):
        http.post(URL, json={})
    http.post(URL, json={})

    assert time.monotonic() - started < 0.5


def test_fake_api_can_answer_with_a_custom_body_and_status():
    api = FakeAPI(status=200, body={"status": "failed"})

    response = client(api).get(URL + "/ch_1")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
