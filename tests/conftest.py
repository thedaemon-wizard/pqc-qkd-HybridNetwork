"""Shared pytest setup.

Two things make the service packages awkward to import from a host test run,
and both are handled here rather than worked around in each test module.

1. Log directory. `services/*/app/logging_setup.py` configures rotating file
   logging at import time, defaulting to /var/log/pqcqkd. That path is correct
   inside the containers and unwritable everywhere else, so importing a service
   module on the host raises PermissionError before any test runs.

2. Package-name collision. `services/webui-backend/app` and
   `services/bb84-kme/app` are BOTH top-level packages named `app`. Appending
   both service directories to sys.path means whichever is imported first wins
   and is cached in sys.modules, so the second import silently returns the
   wrong module -- which surfaces as a confusing ImportError for a symbol that
   plainly exists. `load_service_app` imports each under a unique alias
   instead.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import tempfile
import types
from pathlib import Path

# Must run before any test module imports a service package.
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="pqcqkd-test-logs-"))

REPO_ROOT = Path(__file__).resolve().parents[1]

# The KME reads the ETSI GS QKD 004 spec from this path and has no fallback;
# the Dockerfile sets it in the image, this sets it for host runs.
os.environ.setdefault(
    "ETSI004_SPEC_FILE",
    str(REPO_ROOT / "services/webui-frontend/src/lib/sim/etsi004SpecV211.json"))


def load_service_app(service: str, alias: str) -> types.ModuleType:
    """Import ``services/<service>/app`` as a top-level package named ``alias``.

    Returns the package; submodules are then reachable with
    ``importlib.import_module(f"{alias}.main")``.
    """
    if alias in sys.modules:
        return sys.modules[alias]

    pkg_dir = REPO_ROOT / "services" / service / "app"
    if not pkg_dir.is_dir():
        raise RuntimeError(f"no app package at {pkg_dir}")

    spec = importlib.util.spec_from_file_location(
        alias,
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot build import spec for {pkg_dir}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)

    # Some service modules import third-party deps that live beside the app
    # package (e.g. requirements installed into the service dir).
    service_root = str(REPO_ROOT / "services" / service)
    if service_root not in sys.path:
        sys.path.insert(0, service_root)
    return module


# --- stack-status, assembled as its image assembles it ----------------------
#
# services/stack-status/Dockerfile copies webui-backend's app/stack_contract.py
# into the stack-status package under the same name, so the two services import
# one file. The tree holds no second copy, so the package is not importable as
# it stands; this registers the backend's file at the place the image puts it
# before anything imports the package's main module.

STACK_CONTRACT = REPO_ROOT / "services" / "webui-backend" / "app" / "stack_contract.py"


def load_stack_status_main() -> types.ModuleType:
    """``services/stack-status/app/main.py``, with the contract where the image puts it.

    Needs the Docker SDK, as the service does: callers importorskip("docker").
    """
    package = load_service_app("stack-status", "stack_status_app")
    name = "stack_status_app.stack_contract"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, STACK_CONTRACT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot build import spec for {STACK_CONTRACT}")
        contract = importlib.util.module_from_spec(spec)
        sys.modules[name] = contract
        spec.loader.exec_module(contract)
        package.stack_contract = contract
    return importlib.import_module("stack_status_app.main")


def stack_status_client(docker_client: object):
    """An httpx.Client whose requests stack-status's own handler answers.

    `docker_client` stands in for the Docker SDK client the service would
    create. Nothing leaves the process: each request goes to
    StackStatus.handle, the function the service's HTTP server calls, so a
    webui-backend test that sets `app.state.stack_status` to this exercises
    both services' code, from the fake Docker to the public response.
    """
    import httpx

    api = load_stack_status_main().StackStatus(lambda: docker_client)

    def answer(request: httpx.Request) -> httpx.Response:
        status, body, headers = api.handle(request.method, request.url.raw_path.decode("ascii"))
        return httpx.Response(status, json=body, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(answer), base_url="http://stack-status.test")


def stack_status_replying(reply):
    """An httpx.Client standing in for stack-status, answering with `reply(request)`.

    For tests of what webui-backend does with a reply stack-status itself
    would never send -- unredacted output, a refusal, a garbled body -- so
    that the backend's own layer is what is tested. `reply` returns an
    httpx.Response, or raises an httpx error to simulate no answer at all.
    """
    import httpx

    return httpx.Client(transport=httpx.MockTransport(reply), base_url="http://stack-status.test")


# --- Compose files, read the way `docker compose -f a -f b` reads them -------
#
# Shared by the tests that hold the deployment to a contract across services
# (the arnika settings of every peer pair, the two WireGuard tunnels of a node).
# pyyaml is imported inside the helpers, not at module level: this conftest is
# loaded by every job that runs pytest, and some of those install pytest only.

def _compose_yaml():
    import yaml

    class ComposeLoader(yaml.SafeLoader):
        """SafeLoader that tolerates Compose's own `!override` and `!reset` tags."""

    ComposeLoader.add_multi_constructor(
        "!", lambda loader, suffix, node: (
            loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
            else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
            else loader.construct_scalar(node)
        ),
    )
    return yaml, ComposeLoader


def load_compose(path: Path) -> dict:
    """One compose file, parsed; anchors and `<<` merges resolved by YAML."""
    yaml, loader = _compose_yaml()
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}


def compose_env(service: dict) -> dict:
    """A service's environment as a mapping, from either compose spelling."""
    env = service.get("environment") or {}
    if isinstance(env, list):
        out = {}
        for entry in env:
            key, sep, value = str(entry).partition("=")
            out[key] = value if sep else None
        return out
    return dict(env)


def compose_services(files: list[Path]) -> dict[str, dict]:
    """name -> {"env": ..., "service": ...}, merged over `files` in order.

    Later files update earlier ones key by key, as compose merges overrides for
    mappings. Lists (volumes, cap_add) are taken from the last file that sets
    them, which is enough for the checks here: none of them looks at a list an
    override extends.
    """
    out: dict[str, dict] = {}
    for path in files:
        for name, svc in (load_compose(path).get("services") or {}).items():
            if not isinstance(svc, dict):
                continue
            slot = out.setdefault(name, {"env": {}, "service": {}})
            slot["env"].update(compose_env(svc))
            slot["service"].update({k: v for k, v in svc.items() if k != "environment"})
    return out


_COMPOSE_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}")


def compose_resolve(value, mapping: dict[str, str]):
    """Compose's interpolation of one value against an env-file mapping.

    `${X:-d}` and `${X-d}` fall back to d, `${X:?msg}` and a bare `${X}` that
    the mapping does not set come back as `<unset X>` so an assertion names it,
    and `$$` is a literal dollar. Non-strings pass through unchanged.
    """
    if not isinstance(value, str):
        return value

    def sub(m: re.Match) -> str:
        name, op, arg = m.group(1), m.group(2), m.group(3)
        colon = (op or "").startswith(":")
        if name in mapping and (mapping[name] != "" or not colon):
            return mapping[name]
        if op in (":-", "-"):
            return arg
        return f"<unset {name}>"

    return _COMPOSE_INTERPOLATION.sub(sub, value.replace("$$", "\0")).replace("\0", "$")


def read_env_example(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of an example env file, comments and blanks skipped."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out
