"""Contract test for the ETSI GS QKD 014 endpoints.

This is the **single most important test**: if the JSON shape drifts, arnika cannot parse
the response (see submodules/arnika/repositories/kms.go:43-48) and the whole hybrid layer breaks.

These tests drive a REAL KME over HTTP, so they need a running stack:

    make up && pytest tests/test_etsi014_contract.py -v

Without one they skip rather than fail, so `pytest tests/` is meaningful on a
bare checkout. CI runs them with the stack up (see .github/workflows/ci.yml),
which is where a contract regression must be caught.
"""
from __future__ import annotations

import base64
import os
import time

import httpx
import pytest

KME_URL = os.environ.get("KME_URL", "http://localhost:8080")
SAE_ID = os.environ.get("SAE_ID", "ALICE")
# ETSI 014 clause 5.1: enc_keys names the SLAVE SAE, dec_keys the MASTER --
# from either node that is always the peer.
PEER_SAE_ID = os.environ.get("PEER_SAE_ID", "BOB")


def _kme_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get(f"{KME_URL}/health").status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.live_stack,
    pytest.mark.skipif(
        not _kme_reachable(),
        reason=f"no KME at {KME_URL}; start the stack with `make up`",
    ),
]


def _wait_for_pool(client: httpx.Client, timeout: float = 30.0) -> None:
    """Wait until at least one key is in the pool."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = client.get(f"{KME_URL}/api/v1/keys/{SAE_ID}/status")
        if r.status_code == 200 and r.json().get("stored_key_count", 0) > 0:
            return
        time.sleep(1.0)
    raise TimeoutError("KME never produced any keys")


def test_enc_keys_schema():
    with httpx.Client(timeout=10.0) as client:
        _wait_for_pool(client)
        r = client.get(f"{KME_URL}/api/v1/keys/{SAE_ID}/enc_keys",
                       params={"number": 1, "size": 256})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "keys" in body and isinstance(body["keys"], list) and len(body["keys"]) == 1

        k = body["keys"][0]
        # arnika requires exactly these two fields, exactly these names:
        assert set(k.keys()) == {"key_ID", "key"}, k
        assert isinstance(k["key_ID"], str) and len(k["key_ID"]) >= 8
        decoded = base64.b64decode(k["key"])
        assert len(decoded) == 32, f"key must be 32 bytes (256 bit), got {len(decoded)}"



def _dec_keys_when_synced(client: httpx.Client, url: str, timeout: float = 15.0,
                          **kwargs) -> httpx.Response:
    """GET/POST dec_keys, retrying until the peer KME has the key.

    Propagation to the peer is asynchronous -- `KeyPool._sync_to_peer` POSTs to
    the neighbour, and its HTTP client alone allows 2.0 s. These tests used to
    wait a fixed `time.sleep(0.5)` and assert once, so a sync slower than half a
    second failed with `404 unknown key_ID` and nothing about the product was
    wrong. Observed in CI on a branch that changed only a shell script, a test
    exemption and a checklist row.

    Polling to a deadline is the same wait the file already uses for the key
    pool (`_wait_for_pool`); these two call sites just had not adopted it. The
    deadline is well above the 2.0 s sync timeout so a genuine failure to
    propagate still fails the test rather than hanging.
    """
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.request(url=url, **kwargs)
        if last.status_code == 200:
            return last
        if last.status_code != 404:
            return last          # a real error, not "not yet"
        time.sleep(0.25)
    return last


def test_dec_keys_roundtrip():
    """A key fetched via enc_keys must be retrievable from the PEER KME via dec_keys."""
    peer_url = os.environ.get("PEER_KME_URL", "http://localhost:8081")
    peer_sae = os.environ.get("PEER_SAE_ID", "BOB")

    with httpx.Client(timeout=10.0) as client:
        _wait_for_pool(client)
        # 1) Get a key from the local KME
        r = client.get(f"{KME_URL}/api/v1/keys/{SAE_ID}/enc_keys",
                       params={"number": 1, "size": 256})
        assert r.status_code == 200
        k = r.json()["keys"][0]

        # 2+3) Retrieve the same key from the peer KME, waiting for the
        # asynchronous sync rather than guessing how long it takes.
        r2 = _dec_keys_when_synced(
            client, f"{peer_url}/api/v1/keys/{peer_sae}/dec_keys",
            method="GET", params={"key_ID": k["key_ID"]})
        assert r2.status_code == 200, r2.text
        assert r2.json()["keys"][0]["key"] == k["key"]


def test_status_endpoint():
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{KME_URL}/api/v1/keys/{SAE_ID}/status")
        assert r.status_code == 200
        s = r.json()
        for field in ["source_KME_ID", "target_KME_ID", "key_size",
                      "stored_key_count", "max_key_count"]:
            assert field in s, f"missing required field {field}"
        assert s["key_size"] == 256


# ---------------------------------------------------------------------------
# Specification conformance beyond the arnika client's own usage.
#
# arnika only issues the GET forms, so these guard the parts of GS QKD 014 that
# a different SAE implementation would rely on -- and that Edition 2 makes
# mandatory when it removes GET entirely.
# ---------------------------------------------------------------------------


def test_enc_keys_post_form():
    """POST is the specification's baseline; GET is the optional convenience."""
    with httpx.Client(timeout=10.0) as client:
        _wait_for_pool(client)
        r = client.post(
            f"{KME_URL}/api/v1/keys/{PEER_SAE_ID}/enc_keys",
            json={"number": 1, "size": 256},
        )
        assert r.status_code == 200, r.text
        k = r.json()["keys"][0]
        assert set(k.keys()) == {"key_ID", "key"}
        assert len(base64.b64decode(k["key"])) == 32


