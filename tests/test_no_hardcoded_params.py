"""AST-level guard: numeric literals must not appear in backend implementations.

SCOPE, STATED HONESTLY. This walks `services/bb84-kme/app/backends/` only. The
"no hardcoded params" rule was written to cover `app/`, and this docstring used
to claim "all tunables must come from config/qkd_params.yaml" -- which reads as
a repository-wide guarantee it does not provide. `README.md` cites this test as
what enforces the rule, so the overstatement travelled.

The gap is concrete and was worth checking rather than assuming. Three of the
literals the rule was written against still exist verbatim, outside the scanned
tree, in `app/bb84/simulator.py`:

    n_photons: int = 2048
    channel_noise: float = 0.01
    qber_threshold: float = 0.11

They are DEAD DEFAULTS. `RoundConfig` has exactly one construction site in the
whole application -- `backends/qutip_backend.py` -- and it passes every field
explicitly from the YAML config, so those values are never the ones used. That
is why this file does not simply widen its scan: flagging them would be a false
positive, and deleting the defaults would break the dataclass.

What was actually missing is a check that they STAY dead, which the second
class below now provides. Widening the AST scan to `app/` is still worth doing;
it needs a review of every literal in `simulator.py` and `keypool.py` first,
and is deliberately not bundled with a documentation fix.
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


# ---------------------------------------------------------------------------
# The dead defaults must stay dead.
#
# `RoundConfig` in app/bb84/simulator.py carries literal defaults for exactly
# the values the no-hardcoding rule exists to prevent. They are harmless only
# because the single construction site supplies all of them from YAML. Nothing
# enforced that: adding a seventh field, or dropping one argument at the call
# site, would silently reintroduce a hardcoded physics parameter -- and the AST
# scan above cannot see it, because simulator.py is outside its tree.
# ---------------------------------------------------------------------------

SIMULATOR = ROOT / "services" / "bb84-kme" / "app" / "bb84" / "simulator.py"
QUTIP = TARGET / "qutip_backend.py"


def _roundconfig_fields() -> list[str]:
    tree = ast.parse(SIMULATOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RoundConfig":
            return [s.target.id for s in node.body
                    if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
    raise AssertionError("RoundConfig not found in simulator.py")


def _construction_sites() -> list[ast.Call]:
    tree = ast.parse(QUTIP.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "RoundConfig"]


def test_roundconfig_has_exactly_one_construction_site():
    """If a second appears, the argument below must be checked there too."""
    sites = _construction_sites()
    assert len(sites) == 1, (
        f"{len(sites)} RoundConfig(...) calls in qutip_backend.py; this guard "
        f"only inspects it because there has always been exactly one"
    )
    # And nowhere else in the application.
    others = [p for p in (ROOT / "services" / "bb84-kme" / "app").rglob("*.py")
              if p not in (SIMULATOR, QUTIP)
              and "RoundConfig(" in p.read_text(encoding="utf-8")]
    assert not others, f"RoundConfig is constructed elsewhere too: {others}"


def test_every_defaulted_field_is_supplied_explicitly():
    """The defaults must be unreachable, not merely usually overridden."""
    fields = _roundconfig_fields()
    assert len(fields) >= 6, f"RoundConfig shrank unexpectedly: {fields}"
    supplied = {kw.arg for kw in _construction_sites()[0].keywords if kw.arg}
    missing = sorted(set(fields) - supplied)
    assert not missing, (
        f"qutip_backend.py falls back to RoundConfig's literal defaults for "
        f"{missing}. Those defaults are hardcoded physics parameters "
        f"(n_photons=2048, channel_noise=0.01, qber_threshold=0.11) that the "
        f"no-hardcoding rule exists to prevent, and the AST scan above cannot "
        f"see them because simulator.py is outside its tree. Pass them from "
        f"config_loader like the others."
    )


def test_those_values_come_from_config_not_from_more_literals():
    """Supplying them explicitly is no good if the call site inlines numbers."""
    site = _construction_sites()[0]
    literal_args = [
        kw.arg for kw in site.keywords
        if kw.arg and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, (int, float))
        and not isinstance(kw.value.value, bool)
    ]
    assert not literal_args, (
        f"RoundConfig(...) is passed numeric literals for {literal_args}; the "
        f"value moved from the dataclass to the call site rather than to YAML"
    )
