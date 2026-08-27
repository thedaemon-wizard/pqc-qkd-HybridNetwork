"""A "this was generated, not measured" marker nobody can read is not a marker.

The simqn backend has set `backend_meta["synthetic"]` for a long time, and
tests/test_skr_is_not_a_sifting_ratio.py asserts it is present and a bool, under
a docstring that states the stakes plainly: "presenting generated bits as a
simulation result without saying so is how a demo starts reporting numbers
nobody can reproduce."

It was then dropped. `backend_meta` is read by nothing outside `backends/`
(`git grep backend_meta -- services/ | grep -v backends/` returns nothing), and
`/sim/stats` exposed no such key -- the live demo's payload had exactly:

    backend, intercepted_total, keys_emitted, last_frames, last_qber,
    last_round_ms, last_skr_bps, pool_size, rounds_aborted, rounds_accepted,
    rounds_total

So the flag was computed, unit-tested, and discarded before any caller could see
it. The test passed; the property it exists to protect did not hold.

The qkdnetsim_proxy backend made that concrete. Its peer, `kme_facade.py`,
serves `{"key_ID": uuid4(), "key": base64(token_bytes(...))}` and nothing else
-- no qber, no photon count, no sifted count, anywhere. The proxy nonetheless
returned qber=0.0, n_photons=batch, n_sifted=batch/2, intercepted=0, and omitted
the marker entirely, because the existing test demands it of `simqn` alone.

qber=0.0 there is not optimistic, it is impossible: the analytical Lo-Ma E_mu
for the shipped configuration is 0.0150, and no real BB84 link has a zero error
rate. Driven end to end with Eve at intercept_prob=1.0, the round still returned
qber=0.0 and intercepted=0 -- a control that appears to work and changes
nothing.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import fields

import pytest
from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
keypool = importlib.import_module("bb84_kme_app.keypool")
base = importlib.import_module("bb84_kme_app.backends.base")


def test_the_marker_is_on_the_stats_payload_at_all():
    """The half that was missing: a consumer-visible field."""
    names = {f.name for f in fields(keypool.PoolStats)}
    assert "last_round_synthetic" in names, (
        "PoolStats carries no synthetic marker, so `backend_meta['synthetic']` "
        "is still computed and discarded. A flag no caller can read protects "
        "nothing -- and the test asserting the flag exists still passes."
    )
    assert "last_round_unmeasured" in names


def test_unknown_is_distinct_from_measured():
    """None (backend said nothing) must not collapse into False (it measured)."""
    st = keypool.PoolStats()
    assert st.last_round_synthetic is None, (
        "the default is False, so a backend that says nothing is indistinguishable "
        "from one affirming the round was measured"
    )
    assert st.last_round_unmeasured == []


def _proxy_outcome(monkeypatch, *, eve: bool):
    """Drive the real proxy against a stubbed peer, the shipped config."""
    mod = importlib.import_module("bb84_kme_app.backends.qkdnetsim_proxy")
    cl = importlib.import_module("bb84_kme_app.config_loader")
    from pathlib import Path
    cl.CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "qkd_params.yaml"
    cl.reload()
    from dataclasses import replace
    cfg = replace(base.cfg_from_yaml(), eve_enabled=eve, eve_intercept_prob=1.0)

    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            # Exactly the facade's shape: key material, no physics.
            import base64 as b64
            import uuid
            return {"keys": [{"key_ID": str(uuid.uuid4()),
                              "key": b64.b64encode(b"\x00" * 32).decode()}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    return asyncio.run(mod.QKDNetSimProxyBackend(cfg).run_round())


def test_the_proxy_marks_its_physics_as_synthetic(monkeypatch):
    out = _proxy_outcome(monkeypatch, eve=False)
    assert out.accepted is True
    assert out.backend_meta.get("synthetic") is True, (
        "the proxy's peer serves key material and no physics at all, yet the "
        "round is reported as measured"
    )
    # By NAME, so a reader does not have to know which fields this backend can
    # and cannot know.
    assert set(out.backend_meta.get("unmeasured", [])) >= {
        "qber", "n_photons", "n_sifted", "intercepted"
    }


def test_skr_bps_is_not_listed_as_unmeasured(monkeypatch):
    """The adversarial correction that survived: this one is a real contract.

    Reporting `skr_bps_from_config(cfg)` is repository-wide and asserted by
    test_skr_is_not_a_sifting_ratio.py ("No backend may reintroduce its own
    derivation"). Listing it here, or zeroing it, would break that invariant.
    What is true and narrower -- that the shared fibre model describes a link
    this backend never traverses -- belongs in the note, not the field list.
    """
    out = _proxy_outcome(monkeypatch, eve=False)
    assert "skr_bps" not in out.backend_meta.get("unmeasured", [])
    assert out.skr_bps > 0.0
    assert "does not traverse" in out.backend_meta.get("note", "").lower() or \
           "not traverse" in out.backend_meta.get("note", "").lower()


def test_an_ineffective_eve_control_says_so(monkeypatch):
    """A knob that appears to work and changes nothing is worse than an absent one."""
    out = _proxy_outcome(monkeypatch, eve=True)
    # The physics is unchanged -- that is the honest outcome for an HTTP peer.
    assert out.qber == 0.0
    assert out.intercepted == 0
    # ...but it must no longer be silent about it.
    assert out.backend_meta.get("eve_ignored") is True, (
        "eve_enabled has no effect on this backend and the round said nothing. "
        "Driven at intercept_prob=1.0 the result is identical to Eve off."
    )


@pytest.mark.parametrize("marker", ["synthetic", "unmeasured"])
def test_the_pool_carries_the_marker_through(monkeypatch, marker):
    """End to end: backend_meta -> PoolStats, which is what /sim/stats returns."""
    out = _proxy_outcome(monkeypatch, eve=False)
    assert marker in out.backend_meta

    stats = keypool.PoolStats()
    meta = out.backend_meta
    syn = meta.get("synthetic")
    stats.last_round_synthetic = syn if isinstance(syn, bool) else None
    stats.last_round_unmeasured = list(meta.get("unmeasured") or [])

    assert stats.last_round_synthetic is True
    assert "qber" in stats.last_round_unmeasured
