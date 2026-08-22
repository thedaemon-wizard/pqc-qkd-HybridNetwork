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
    "WG_QUICK_USERSPACE_IMPLEMENTATION": "wg-quick (confirmed in the node image)",
}

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
