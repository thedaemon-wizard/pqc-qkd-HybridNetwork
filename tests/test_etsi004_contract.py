"""Contract test for the ETSI GS QKD 004 V2.1.1 binding, against two live KMEs.

The host tests (test_etsi004_state_machine.py, test_etsi004_http_binding.py)
run the engine in one process. This drives the real containers: two uvicorn
processes, the peer exchange over the compose network, keys from the real
producer, and ETSI GS QKD 014 served by the same KME at the same time.

    make up
    sed -i 's/^  endpoint_enabled: false/  endpoint_enabled: true/' config/qkd_params.yaml
    KME_URL=... PEER_KME_URL=... pytest tests/test_etsi004_contract.py -v

The config is hot-reloaded, so no restart is needed. Without a KME the file
skips, like the 014 contract. With a KME but the binding off it skips too --
unless ETSI004_REQUIRED is set, which the CI live-stack job does after
switching the binding on, so there a disabled binding fails instead of
passing by skipping.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

KME_URL = os.environ.get("KME_URL", "http://localhost:8080")          # ALICE
PEER_KME_URL = os.environ.get("PEER_KME_URL", "http://localhost:8081")  # BOB
SAE_ID = os.environ.get("SAE_ID", "ALICE")
PEER_SAE_ID = os.environ.get("PEER_SAE_ID", "BOB")
PREFIX = "/etsi004/v2.1.1"
SRC, DST = f"sae://{SAE_ID.lower()}/contract", f"sae://{PEER_SAE_ID.lower()}/contract"
# Keys come from the real producer; this bounds the wait for one.
KEY_WAIT_S = 30.0


def _reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return all(c.get(f"{u}/health").status_code == 200 for u in (KME_URL, PEER_KME_URL))
    except Exception:
        return False


pytestmark = [
    pytest.mark.live_stack,
    pytest.mark.skipif(not _reachable(), reason=f"no KMEs at {KME_URL} / {PEER_KME_URL}"),
]


@pytest.fixture(scope="module", autouse=True)
def _binding_on():
    with httpx.Client(timeout=5.0) as c:
        r = c.post(f"{KME_URL}{PREFIX}/open_connect", json={})
    if r.status_code == 404:
        msg = "etsi004.endpoint_enabled is false on the live KME"
        if os.environ.get("ETSI004_REQUIRED"):
            pytest.fail(msg + " (ETSI004_REQUIRED is set)")
        pytest.skip(msg)
    assert r.status_code == 422, r.text          # enabled: an empty body is malformed


def _post(url: str, path: str, body: dict) -> httpx.Response:
    with httpx.Client(timeout=40.0) as c:
        return c.post(f"{url}{PREFIX}/{path}", json=body)


def _call(url: str, path: str, body: dict) -> dict:
    r = _post(url, path, body)
    assert r.status_code == 200, (path, r.status_code, r.text)
    return r.json()


def _open_pair(qos: dict | None = None) -> str:
    body = {"source": SRC, "destination": DST}
    if qos:
        body["QoS"] = qos
    r = _call(KME_URL, "open_connect", body)
    assert r["status"] == 1, r
    ksid = r["Key_stream_ID"]
    r = _call(PEER_KME_URL, "open_connect",
              {"source": DST, "destination": SRC, "Key_stream_ID": ksid})
    assert r["status"] == 0, r
    return ksid


def _close(ksid: str) -> None:
    for url in (KME_URL, PEER_KME_URL):
        _post(url, "close", {"Key_stream_ID": ksid})


def _get_when_produced(url: str, body: dict) -> dict:
    """GET_KEY, repeating status 2 (no key yet) until the producer caught up."""
    deadline = time.monotonic() + KEY_WAIT_S
    while True:
        r = _call(url, "get_key", body)
        if r["status"] != 2 or time.monotonic() > deadline:
            return r
        time.sleep(0.5)


def test_both_applications_read_the_same_key():
    ksid = _open_pair()
    try:
        a = _get_when_produced(KME_URL, {"Key_stream_ID": ksid})
        assert a["status"] == 0 and a["index"] == 0, a
        b = _call(PEER_KME_URL, "get_key", {"Key_stream_ID": ksid, "index": 0})
        assert b["status"] == 0, b
        assert a["Key_buffer"] == b["Key_buffer"]
        assert len(base64.b64decode(a["Key_buffer"])) > 0
        # Read once per side: the same index again is status 2 (T21).
        again = _call(KME_URL, "get_key", {"Key_stream_ID": ksid, "index": 0})
        assert again["status"] == 2, again
    finally:
        _close(ksid)
    # Closed on both sides: unknown now (T20).
    assert _post(KME_URL, "get_key", {"Key_stream_ID": ksid}).status_code == 404


def test_status_3_before_the_peer_application_opens():
    r = _call(KME_URL, "open_connect", {"source": SRC, "destination": DST})
    ksid = r["Key_stream_ID"]
    try:
        assert _call(KME_URL, "get_key", {"Key_stream_ID": ksid})["status"] == 3
    finally:
        _post(KME_URL, "close", {"Key_stream_ID": ksid})


def test_status_5_for_a_key_stream_id_in_use():
    ksid = _open_pair()
    try:
        r = _call(KME_URL, "open_connect", {"source": SRC, "destination": DST, "Key_stream_ID": ksid})
        assert r["status"] == 5, r
        r = _call(KME_URL, "open_connect",
                  {"source": "sae://carol/contract", "destination": DST, "Key_stream_ID": ksid})
        assert r["status"] == 5, r
    finally:
        _close(ksid)


def test_status_7_for_a_chunk_size_that_is_not_whole_keys():
    r = _call(KME_URL, "open_connect",
              {"source": SRC, "destination": DST, "QoS": {"Key_chunk_size": 33}})
    assert r["status"] == 7 and r.get("Key_stream_ID") is None, r
    assert r["QoS"]["Key_chunk_size"] != 33


def test_status_8_holds_the_key_for_the_retry():
    ksid = _open_pair()
    try:
        r = _get_when_produced(KME_URL, {"Key_stream_ID": ksid, "Metadata": {"Metadata_size": 1}})
        assert r["status"] == 8 and "Key_buffer" not in r, r
        need, index = r["Metadata"]["Metadata_size"], r["index"]
        r = _call(KME_URL, "get_key", {"Key_stream_ID": ksid, "index": index,
                                       "Metadata": {"Metadata_size": need}})
        assert r["status"] == 0 and r["index"] == index, r
        b = _call(PEER_KME_URL, "get_key", {"Key_stream_ID": ksid, "index": index})
        assert b["Key_buffer"] == r["Key_buffer"]
    finally:
        _close(ksid)


def test_a_predefined_id_blocks_until_the_peer_opens():
    ksid = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call, KME_URL, "open_connect",
                        {"source": SRC, "destination": DST, "Key_stream_ID": ksid,
                         "QoS": {"Timeout": 10000}})
        time.sleep(1.0)
        b = _call(PEER_KME_URL, "open_connect",
                  {"source": DST, "destination": SRC, "Key_stream_ID": ksid})
        a = fut.result(timeout=15)
    try:
        assert a["status"] == 0 and b["status"] == 0, (a, b)
    finally:
        _close(ksid)


def test_ttl_closes_an_idle_stream():
    ksid = _open_pair({"TTL": 1})
    time.sleep(4.0)                      # TTL plus two sweep intervals
    assert _post(KME_URL, "get_key", {"Key_stream_ID": ksid}).status_code == 404


def test_malformed_is_422_and_unknown_is_404():
    assert _post(KME_URL, "get_key", {"Key_stream_ID": "not-a-uuid"}).status_code == 422
    assert _post(KME_URL, "get_key", {"Key_stream_ID": str(uuid.uuid4())}).status_code == 404


def test_etsi_014_is_served_while_004_drains_the_pool():
    """The 014 floor: a 004 stream reading as fast as it can leaves enc_keys working."""
    ksid = _open_pair()
    try:
        _get_when_produced(KME_URL, {"Key_stream_ID": ksid})
        with httpx.Client(timeout=10.0) as c:
            stats = c.get(f"{KME_URL}/sim/stats").json()
        for _ in range(int(stats["pool_size"]) + 1):
            if _call(KME_URL, "get_key", {"Key_stream_ID": ksid})["status"] != 0:
                break
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{KME_URL}/api/v1/keys/{PEER_SAE_ID}/enc_keys", params={"number": 1, "size": 256})
        assert r.status_code == 200, r.text
    finally:
        _close(ksid)
