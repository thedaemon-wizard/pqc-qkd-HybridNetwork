"""Shared pytest setup.

`services/webui-backend/app/main.py` and `services/bb84-kme/app/main.py`
configure rotating file logging at import time, defaulting to /var/log/pqcqkd
(see services/*/app/logging_setup.py). That path is correct inside the
containers and unwritable everywhere else, so importing those modules from a
test run on the host raises PermissionError before a single test executes.

Point LOG_DIR at a temporary directory for the whole session so backend modules
are importable outside Docker. This is test scaffolding only -- the production
default is deliberately left alone.
"""

from __future__ import annotations

import os
import tempfile

# Must run before any test module imports a service package.
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="pqcqkd-test-logs-"))
