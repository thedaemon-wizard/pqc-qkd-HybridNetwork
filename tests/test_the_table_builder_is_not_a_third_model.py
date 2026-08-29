"""The offline table builder must delegate, not carry its own decoy model.

`docs/keyrate.md`, `tests/test_keyrate_golden_vector.py` and `.github/workflows/ci.yml`
all describe the drift risk as "the same model is implemented three times".
Two of those three were kept in step. The third --
`tools/precompute_keyrate_table_fallback.py` -- received half the corrections,
and the half it missed contained a hard failure:

    def decoy_bounds(p) -> tuple[float, float]:
        ...
        denom = p.mu * p.nu1 - p.mu * p.nu2 - p.nu1 * p.nu1 + p.nu2 * p.nu2
        if denom <= 0:
            return 0.0            # a bare float from a tuple-annotated
                                  # function; the only caller unpacks two

Reproduced before the fix with mu=0.5, nu1=0.3, nu2=0.25 -- which violates
Ma et al. PRA 72, 012326 (2005) Eq. (15)'s `nu1 + nu2 < mu`, the exact
condition that branch exists to enforce:

    denom = -0.002500
    TypeError: cannot unpack non-iterable float object

Reachable from the browser: `source.intensity_decoy_2_nu2` is an editable
field on /physics with bound `[0, null]`, so nu2 has no upper limit.

The builder now calls `_skr` for the asymptotic half, as it already did for
the finite-key half. This file pins that, because the cheapest way for the
third copy to come back is for someone to inline "just this one formula" again.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "precompute_keyrate_table_fallback.py"

os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))


def _tool():
    """Import the builder under a real module name.

    `dataclass` resolves annotations through `sys.modules[cls.__module__]`, so
    a spec-loaded module that is not registered raises
    `AttributeError: 'NoneType' object has no attribute '__dict__'`.
    """
    spec = importlib.util.spec_from_file_location("_kr_table_tool", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_kr_table_tool"] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# The failure that was there.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mu,nu1,nu2", [
    (0.5, 0.3, 0.25),    # nu1 + nu2 = 0.55 > mu  -- the reproduced case
    (0.5, 0.4, 0.2),     # nu1 + nu2 = 0.60 > mu
    (0.3, 0.2, 0.15),    # same violation at a different scale
])
def test_a_parameter_set_outside_the_validity_condition_does_not_raise(mu, nu1, nu2):
    """Ma Eq. (15) requires 0 <= nu2 < nu1 and nu1 + nu2 < mu.

    Outside it the rate is not defined and 0 is the right answer. A TypeError
    is not: it aborts the whole table build, and /physics can reach these
    values because nu2 has no upper bound.
    """
    m = _tool()
    p = m.PhysParams(distance_km=50.0, eta_d=0.2, Y0=1e-6,
                     mu=mu, nu1=nu1, nu2=nu2)
    assert nu1 + nu2 > mu, "precondition: this parameter set must violate Eq. (15)"
    assert m.asymptotic_skr_per_pulse(p) == 0.0


def test_the_local_decoy_model_is_gone():
    """Delegation, asserted by absence.

    Repairing `decoy_bounds` in place would have left three implementations
    and the next divergence unguarded. The fix was to delete it.
    """
    m = _tool()
    assert not hasattr(m, "decoy_bounds"), (
        "tools/ carries its own decoy_bounds again. Call _skr instead -- "
        "finite_key_correction in the same file already does, and its "
        "docstring says why")
    src = TOOL.read_text(encoding="utf-8")
    assert "_skr.asymptotic_skr_per_pulse(" in src
    assert "_skr.skr_finite(" in src


def test_both_halves_delegate_to_the_same_module():
    """Half-delegation is what produced this defect in the first place."""
    src = TOOL.read_text(encoding="utf-8")
    body = src[src.index("def asymptotic_skr_per_pulse"):]
    body = body[:body.index("\ndef precompute")]
    assert "math.exp" not in body, (
        "the asymptotic path is computing again rather than delegating; "
        "an inlined exponential is how the local model grew back last time")


# --------------------------------------------------------------------------
# The delegation must agree with the module it delegates to.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("distance_km", [10.0, 50.0, 100.0])
@pytest.mark.parametrize("nu2", [0.0, 0.01, 0.05])
def test_the_builder_and_the_runtime_agree_exactly(distance_km, nu2):
    """Not "close" -- identical. They are now the same code path.

    nu2 > 0 is included deliberately: every case that hid the original
    divergence pinned nu2 = 0.0, where the wrong denominator happened to be
    right.
    """
    from app.backends import _skr

    m = _tool()
    p = m.PhysParams(distance_km=distance_km, eta_d=0.2, Y0=1e-6,
                     mu=0.5, nu1=0.1, nu2=nu2)
    direct = _skr.asymptotic_skr_per_pulse(
        Y0=p.Y0, eta_total=m.channel_transmittance(p), e_d=p.e_d,
        mu=p.mu, nu1=p.nu1, nu2=p.nu2, f_EC=p.f_EC,
    )
    assert m.asymptotic_skr_per_pulse(p) == direct


def test_a_valid_parameter_set_still_produces_a_rate():
    """Not vacuous: the tests above would pass on a function returning 0."""
    m = _tool()
    p = m.PhysParams(distance_km=50.0, eta_d=0.2, Y0=1e-6,
                     mu=0.5, nu1=0.1, nu2=0.0)
    assert m.asymptotic_skr_per_pulse(p) > 0.0


# --------------------------------------------------------------------------
# The shipped artefact must not have moved.
# --------------------------------------------------------------------------

def test_the_committed_table_is_what_this_builder_produces(tmp_path):
    """The delegation was verified as a no-op on the shipped data: 1170/1170.

    If this fails, the table in git and the model in the code disagree, and
    `config/qkd_keyrate_table.json` is shipped data -- /physics reads it.
    """
    committed = ROOT / "config" / "qkd_keyrate_table.json"
    if not committed.is_file():
        pytest.skip("no committed table to compare against")

    m = _tool()
    out = tmp_path / "regenerated.json"
    argv = sys.argv[:]
    sys.argv = ["precompute", "--out", str(out)]
    try:
        m.main()
    finally:
        sys.argv = argv

    a = json.loads(committed.read_text(encoding="utf-8"))
    b = json.loads(out.read_text(encoding="utf-8"))
    rows_a = a.get("rows", a)
    rows_b = b.get("rows", b)
    assert len(rows_a) == len(rows_b)
    differing = [i for i, (x, y) in enumerate(zip(rows_a, rows_b)) if x != y]
    assert not differing, (
        f"{len(differing)} of {len(rows_a)} committed rows differ from what the "
        f"builder now produces (first at index {differing[0]}). Either "
        f"regenerate the table or explain the model change.")
