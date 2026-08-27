"""Every key in config/qkd_params.yaml must be read by some code path.

That file opens by declaring itself

    "the SINGLE SOURCE OF TRUTH for every numeric value in the BB84-KME stack"

and

    "Hot-reload: the bb84-kme process watches this file; on change the new
     values take effect at the next BB84 round."

Seven leaf keys are read by nothing, so editing them takes effect at no round
ever. Enumerated by walking the YAML and searching every tracked CODE file
(.py/.ts/.tsx/.go/.sh/.yml) for either the dotted path or the leaf name as an
identifier:

    source.source_type
    hil.kms_url
    hil.ca_cert_file
    hil.client_cert_file
    hil.client_key_file
    webui.refresh_interval_ms
    webui.ws_frame_buffer

The `hil.*` group is the one that can mislead. docs/LIMITATIONS.md says a real
device "can be substituted by changing a single KMS_URL line", and HIL.tsx tells
you to `Set KMS_URL=https://<device>/api/v1/keys/<SAE_ID>`. That is an
ENVIRONMENT VARIABLE -- docker-compose.strongswan.yml sets it -- and it works.
`hil.kms_url` in the YAML is a second surface for the same idea that nothing
reads. An operator following the file that calls itself the single source of
truth would set the dead one.

Same shape as the seven `BB84_*` compose variables that
tests/test_compose_env_is_read_by_something.py exists for, on the other
configuration surface. That test covers compose env; nothing covered this file.

Two traps this guard has to avoid, both already paid for elsewhere here:

  * `git ls-files` lists submodule gitlinks as paths, so piping it into a
    recursive grep descends into submodules and reports dozens of upstream
    matches. Filter to real files outside submodules/.
  * a DOCS mention is not a reader. `source.basis_bias_pz` appears in
    docs/keyrate.md and is genuinely read in backends/base.py; searching prose
    as well would have called it live for the wrong reason, and would call a
    dead key live as soon as someone documents it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "qkd_params.yaml"
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".go", ".sh", ".yml", ".yaml", ".rs"}

# Keys with no reader, each of which must say WHY it is here. An unexplained
# entry is how a dead knob becomes permanent.
KNOWN_UNREAD: dict[str, str] = {
    "source.source_type": (
        "Descriptive label ('WCP') for the source model. Every backend assumes "
        "weak coherent pulses; there is no second value to switch to, so "
        "nothing branches on it."
    ),
    "hil.kms_url": (
        "Reserved for the Hardware-In-Loop lane, not wired. The LIVE knob is "
        "the KMS_URL environment variable (docker-compose.strongswan.yml), "
        "which is what HIL.tsx and docs/LIMITATIONS.md tell you to set."
    ),
    "hil.ca_cert_file": "Reserved for HIL mTLS; not wired. See hil.kms_url.",
    "hil.client_cert_file": "Reserved for HIL mTLS; not wired. See hil.kms_url.",
    "hil.client_key_file": "Reserved for HIL mTLS; not wired. See hil.kms_url.",
    "webui.refresh_interval_ms": (
        "The frontend polls on hardcoded intervals (3000 ms in Overview and "
        "VpnProtocols). It never fetches this file, so the value cannot reach "
        "it without a new endpoint."
    ),
    "webui.ws_frame_buffer": (
        "Sized a WebSocket frame buffer for the /ws fan-out that was removed "
        "in Round 5. Nothing has opened a WebSocket since; main.py's own "
        "comment records the removal."
    ),
}


def _leaves(node, prefix: str = ""):
    for key, value in (node or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _leaves(value, path + ".")
        else:
            yield path


def _code_bodies() -> dict[str, str]:
    out: dict[str, str] = {}
    listed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    for rel in listed:
        if rel.startswith("submodules/") or rel == "config/qkd_params.yaml":
            continue
        p = ROOT / rel
        # `is_file()` matters: gitlinks are listed as paths but are directories.
        if not p.is_file() or p.suffix not in CODE_SUFFIXES:
            continue
        try:
            out[rel] = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return out


def _readers(dotted: str, bodies: dict[str, str]) -> list[str]:
    """Files that read this key, by dotted path or by leaf identifier.

    Both forms count: config_loader exposes `cl.get("a.b.c")`, and
    `cfg_from_yaml` maps YAML keys onto BackendConfig fields whose names are
    the bare leaves.
    """
    leaf = dotted.rsplit(".", 1)[-1]
    pattern = re.compile(rf"\b{re.escape(leaf)}\b")
    return [rel for rel, body in bodies.items()
            if dotted in body or pattern.search(body)]


@pytest.fixture(scope="module")
def bodies() -> dict[str, str]:
    assert CONFIG.is_file(), f"{CONFIG} missing"
    return _code_bodies()


def test_no_new_config_key_is_unread(bodies):
    """The guard itself: anything dead must be listed and explained."""
    params = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    unread = [k for k in _leaves(params) if not _readers(k, bodies)]
    unexpected = sorted(set(unread) - set(KNOWN_UNREAD))
    assert not unexpected, (
        "these keys are in config/qkd_params.yaml and read by no code path, so "
        "editing them changes nothing -- in a file whose header calls itself "
        "the single source of truth and says changes take effect at the next "
        "round:\n  " + "\n  ".join(unexpected) +
        "\nEither wire them up, delete them, or add them to KNOWN_UNREAD with a "
        "reason. An unexplained entry is how a dead knob becomes permanent."
    )


def test_the_known_list_has_not_gone_stale(bodies):
    """The other direction: a key that got wired must leave the list.

    Without this the allowlist only ever grows, and a stale exemption is a
    place a genuinely dead key can hide.
    """
    params = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    present = set(_leaves(params))
    now_read = sorted(
        k for k in KNOWN_UNREAD if k in present and _readers(k, bodies)
    )
    assert not now_read, (
        "these are listed as unread but now have a reader; drop them from "
        "KNOWN_UNREAD:\n  " + "\n  ".join(now_read)
    )
    gone = sorted(k for k in KNOWN_UNREAD if k not in present)
    assert not gone, (
        "these are listed as unread but are no longer in the YAML at all:\n  "
        + "\n  ".join(gone)
    )


def test_every_exemption_states_a_reason():
    for key, reason in KNOWN_UNREAD.items():
        assert len(reason) > 40, f"{key}: the reason is too thin to be one"


def test_a_docs_mention_does_not_count_as_a_reader(bodies):
    """Guards the guard.

    `source.basis_bias_pz` appears in docs/keyrate.md AND is genuinely read in
    backends/base.py. Searching prose too would call it live for the wrong
    reason -- and would call a truly dead key live the moment someone wrote a
    sentence about it. Only code files are searched, and this pins that.
    """
    assert all(Path(rel).suffix in CODE_SUFFIXES for rel in bodies)
    assert not any(rel.startswith("docs/") and rel.endswith(".md") for rel in bodies)
    # And the specific key: readable from code, not merely from documentation.
    hits = _readers("source.basis_bias_pz", bodies)
    assert any(h.startswith("services/bb84-kme/") for h in hits), (
        "basis_bias_pz is no longer read by the backend; if that is deliberate "
        "it belongs in KNOWN_UNREAD"
    )
