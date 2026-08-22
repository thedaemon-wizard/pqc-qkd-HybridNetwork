"""The frontend's offline defaults must equal `config/qkd_params.yaml`.

That file opens by declaring itself "the SINGLE SOURCE OF TRUTH for every
numeric value", and `tests/test_no_hardcoded_params.py` enforces it -- but only
for `services/bb84-kme/app/backends/`. Nothing looked at the frontend, and the
frontend kept its own copy.

The copy drifted:

    link_length_km   config 10.0    BB84.tsx 25      2.5x
    pulse_rate_hz    config 1.0e9   BB84.tsx 1e7     100x

`/bb84` reads `/api/sim/params` at mount and falls back to those literals when
the backend is absent. Static hosting is a deployment mode the project actively
recommends (`docs/deployment-economics.md`), so the offline path is a normal way
to view the page -- and on it, `/bb84` was simulating a different physical link
from every other component, with no indication that it had.

Two copies of a constant stay in step only if something checks. This is that
check. It parses the literals rather than importing them, because the backend
test suite cannot execute TypeScript.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "qkd_params.yaml"
# The literal moved out of BB84.tsx into lib/sim/keyrate.ts as BUNDLED_PARAMS,
# because two engines carried their own conflicting copies. This test follows
# the definition rather than the page: it is the single source that has to
# agree with the YAML, and the engines derive from it.
BUNDLED = ROOT / "services" / "webui-frontend" / "src" / "lib" / "sim" / "keyrate.ts"
# The page is a separate concern: keyrate.ts owns the fallback VALUES, BB84.tsx
# owns actually asking the backend first. Checking both against the same file
# would let either half rot silently.
BB84_PAGE = ROOT / "services" / "webui-frontend" / "src" / "pages" / "BB84.tsx"

# camelCase name in BUNDLED_PARAMS -> dotted path in qkd_params.yaml
MAPPING = {
    "detectorEfficiency": "physical.detector_efficiency",
    "fiberAttenuationDbPerKm": "physical.fiber_attenuation_db_per_km",
    "linkLengthKm": "physical.link_length_km",
    "darkCountRateHz": "physical.dark_count_rate_hz",
    "misalignmentErrorEd": "physical.misalignment_error_ed",
    "pulseRateHz": "source.pulse_rate_hz",
    "qberThresholdAbort": "protocol.qber_threshold_abort",
}


def _config_value(dotted: str):
    node = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for part in dotted.split("."):
        node = node[part]
    return float(node)


def _frontend_defaults() -> dict[str, float]:
    """Parse the `BUNDLED_PARAMS` object literal out of keyrate.ts."""
    src = BUNDLED.read_text(encoding="utf-8")
    m = re.search(r"export const BUNDLED_PARAMS\s*=\s*\{(.*?)\n\}\s*as const;", src, re.S)
    assert m, "DEFAULT_PARAMS literal not found in BB84.tsx -- has it been renamed?"

    body = re.sub(r"//[^\n]*", "", m.group(1))          # strip trailing comments
    out: dict[str, float] = {}
    for key, raw in re.findall(r"(\w+)\s*:\s*([0-9eE.+-]+)\s*,", body):
        out[key] = float(raw)
    assert out, "no numeric entries parsed from DEFAULT_PARAMS"
    return out


def test_every_frontend_default_is_mapped():
    """A new default must be added to MAPPING, not silently unchecked."""
    unmapped = set(_frontend_defaults()) - set(MAPPING)
    assert not unmapped, (
        f"BB84.tsx defaults with no config counterpart: {sorted(unmapped)}. "
        "Either map them to a qkd_params.yaml key or justify them here."
    )


@pytest.mark.parametrize("name,dotted", sorted(MAPPING.items()))
def test_frontend_default_equals_the_configured_value(name, dotted):
    defaults = _frontend_defaults()
    if name not in defaults:
        pytest.skip(f"{name} is not among BB84.tsx defaults")
    assert defaults[name] == pytest.approx(_config_value(dotted), rel=1e-12), (
        f"BB84.tsx {name}={defaults[name]!r} but {CONFIG.name} "
        f"{dotted}={_config_value(dotted)!r}. The offline path would simulate a "
        f"different system from the configured one."
    )


def test_the_page_reads_the_backend_before_falling_back():
    """The literals are a fallback, not the primary source.

    If the fetch were removed the values would be correct but frozen, which is
    the same defect one step later.
    """
    src = BB84_PAGE.read_text(encoding="utf-8")
    assert "/api/sim/params" in src, "BB84.tsx no longer asks the backend at all"
    for dotted in MAPPING.values():
        leaf = dotted.split(".")[-1]
        assert leaf in src, f"BB84.tsx never reads {leaf} from the API response"


def test_config_declares_itself_the_single_source_of_truth():
    """Pin the premise, so the rule and the check cannot drift apart."""
    head = CONFIG.read_text(encoding="utf-8")[:600].upper()
    assert "SINGLE SOURCE OF TRUTH" in head, (
        "qkd_params.yaml no longer claims to be the single source of truth; "
        f"if that changed deliberately, this test and {BUNDLED.name} need revisiting"
    )


def test_mapping_paths_all_resolve():
    """A typo in MAPPING would make a test vacuously pass."""
    for dotted in MAPPING.values():
        assert isinstance(_config_value(dotted), float), dotted
    # Guard against the mapping silently shrinking to nothing.
    assert len(MAPPING) >= 7, json.dumps(MAPPING, indent=1)
