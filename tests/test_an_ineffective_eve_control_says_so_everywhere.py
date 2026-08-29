"""A control that changes nothing must not report success.

`POST /sim/eve` returned `{"ok": true}` on every backend. The shipped default
is `simqn` (config/qkd_params.yaml), and `simqn` never reads `cfg.eve_enabled`:
`intercepted=0` is a literal at `simqn_backend.py:197`. Driven with
`prob=1.0` the next round came back with the QBER unchanged and
`intercepted=0` -- so "Eve is not modelled here" and "Eve was modelled and
found nothing" produced byte-identical output, on the backend the demo runs.

Only `qutip_backend` passes the flag into its channel model. Only
`qkdnetsim_proxy` said so, and it said so for itself:

    meta["eve_ignored"] = True

That marker is now on `KeyProducer`, so `simqn`, `sequence`, `cvqkd` and `tno`
declare the omission too rather than each needing to remember.

There is an existing test for this property --
`tests/test_synthetic_physics_reaches_a_caller.py::test_an_ineffective_eve_control_says_so`
-- and it only ever constructs `QKDNetSimProxyBackend`, the one backend that
was already correct. A guard aimed at the one case that did not need it.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))

from app.backends.base import KeyProducer, cfg_from_yaml  # noqa: E402

BACKENDS = ROOT / "services" / "bb84-kme" / "app" / "backends"

# Every backend that hardcodes intercepted=0 and never reads the flag.
SILENT = ["simqn_backend", "sequence_backend", "cvqkd_backend", "tno_backend"]


class _Silent(KeyProducer):
    backend_name = "silent"

    async def run_round(self):  # pragma: no cover - never called
        raise NotImplementedError


class _Modelling(KeyProducer):
    backend_name = "modelling"
    models_eve = True

    async def run_round(self):  # pragma: no cover - never called
        raise NotImplementedError


# --------------------------------------------------------------------------
# The marker itself.
# --------------------------------------------------------------------------

def test_a_backend_that_ignores_eve_declares_it():
    b = _Silent(cfg_from_yaml())
    b.set_eve(True, 1.0)
    meta = b.eve_meta()
    assert meta.get("eve_ignored") is True
    assert "intercepted" in meta.get("unmeasured", [])
    assert "not because none was detected" in meta.get("note", "")


def test_a_backend_that_models_eve_declares_nothing():
    """Otherwise every round would carry a warning that does not apply."""
    b = _Modelling(cfg_from_yaml())
    b.set_eve(True, 1.0)
    assert b.eve_meta() == {}


def test_nothing_is_declared_when_eve_is_off():
    """`eve_ignored` on a round with no Eve requested would be noise."""
    for cls in (_Silent, _Modelling):
        b = cls(cfg_from_yaml())
        b.set_eve(False, 1.0)
        assert b.eve_meta() == {}


def test_the_default_is_not_modelled():
    """A new backend must opt IN to claiming it models Eve.

    Defaulting to True would make silence mean "modelled", which is the
    direction that produced this defect.
    """
    assert KeyProducer.models_eve is False


# --------------------------------------------------------------------------
# Each silent backend actually merges it.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mod", SILENT)
def test_each_silent_backend_merges_the_marker(mod):
    src = (BACKENDS / f"{mod}.py").read_text(encoding="utf-8")
    assert "self.eve_meta()" in src, (
        f"{mod} builds backend_meta without merging eve_meta(), so a round on "
        f"it still reports intercepted=0 with nothing saying why")


@pytest.mark.parametrize("mod", SILENT)
def test_no_silent_backend_claims_to_model_eve(mod):
    src = (BACKENDS / f"{mod}.py").read_text(encoding="utf-8")
    assert "models_eve = True" not in src, (
        f"{mod} claims models_eve, which suppresses the marker. If it really "
        f"reads cfg.eve_enabled now, this test should be updated -- but check "
        f"that intercepted is no longer a hardcoded 0 first")


def test_qutip_is_still_the_one_that_models_eve():
    """Derived, not asserted from memory: it must actually read the flag."""
    src = (BACKENDS / "qutip_backend.py").read_text(encoding="utf-8")
    assert "models_eve = True" in src
    assert "eve_enabled=self.cfg.eve_enabled" in src, (
        "qutip declares models_eve but no longer passes the flag into its "
        "channel model")


def test_the_claim_and_the_code_cannot_drift_apart():
    """Any backend claiming models_eve must reference the flag.

    This is the assertion that would have caught the original defect if the
    attribute had existed: simqn would have had to claim it, and the claim
    would have been checkable.
    """
    offenders = []
    for path in BACKENDS.glob("*_backend.py"):
        src = path.read_text(encoding="utf-8")
        if "models_eve = True" in src and "eve_enabled" not in src:
            offenders.append(path.name)
    assert not offenders, (
        f"these claim to model Eve without reading cfg.eve_enabled: {offenders}")


# --------------------------------------------------------------------------
# The endpoint reports effectiveness.
# --------------------------------------------------------------------------

def test_the_endpoint_reports_whether_the_control_is_effective():
    src = (ROOT / "services" / "bb84-kme" / "app" / "main.py").read_text(
        encoding="utf-8")
    body = src[src.index('@app.post("/sim/eve")'):]
    body = body[:body.index('@app.get("/sim/stats")')]
    assert '"effective": effective' in body, (
        "/sim/eve no longer reports whether the active backend acts on the "
        "flag, so it is back to returning ok:true regardless")
    assert 'getattr(backend, "models_eve", False)' in body
    assert "note" in body, (
        "an ineffective control should explain itself, not just flag itself")


def test_the_endpoint_still_stores_the_flag():
    """It must not become a 501.

    The flag propagates through update_config, so switching to qutip
    afterwards makes it take effect. Refusing the request would be a
    different inaccuracy.
    """
    src = (ROOT / "services" / "bb84-kme" / "app" / "main.py").read_text(
        encoding="utf-8")
    body = src[src.index('@app.post("/sim/eve")'):]
    body = body[:body.index('@app.get("/sim/stats")')]
    assert "set_eve(ctl.enabled, ctl.prob)" in body
    # Match the RAISE, not the digits. A first version of this asserted
    # `"501" not in body` and failed on the handler's own docstring, which
    # explains why it does not return one -- the same self-reference that
    # keeps catching guards in this suite.
    assert "HTTPException(501" not in body
    assert "status_code=501" not in body
