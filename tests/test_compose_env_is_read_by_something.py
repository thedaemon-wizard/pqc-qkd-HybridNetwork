"""An environment variable a compose file sets must be read by something.

Seven `BB84_*` variables and an `ETSI_MTLS_ENABLED` were set on the KME
services, listed in `.env.example`, and documented in the README with a
"Source of truth" column naming a specific Python file for each. No Python file
read any of them. `config_loader.py` says in its own docstring that
`config/qkd_params.yaml` is the single source of truth and that any module
needing a numeric tunable must go through it -- so the variables were a second
configuration surface that was wired up on the outside and connected to nothing
on the inside.

The failure is worse than dead weight, because it is confidently documented.
A reader tuning `BB84_QBER_THRESHOLD` gets no error and no effect, and the
README tells them which file to look in. `/hil` had the same shape: it
instructed the operator to set `ETSI_MTLS_ENABLED=true` before attaching real
QKD hardware.

`config_loader.env_override()` existed for exactly this and had zero callers,
which is the clearest evidence the intent was abandoned rather than finished.

The check is deliberately broad in where it looks for a reader -- Python, Go,
shell, TypeScript, Dockerfiles, nginx and Caddy config -- because a variable
consumed by an entrypoint or by a third-party binary is legitimately read
outside the application code. It is the variables nothing anywhere mentions
that this catches.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

COMPOSE_FILES = sorted(ROOT.glob("docker-compose*.yml")) + sorted(
    (ROOT / "deploy").glob("docker-compose*.yml")
)

# Parsed from the YAML rather than by regex over lines. A first version matched
# any indented `NAME:` and so picked up `build.args.USE_BORINGTUN`, which is a
# build argument, not an environment variable -- a different mechanism with a
# different consumer. (That argument turned out to be dead too, but for its own
# reason: the Dockerfile never declares it.)
def _service_env(service: dict) -> list[str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return list(env)
    return [str(e).split("=", 1)[0] for e in env]


# Variables consumed by a third-party program rather than by this repository.
# Each entry names what reads it, because "something external reads it" is
# exactly the excuse that would otherwise let a dead variable back in.
EXTERNALLY_CONSUMED = {
    "OMP_NUM_THREADS": "OpenMP runtime, via numpy/qutip in bb84-kme",
    "OPENBLAS_CORETYPE": "OpenBLAS runtime, via numpy",
}
# WG_QUICK_USERSPACE_IMPLEMENTATION used to be exempted here as "wg-quick
# (confirmed in the node image)". Nothing in this repository ever invoked
# wg-quick -- `nodes/alice/entrypoint.sh` created the interface with a bare
# `ip link add ... type wireguard` -- so the variable was read by nothing and
# the exemption was the excuse that kept a dead variable alive. The entrypoint
# now reads it when the kernel module is missing, which makes it an ordinary
# in-tree consumer and needs no exemption at all.

# Where a reader could legitimately live. Entrypoints and third-party binaries
# count: ARNIKA_* is read by arnika itself, not by anything in this repo's
# Python.
READER_GLOBS = (
    "services/**/*.py", "services/**/*.ts", "services/**/*.tsx",
    "services/**/*.go", "services/**/*.conf", "services/**/Dockerfile*",
    "nodes/**/*", "scripts/*.sh", "benchmarks/*.sh", "tools/*.py",
    "deploy/*.sh", "deploy/Caddyfile", "Makefile", ".github/workflows/*.yml",
)


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Compose's own YAML tags.

    `deploy/docker-compose.cloud.yml` uses `!override` (and Compose also
    defines `!reset`). SafeLoader raises on them, which took the whole test
    module out at collection -- a guard that cannot be collected protects
    nothing, so this is handled rather than worked around by narrowing the
    file list.
    """


_ComposeLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: (
        loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
        else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
        else loader.construct_scalar(node)
    ),
)


