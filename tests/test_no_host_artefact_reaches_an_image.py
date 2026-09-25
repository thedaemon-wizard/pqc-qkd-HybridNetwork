"""Every compose build context ignores the host artefacts that must not reach an image.

A host `__pycache__` copied by `COPY services/bb84-kme/app/ ./app/` made a
KME image run bytecode older than its source: the .pyc had the same size and
mtime second as the source file, so Python took it as current. And the
frontend's `COPY . .` ran after `npm install`, overwriting the image's
node_modules with the host's. Both are closed by a .dockerignore in the build
context; this checks each context compose builds from has one that does.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from test_compose_env_is_read_by_something import _ComposeLoader

REPO = Path(__file__).resolve().parents[1]


def _contexts() -> set[Path]:
    out = set()
    for f in list(REPO.glob("docker-compose*.yml")) + list((REPO / "deploy").glob("docker-compose*.yml")):
        services = (yaml.load(f.read_text(), Loader=_ComposeLoader) or {}).get("services") or {}
        for svc in services.values():
            build = (svc or {}).get("build")
            if isinstance(build, dict) and "context" in build:
                out.add((f.parent / build["context"]).resolve())
            elif isinstance(build, str):
                out.add((f.parent / build).resolve())
    return out


def _ignored(ctx: Path) -> set[str]:
    f = ctx / ".dockerignore"
    assert f.is_file(), f"{ctx.relative_to(REPO)} has no .dockerignore"
    return {ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")}


def test_there_are_contexts_to_check():
    assert REPO in _contexts()


def test_no_context_ships_host_bytecode_or_node_modules():
    for ctx in _contexts():
        ignored = _ignored(ctx)
        # Python sources of the project, not ones vendored inside node_modules.
        if any("node_modules" not in f.parts for f in ctx.rglob("*.py")):
            assert {"**/__pycache__", "**/*.py[co]"} <= ignored, ctx
        if (ctx / "package.json").is_file():
            assert "node_modules" in ignored or "**/node_modules" in ignored, ctx
