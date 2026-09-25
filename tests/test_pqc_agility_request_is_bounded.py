"""`POST /api/pqc/agility` is bounded, and its signature rows test rejection too.

Two defects, one route.

1. COST. The backend forwarded any `kems` / `sigs` lists to the validator,
   unauthenticated, with no allow-list, no length cap and no de-duplication.
   Only the bodyless call was cached. One SLH-DSA keygen + sign + verify costs
   about 0.6 s in the image, the validator handler keeps running in its
   threadpool after the backend's 20 s timeout, and nginx admits a 64 MB body:
   one request could hold a worker for hours. Now the validator is only ever
   asked for its DEFAULT matrix, an explicit list is answered by selecting rows
   of it, and the validator itself refuses anything outside its defaults.

2. HALF A CHECK. /verify says that for signatures both implementations verify a
   good signature AND reject a tampered one. The liboqs half did the first only:
   `ok = verify(genuine)`. A verify that accepted everything passed. The rows now
   carry `verified` and `rejects_tampered`, and `ok` needs both.

The validator half runs against a stand-in `oqs` module, so this file needs no
liboqs on the host; tests/test_agility_matrix_spans_two_families.py covers the
real library inside the image.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import types

import httpx
import pytest
from conftest import load_service_app
from fastapi import HTTPException
from fastapi.testclient import TestClient

load_service_app("webui-backend", "webui_backend_app")
backend = importlib.import_module("webui_backend_app.main")
load_service_app("pqc-validator", "pqc_validator_app")
validator = importlib.import_module("pqc_validator_app.main")


# ---- a stand-in liboqs --------------------------------------------------------
def _fake_oqs(*, verify_accepts_anything: bool = False,
              encap_error: str | None = None) -> types.SimpleNamespace:
    kems = list(validator.DEFAULT_KEM_ALGOS) + ["FrodoKEM-640-AES"]
    sigs = list(validator.DEFAULT_SIG_ALGOS) + ["SLH_DSA_PURE_SHAKE_256F"]

    class KeyEncapsulation:
        details = {"length_public_key": 4}

        def __init__(self, algo, secret_key=None):
            self.algo = algo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def generate_keypair(self):
            return b"pkey"

        def encap_secret(self, pk):
            if encap_error:
                raise RuntimeError(encap_error)
            return b"ct" + pk, b"ss"

        def decap_secret(self, ct):
            return b"ss"

    class Signature:
        def __init__(self, algo):
            self.algo = algo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def generate_keypair(self):
            return b"pk-" + self.algo.encode()

        def sign(self, msg):
            return hashlib.sha256(msg).digest()

        def verify(self, msg, sig, pk):
            return True if verify_accepts_anything else sig == hashlib.sha256(msg).digest()

    return types.SimpleNamespace(
        get_enabled_kem_mechanisms=lambda: kems,
        get_enabled_sig_mechanisms=lambda: sigs,
        oqs_version=lambda: "0.16.0",
        KeyEncapsulation=KeyEncapsulation,
        Signature=Signature,
    )


@pytest.fixture
def oqs(monkeypatch):
    fake = _fake_oqs()
    monkeypatch.setattr(validator, "_OQS_AVAILABLE", True)
    monkeypatch.setattr(validator, "oqs", fake, raising=False)
    return fake


# ---- validator: the request model ------------------------------------------------
class TestValidatorRequest:
    def test_a_list_longer_than_the_allow_list_is_refused_before_anything_runs(self, oqs):
        too_many = ["ML-DSA-65"] * (len(validator.DEFAULT_SIG_ALGOS) + 6)
        with TestClient(validator.app) as client:
            r = client.post("/api/agility", json={"sigs": too_many})
        assert r.status_code == 422, r.text

    def test_repeats_within_the_cap_are_run_once(self, oqs):
        out = validator.agility(validator.AgilityRequest(
            kems=["ML-KEM-768", "ML-KEM-768", "HQC-1"], sigs=["ML-DSA-65", "ML-DSA-65"]))
        assert [r["algo"] for r in out["matrix"]] == ["ML-KEM-768", "HQC-1", "ML-DSA-65"]

    @pytest.mark.parametrize("field,name", [
        ("sigs", "SLH_DSA_PURE_SHAKE_256F"),     # enabled in liboqs, not in the matrix
        ("kems", "Classic-McEliece-460896"),
        ("sigs", "SLH-DSA-SHA2-128s"),           # the browser's spelling
    ])
    def test_a_name_outside_the_defaults_is_refused(self, oqs, field, name):
        with TestClient(validator.app) as client:
            r = client.post("/api/agility", json={field: [name]})
        assert r.status_code == 422, r.text

    def test_an_unknown_field_is_refused_not_ignored(self, oqs):
        with TestClient(validator.app) as client:
            r = client.post("/api/agility", json={"kem": ["ML-KEM-768"]})
        assert r.status_code == 422

    def test_no_body_runs_the_whole_default_matrix(self, oqs):
        with TestClient(validator.app) as client:
            r = client.post("/api/agility")
        assert r.status_code == 200
        algos = [row["algo"] for row in r.json()["matrix"]]
        assert algos == validator.DEFAULT_KEM_ALGOS + validator.DEFAULT_SIG_ALGOS


# ---- validator: the signature rows -------------------------------------------------
class TestSignatureRowsTestRejection:
    def test_a_correct_scheme_verifies_and_rejects(self, oqs):
        out = validator.agility(None)
        sigs = [r for r in out["matrix"] if r["family"] == "SIG"]
        assert sigs and all(r["verified"] is True for r in sigs)
        assert all(r["rejects_tampered"] is True for r in sigs)
        assert all(r["ok"] is True for r in sigs)
        assert out["summary"]["all_pass"] is True

    def test_a_verify_that_accepts_everything_fails(self, monkeypatch):
        """The case the old row could not see: it reported ok = verify(genuine)."""
        monkeypatch.setattr(validator, "_OQS_AVAILABLE", True)
        monkeypatch.setattr(validator, "oqs", _fake_oqs(verify_accepts_anything=True),
                            raising=False)
        out = validator.agility(None)
        sigs = [r for r in out["matrix"] if r["family"] == "SIG"]
        assert all(r["verified"] is True for r in sigs)
        assert all(r["rejects_tampered"] is False for r in sigs)
        assert all(r["ok"] is False for r in sigs), (
            "a signature scheme that accepts a tampered message was reported as passing")

    def test_the_tampering_is_the_browsers(self):
        """First byte XOR 0xFF, as pqc.ts does, so both sides face the same test."""
        msg = validator.AGILITY_PROBE_MESSAGE
        t = validator._tampered(msg)
        assert t != msg and len(t) == len(msg)
        assert t[0] == msg[0] ^ 0xFF and t[1:] == msg[1:]

    def test_a_disabled_row_says_not_tested_rather_than_failed(self, monkeypatch, oqs):
        monkeypatch.setattr(oqs, "get_enabled_sig_mechanisms", lambda: [])
        out = validator.agility(validator.AgilityRequest(sigs=["ML-DSA-65"]))
        row = next(r for r in out["matrix"] if r["family"] == "SIG")
        assert row["enabled"] is False and row["ok"] is False
        assert row["verified"] is None and row["rejects_tampered"] is None


# ---- validator: the other routes this batch touched ---------------------------------
class TestValidatorRoutes:
    def test_algorithms_are_listed_in_full_with_counts(self, oqs):
        with TestClient(validator.app) as client:
            body = client.get("/api/algorithms").json()["liboqs"]
        assert body["kems"] == oqs.get_enabled_kem_mechanisms()
        assert body["sigs"] == oqs.get_enabled_sig_mechanisms()
        assert body["n_kems"] == len(body["kems"])
        assert body["n_sigs"] == len(body["sigs"])
        assert body["version"] == "0.16.0"

    def test_every_default_algorithm_is_listed(self, oqs):
        with TestClient(validator.app) as client:
            body = client.get("/api/algorithms").json()["liboqs"]
        assert set(validator.DEFAULT_KEM_ALGOS) <= set(body["kems"])
        assert set(validator.DEFAULT_SIG_ALGOS) <= set(body["sigs"])

    def test_a_key_liboqs_refuses_is_a_400_not_a_500(self, monkeypatch):
        """FIPS 203 input check: right length, wrong content."""
        import base64
        monkeypatch.setattr(validator, "_OQS_AVAILABLE", True)
        monkeypatch.setattr(validator, "oqs",
                            _fake_oqs(encap_error="Can not encapsulate secret"),
                            raising=False)
        with TestClient(validator.app) as client:
            r = client.post("/api/interop/mlkem", json={
                "algo": "ML-KEM-768",
                "public_key_b64": base64.b64encode(b"\xff" * 4).decode()})
        assert r.status_code == 400, r.text
        assert "Can not encapsulate" in r.json()["detail"]

    def test_kat_with_an_unknown_name_is_a_400(self, oqs):
        with TestClient(validator.app) as client:
            r = client.post("/api/kat", json={"algo": "NOT-A-KEM", "seed_hex": "00"})
        assert r.status_code == 400


# ---- backend: the proxy ------------------------------------------------------------
def _default_matrix() -> dict:
    """What the validator's default matrix looks like, one row per default name."""
    rows = [{"algo": a, "family": "KEM", "enabled": True, "ok": True}
            for a in validator.DEFAULT_KEM_ALGOS]
    rows += [{"algo": a, "family": "SIG", "enabled": True, "ok": a != "ML-DSA-87",
              "verified": True, "rejects_tampered": a != "ML-DSA-87"}
             for a in validator.DEFAULT_SIG_ALGOS]
    return {"matrix": rows, "summary": {"total": len(rows)}, "library": "liboqs"}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _Validator:
    """Stands in for httpx.AsyncClient pointed at pqc-validator."""

    def __init__(self, respond):
        self.bodies: list = []
        self.respond = respond

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.bodies.append(json)
        out = self.respond()
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setattr(backend, "_pure_cache", {})

    def install(respond):
        v = _Validator(respond)
        monkeypatch.setattr(backend.httpx, "AsyncClient", lambda *a, **k: v)
        return v

    return install


