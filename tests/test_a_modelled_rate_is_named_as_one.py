"""The headline key rate is a prediction. Its name and payload must say so.

`/sim/stats` reported `last_skr_bps` in the middle of the `last_*` group,
between `last_qber` and `intercepted_total` -- both of which are genuinely
measured per round. It is not. Every backend fills `RoundOutcome.skr_bps` from
`skr_bps_from_config(cfg)`, and that function's signature is

    skr_bps_from_config(cfg) -> float

There is no round argument. It cannot depend on a round, so no run can move it.

Measured on the public demo, 2026-08-27:

    alice   rounds_total=6       last_skr_bps=12072051.175288066
    bob     rounds_total=12126   last_skr_bps=12072051.175288066

Bit-identical across a 2000x difference in rounds, and equal to what the config
alone predicts with no simulator running at all -- while `last_qber` (0.0098 vs
0.0) and `last_round_ms` (220.8 vs 300.3) differed on the same request, because
those are measurements. The `last_` prefix and the company it kept asserted a
provenance the number does not have, and docs/roadmap.md went on to call it
"an actual 12.07 Mbps".

The rate itself is correct and worth reporting: it is the right thing to
compare a backend against, which is what tests/test_skr_is_not_a_sifting_ratio.py
already checks. Only the claim about where it came from was wrong.

These tests are about NAMING and PROVENANCE, deliberately separate from that
file, which is about the value. Both can be right while the other is wrong.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import fields

from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
keypool = importlib.import_module("bb84_kme_app.keypool")
_skr = importlib.import_module("bb84_kme_app.backends._skr")
base = importlib.import_module("bb84_kme_app.backends.base")


def test_the_modelled_rate_is_not_named_like_a_measurement():
    names = {f.name for f in fields(keypool.PoolStats)}
    assert "modelled_skr_bps" in names, (
        "PoolStats has no `modelled_skr_bps`. The field carrying the "
        "closed-form rate must not be named like a per-round measurement."
    )
    assert "last_skr_bps" not in names, (
        "`last_skr_bps` is back. It sits among genuinely measured `last_*` "
        "fields while being a pure function of config -- that adjacency is the "
        "whole defect. Renaming, not aliasing: a synonym preserves the claim."
    )


def test_the_payload_states_its_provenance():
    """The field name is not the only place a JSON consumer looks."""
    names = {f.name for f in fields(keypool.PoolStats)}
    assert "skr_provenance" in names
    default = keypool.PoolStats().skr_provenance
    assert "closed-form" in default and "not measured" in default, (
        f"skr_provenance reads {default!r}; it must say the value is predicted "
        "from configuration rather than measured per round"
    )


def test_the_function_behind_it_takes_no_round():
    """The structural fact the naming has to match.

    Derived from the signature rather than asserted in prose, so a future
    version that DOES incorporate the round breaks this test and invites the
    name to change back.
    """
    sig = inspect.signature(_skr.skr_bps_from_config)
    assert list(sig.parameters) == ["cfg"], (
        f"skr_bps_from_config now takes {list(sig.parameters)}. If it consumes "
        "round data, it is no longer purely modelled and `modelled_skr_bps` "
        "should be revisited -- do not just widen this assertion."
    )


def test_two_different_round_counts_cannot_change_it():
    """The demo observation, reproduced offline.

    Feeding the same config twice must give the identical float; that is what
    made two nodes 2000 rounds apart agree to the last bit.
    """
    # config_loader captures CONFIG_PATH at IMPORT time from QKD_PARAMS_FILE,
    # defaulting to /etc/pqcqkd/qkd_params.yaml -- which does not exist here, so
    # a bare reload() silently yields empty defaults and cfg_from_yaml() then
    # raises on a missing key. Point it at the shipped file explicitly rather
    # than relying on import order; an env var set after import does nothing.
    cl = importlib.import_module("bb84_kme_app.config_loader")
    from pathlib import Path
    repo_cfg = Path(__file__).resolve().parents[1] / "config" / "qkd_params.yaml"
    cl.CONFIG_PATH = repo_cfg
    cl.reload()
    cfg = base.cfg_from_yaml()
    a = _skr.skr_bps_from_config(cfg)
    b = _skr.skr_bps_from_config(cfg)
    assert a == b, "not even deterministic in config, which is a different bug"
    assert a > 0.0

    # ...and it DOES move when the physics moves, so it is not merely a
    # constant. Distance is the cleanest lever.
    from dataclasses import replace
    near = _skr.skr_bps_from_config(replace(cfg, link_length_km=10.0))
    far = _skr.skr_bps_from_config(replace(cfg, link_length_km=80.0))
    assert far < near, (
        "the modelled rate does not fall with distance, so it is not tracking "
        "the model either"
    )


def test_the_round_outcome_does_not_call_it_estimated():
    """`estimated` reads as "measured, with error bars"; it is predicted."""
    src = inspect.getsource(base)
    decl = next(line for line in src.splitlines()
                if line.strip().startswith("skr_bps: float"))
    # The DECLARATION line only. A window of surrounding prose caught this
    # test's own explanatory comment, which quotes the wrong phrase in order to
    # say what was wrong -- the same self-quotation trap that has now caught
    # four guards here (depolarizing_rate, logService, the paper citation, and
    # the secret scanner's fixtures).
    assert "estimated secret-key rate" not in decl, (
        f"RoundOutcome.skr_bps is declared as {decl.strip()!r}. It is computed "
        "from configuration alone, so 'predicted'/'closed-form' is the honest "
        "word -- 'estimated' implies a measurement carrying uncertainty."
    )
    idx = src.index(decl)
    window = src[max(0, idx - 900):idx]
    assert "no round argument" in window, (
        "the comment above RoundOutcome.skr_bps no longer says where the "
        "number comes from"
    )