def test_dec_keys_post_form_takes_array_of_objects():
    """`key_IDs` is an array of OBJECTS, not of bare strings.

    Sending `["uuid"]` instead of `[{"key_ID": "uuid"}]` is one of the most
    common 014 interop failures, so the object form must be what works.
    """
    peer_url = os.environ.get("PEER_KME_URL", "http://localhost:8081")

    with httpx.Client(timeout=10.0) as client:
        _wait_for_pool(client)
        r = client.post(
            f"{KME_URL}/api/v1/keys/{PEER_SAE_ID}/enc_keys",
            json={"number": 1, "size": 256},
        )
        assert r.status_code == 200
        k = r.json()["keys"][0]

        r2 = _dec_keys_when_synced(
            client, f"{peer_url}/api/v1/keys/{SAE_ID}/dec_keys",
            method="POST", json={"key_IDs": [{"key_ID": k["key_ID"]}]})
        assert r2.status_code == 200, r2.text
        assert r2.json()["keys"][0]["key"] == k["key"]

        # The bare-string form must be rejected, not silently coerced.
        r3 = client.post(
            f"{peer_url}/api/v1/keys/{SAE_ID}/dec_keys",
            json={"key_IDs": [k["key_ID"]]},
        )
        assert r3.status_code == 422, "array-of-strings must be a validation error"


def test_size_is_in_bits_not_bytes():
    """GS QKD 014 counts key size in BITS; GS QKD 004 uses bytes."""
    with httpx.Client(timeout=10.0) as client:
        _wait_for_pool(client)
        # 32 would be a valid BYTE count for a 256-bit key, and must be refused.
        r = client.post(
            f"{KME_URL}/api/v1/keys/{PEER_SAE_ID}/enc_keys",
            json={"number": 1, "size": 32},
        )
        assert r.status_code == 400, "size is in bits; 32 must not be accepted"
        assert "bits" in r.json()["detail"]


def test_unknown_key_id_is_404():
    with httpx.Client(timeout=10.0) as client:
        r = client.get(
            f"{KME_URL}/api/v1/keys/{PEER_SAE_ID}/dec_keys",
            params={"key_ID": "00000000-0000-0000-0000-000000000000"},
        )
        assert r.status_code == 404