def _agility(body=None):
    return asyncio.run(backend.pqc_agility(body))


class TestBackendProxy:
    def test_an_explicit_list_is_served_from_the_default_matrix(self, upstream):
        v = upstream(lambda: _Resp(200, _default_matrix()))
        out = _agility({"kems": ["HQC-3", "ML-KEM-512"], "sigs": ["ML-DSA-87"]})
        assert [r["algo"] for r in out["matrix"]] == ["HQC-3", "ML-KEM-512", "ML-DSA-87"]
        assert out["summary"] == {"total": 3, "passed": 2, "all_pass": False}
        assert v.bodies == [{}], (
            f"the caller's lists reached the validator: {v.bodies}")

    def test_a_second_request_of_any_shape_costs_the_validator_nothing(self, upstream):
        v = upstream(lambda: _Resp(200, _default_matrix()))
        _agility(None)
        out = _agility({"sigs": ["SLH_DSA_PURE_SHA2_256S"] * 3})
        assert out["cached"] is True
        assert [r["algo"] for r in out["matrix"]] == \
            validator.DEFAULT_KEM_ALGOS + ["SLH_DSA_PURE_SHA2_256S"]
        assert len(v.bodies) == 1

    @pytest.mark.parametrize("body", [
        {"sigs": ["ML-DSA-65"] * 13},                      # longer than the family
        {"sigs": ["SLH_DSA_PURE_SHAKE_256F"]},            # not in the matrix
        {"kems": "ML-KEM-768"},                            # not a list
        {"kems": [768]},                                   # not names
        {"algos": ["ML-KEM-768"]},                         # unknown field
    ])
    def test_a_malformed_or_oversized_request_is_422(self, upstream, body):
        upstream(lambda: _Resp(200, _default_matrix()))
        with pytest.raises(HTTPException) as e:
            _agility(body)
        assert e.value.status_code == 422

    def test_a_validator_error_body_is_not_cached_as_the_matrix(self, upstream):
        upstream(lambda: _Resp(500, {"detail": "liboqs failure"}))
        with pytest.raises(HTTPException) as e:
            _agility(None)
        assert e.value.status_code == 500
        assert "agility" not in backend._pure_cache, (
            "a 5xx body was stored as the matrix, to be served for the full TTL")

    def test_a_failure_is_remembered_briefly_under_its_own_key(self, upstream):
        v = upstream(lambda: httpx.ConnectError("connection refused"))
        for _ in range(3):
            with pytest.raises(HTTPException) as e:
                _agility(None)
            assert e.value.status_code == 503
        assert len(v.bodies) == 1, (
            "every viewer paid for the failed upstream call; failures are meant "
            "to be cached for PQC_AGILITY_ERROR_TTL_S")
        assert "agility:error" in backend._pure_cache
        assert "agility" not in backend._pure_cache
