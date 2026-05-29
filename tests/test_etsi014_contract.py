"""Contract test for the ETSI GS QKD 014 endpoints.

This is the **single most important test**: if the JSON shape drifts, arnika cannot parse
the response (see submodules/arnika-vq/kms/kms.go:69-76) and the whole hybrid layer breaks.

Run after `make up`:
    pytest tests/test_etsi014_contract.py -v
"""
from __future__ import annotations

import base64
import os
import time

import httpx
import pytest

KME_URL = os.environ.get("KME_URL", "http://localhost:8080")
SAE_ID = os.environ.get("SAE_ID", "ALICE")


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

        # 2) Allow a moment for the internal sync to propagate
        time.sleep(0.5)

        # 3) Retrieve the same key from the peer KME using its ID
        r2 = client.get(f"{peer_url}/api/v1/keys/{peer_sae}/dec_keys",
                        params={"key_ID": k["key_ID"]})
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
