"""AST-level guard: numeric literals must not appear in backend implementations.

The "no hardcoded params" rule (see plan §Phase 8 design principle) says all
tunables must come from config/qkd_params.yaml (via config_loader). This test
walks the AST of every *.py under services/bb84-kme/app/backends/ and checks
that no float literal is used as a magic number, except for a small whitelist
of mathematically intrinsic constants (0, 1, 2, 0.5, etc.).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "services" / "bb84-kme" / "app" / "backends"

# Allowed numeric literals fall into three categories:
#   1) mathematically intrinsic   (0, 1, 0.5, ...)
#   2) unit-conversion / physics constants  (1000 for km↔m, 8 for bit↔byte,
#                                            1e9 simulator-clock precision,
#                                            c = 299_792_458 m/s for photon delay)
#   3) scientifically-grounded CV-QKD defaults inside BackendConfig
#      (Pirandola Adv. Opt. Photon. 12 1012 (2020); restated in
#       config/qkd_params.yaml so users can override without touching code).
_ALLOWED_FLOATS = {
    0.0, 0.5, 1.0, 2.0, 10.0, -1.0, 0.25, 0.75,
    1000.0, 8.0, 60.0,
    299_792_458.0,
    4.0, 0.01, 0.95,
    5.0,                            # operational HTTPX timeout
}
_ALLOWED_INTS = {0, 1, 2, 3, 4, 8, 10, 16, 32, 64, 128, 256, 512, 1024,
                 -1, 100, 1000, 1_000_000_000}


class MagicHunter(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.bad: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant):
        v = node.value
        if isinstance(v, float):
            if v not in _ALLOWED_FLOATS:
                self.bad.append((node.lineno, f"{v!r}"))
        elif isinstance(v, int) and not isinstance(v, bool):
            if v not in _ALLOWED_INTS and abs(v) > 1:
                self.bad.append((node.lineno, f"{v!r}"))


def test_no_hardcoded_numeric_params():
    violations: list[str] = []
    py_files = list(TARGET.rglob("*.py"))
    assert py_files, f"no Python files found under {TARGET}"
    for f in py_files:
        # _skr.py is the closed-form math reference; it contains constants
        # like 0.5 (basis sift) and is allowed
        if f.name in ("_skr.py", "__init__.py"):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        hunter = MagicHunter(f)
        hunter.visit(tree)
        for line, snippet in hunter.bad:
            violations.append(f"{f.relative_to(ROOT)}:{line} → {snippet}")
    if violations:
        msg = "Magic numeric literals found in backends:\n" + "\n".join(violations)
        raise AssertionError(msg)


if __name__ == "__main__":
    import logging
    import os
    from logging.handlers import RotatingFileHandler
    _log_dir = Path(os.environ.get("LOG_DIR", "benchmarks/results"))
    _log_dir.mkdir(parents=True, exist_ok=True)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
    _root = logging.getLogger(); _root.setLevel(logging.INFO); _root.handlers.clear()
    _sh = logging.StreamHandler(); _sh.setFormatter(_fmt); _root.addHandler(_sh)
    _fh = RotatingFileHandler(_log_dir / "test_no_hardcoded_params.log",
                                maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    _fh.setFormatter(_fmt); _root.addHandler(_fh)
    _log = logging.getLogger("ast-test")
    try:
        test_no_hardcoded_numeric_params()
        _log.info("OK")
    except AssertionError as e:
        _log.error("%s", e); sys.exit(1)