def _compose_vars() -> dict[str, set[str]]:
    """var -> set of compose files that set it, from the parsed YAML."""
    found: dict[str, set[str]] = {}
    for f in COMPOSE_FILES:
        doc = yaml.load(f.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
        for svc in (doc.get("services") or {}).values():
            if not isinstance(svc, dict):
                continue
            for name in _service_env(svc):
                found.setdefault(name, set()).add(f.name)
    return found


def _corpus() -> str:
    parts = []
    for pattern in READER_GLOBS:
        for p in ROOT.glob(pattern):
            if p.is_file() and "node_modules" not in p.parts and "submodules" not in p.parts:
                try:
                    parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
    return "\n".join(parts)


CORPUS = _corpus()
# Raw text of every compose file, for the interpolation check above. Read as
# text rather than through the YAML loader on purpose: `${VAR}` is a string in
# the document, and the loader would give back the substituted value.
COMPOSE_TEXT = "\n".join(f.read_text(encoding="utf-8") for f in COMPOSE_FILES)
COMPOSE_VARS = _compose_vars()


def test_there_are_compose_variables_to_check():
    """Guard the guard: a glob or parser change must not silently empty this."""
    assert len(COMPOSE_VARS) > 20, (
        f"only {len(COMPOSE_VARS)} compose environment variables parsed; the "
        "extractor has stopped matching."
    )
    assert len(CORPUS) > 100_000, "reader corpus is suspiciously small"


@pytest.mark.parametrize("var", sorted(COMPOSE_VARS))
def test_something_reads_the_variable(var):
    if var in EXTERNALLY_CONSUMED:
        pytest.skip(f"{var}: read by {EXTERNALLY_CONSUMED[var]}")
    where = ", ".join(sorted(COMPOSE_VARS[var]))
    assert var in CORPUS, (
        f"{var} is set in {where} but appears nowhere in the code, entrypoints, "
        "scripts, Dockerfiles or CI. Either wire it up or delete it -- a "
        "documented knob that does nothing is worse than a missing one, because "
        "someone will set it and believe it took effect. This is what happened "
        "to seven BB84_* variables and ETSI_MTLS_ENABLED."
    )


def test_the_abandoned_override_hook_is_gone():
    """`env_override()` was the mechanism that would have made them real.

    Zero callers, while the README documented the variables as live. Keeping a
    plausible hook around invites someone to conclude the wiring exists.
    """
    loader = ROOT / "services" / "bb84-kme" / "app" / "config_loader.py"
    src = loader.read_text(encoding="utf-8")
    assert "def env_override" not in src, (
        "config_loader.env_override() is back. If it has real callers now, "
        "delete this assertion; if it does not, it is the same trap again."
    )


def test_the_yaml_is_still_the_declared_single_source():
    """The reason the variables were removed rather than wired up."""
    loader = ROOT / "services" / "bb84-kme" / "app" / "config_loader.py"
    src = loader.read_text(encoding="utf-8").lower()
    assert "single source of truth" in src and "qkd_params.yaml" in src, (
        "config_loader.py no longer declares qkd_params.yaml the single source "
        "of truth. If that decision changed, the BB84_* variables may belong "
        "again -- but then they need readers, and this test needs rewriting."
    )


# ---------------------------------------------------------------------------
# Orphans that live ONLY in an example file.
#
# Everything above enumerates variables SET IN a compose file, so a variable
# that appears only in `.env.example` or `deploy/.env.example` is outside this
# module's reach by construction. That gap was real: `deploy/.env.example`
# carried a "BB84-KME tuning" block of five variables --
#
#     BB84_BATCH, BB84_CHANNEL_NOISE, BB84_QBER_THRESHOLD,
#     BB84_POOL_LOW, BB84_POOL_MAX
#
# -- that appeared in no compose file and in no Python source. `deploy/README.md`
# tells operators to copy that file, so the offer was to tune five values and
# observe nothing. The real knobs are in `config/qkd_params.yaml`.
#
# An example file is a promise about the runtime, exactly like a compose
# variable, so it gets the same check.
# ---------------------------------------------------------------------------

EXAMPLE_FILES = [p for p in (ROOT / ".env.example", ROOT / "deploy" / ".env.example")
                 if p.is_file()]


def _example_vars() -> dict[str, set[str]]:
    """`NAME=value` assignments in the example files, ignoring comments."""
    out: dict[str, set[str]] = {}
    for f in EXAMPLE_FILES:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
            if m:
                out.setdefault(m.group(1), set()).add(
                    str(f.relative_to(ROOT)))
    return out


# Consumed by `docker compose` itself rather than by anything in this tree, so
# "nothing reads it" is true of the repository and false of the runtime. Kept
# as an explicit list of one, not a pattern, so a second entry needs a reason.
COMPOSE_BUILTINS = {"COMPOSE_PROJECT_NAME"}

EXAMPLE_VARS = _example_vars()


def test_there_are_example_variables_to_check():
    # Without this the parametrisation below can silently collapse to nothing.
    assert len(EXAMPLE_VARS) >= 5, (
        f"only {len(EXAMPLE_VARS)} variables parsed from {EXAMPLE_FILES}"
    )


@pytest.mark.parametrize("var", sorted(EXAMPLE_VARS))
def test_every_example_variable_is_read_somewhere(var):
    """An example file must not offer a knob nothing turns.

    Reading counts if a compose file interpolates it OR any source file
    mentions it -- the same corpus the compose check uses.
    """
    if var in COMPOSE_VARS:
        return  # already covered, and covered more strictly, above
    # Interpolation counts as reading. `_compose_vars()` collects the KEYS set
    # in a service `environment:` block, so a variable used only as
    # `${WG_ALICE_IP:-10.0.0.1}` on the VALUE side is invisible to it. The first
    # version of this check omitted COMPOSE_TEXT and reported twelve orphans,
    # eleven of which were interpolations -- WG_*, ARNIKA_ID_*, WEBUI_*_PORT and
    # COMPOSE_PROJECT_NAME are all genuinely consumed that way.
    if var in COMPOSE_BUILTINS:
        return
    assert var in CORPUS or var in COMPOSE_TEXT, (
        f"{var} is offered in {sorted(EXAMPLE_VARS[var])} but is read by "
        f"nothing: it appears in no docker-compose*.yml and nowhere in the "
        f"source corpus. Either wire it up or delete it -- an operator who "
        f"edits it will see no effect."
    )


def test_the_removed_bb84_block_stays_removed():
    """Named explicitly, because it is the case that motivated the check."""
    for f in EXAMPLE_FILES:
        text = f.read_text(encoding="utf-8")
        for var in ("BB84_BATCH", "BB84_CHANNEL_NOISE", "BB84_QBER_THRESHOLD",
                    "BB84_POOL_LOW", "BB84_POOL_MAX"):
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#"):
                    continue    # the retraction note quotes the names on purpose
                assert not s.startswith(f"{var}="), (
                    f"{f.relative_to(ROOT)} offers {var} again; nothing reads it"
                )
