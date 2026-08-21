"""Every shell-level default for a VICI variable must be documented.

`services/arnika-vici/README.md` stated flatly: "All variables are mandatory.
There are no defaults, because every plausible default silently masks a
misconfiguration that still looks like a working tunnel."

That is true of the Go adapter -- `getKeyWriterService` errors on an unset
`VICI_REAUTH_TIMEOUT` or `VICI_IKE_ROLE`, and `ViciConfig` documents every field
as required. It was not true of the shipped deployment, which supplies
`${VAR:-default}` for three of those variables in the entrypoint and the compose
file. An operator who read the README, omitted `VICI_REAUTH_TIMEOUT` from their
own compose file and expected an error would instead silently get 10 s -- the
exact failure mode the sentence claims to prevent.

The two layers drifted because nothing connected them. This connects them: a
new default in the shell layer fails until the README accounts for it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "services" / "arnika-vici" / "README.md"
SHELL_SOURCES = [
    ROOT / "nodes" / "strongswan" / "entrypoint.sh",
    ROOT / "docker-compose.strongswan.yml",
]

# `${NAME:-value}` where NAME looks like part of the VICI/strongSwan surface.
DEFAULT = re.compile(r"\$\{(?P<name>[A-Z][A-Z0-9_]*)\s*:-(?P<value>[^}]*)\}")
RELEVANT = re.compile(r"^(VICI_|REAUTH_|WIREGUARD_)")


def _shell_defaults() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in SHELL_SOURCES:
        if not path.is_file():
            continue
        for m in DEFAULT.finditer(path.read_text(encoding="utf-8")):
            name = m.group("name")
            if RELEVANT.match(name):
                found.setdefault(name, m.group("value"))
    return found


def test_the_shell_layer_still_has_defaults_worth_documenting():
    """Guard the guard: if these disappear, this file should be revisited."""
    defaults = _shell_defaults()
    assert defaults, (
        "no ${VAR:-default} found for any VICI/REAUTH/WIREGUARD variable. If the "
        "deployment genuinely stopped defaulting them, the README may now say "
        "'there are no defaults' without qualification -- and this test can go."
    )


@pytest.mark.parametrize("name", sorted(_shell_defaults()))
def test_each_shell_default_is_named_in_the_readme(name):
    text = README.read_text(encoding="utf-8")
    assert name in text, (
        f"{name} is given a default in the shell/compose layer but is not "
        f"mentioned in {README.relative_to(ROOT)}. Either document it or remove "
        f"the default; leaving both is how the 'no defaults' claim became untrue."
    )


def test_the_readme_does_not_claim_defaults_are_absent_without_qualifying_it():
    """The unqualified sentence is the thing that was wrong.

    Matched loosely on purpose: any rewording that still asserts a bare absence
    of defaults, while the table above shows three, should fail here.
    """
    text = README.read_text(encoding="utf-8")
    bare = re.search(
        r"There are no defaults[.,]", text, re.IGNORECASE,
    )
    assert not bare, (
        "README asserts 'There are no defaults.' without qualification, but "
        f"the shell layer defines: {sorted(_shell_defaults())}. Say where the "
        "requirement holds (the adapter) and where it does not (the deployment)."
    )


def test_the_adapter_really_does_reject_unset_values():
    """The half of the claim that IS true must stay true.

    If the adapter ever gains its own default, the README's distinction between
    adapter and deployment collapses and the whole section needs rewriting.
    """
    src = (ROOT / "services" / "arnika-vici" / "strongswanvici.go").read_text(encoding="utf-8")
    assert 'must be set' in src, "the adapter no longer errors on unset configuration"
    # The two it checks explicitly, by name.
    assert "VICI_REAUTH_TIMEOUT" in src
    assert "VICI_IKE_ROLE" in src
