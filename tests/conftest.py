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
import sys
import tempfile
import types
from pathlib import Path

# Must run before any test module imports a service package.
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="pqcqkd-test-logs-"))

REPO_ROOT = Path(__file__).resolve().parents[1]


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
