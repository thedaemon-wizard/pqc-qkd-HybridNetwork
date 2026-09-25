"""Every Python the Makefile runs is the project venv's.

`make bench` ran `./benchmarks/handshake_timer.py`, whose shebang resolves to
the host's system interpreter, and `make animations` ran `python3.12 -m
manim`. On the development host the system `python3` is 3.9 with none of this
project's packages, so both targets ran against the wrong interpreter while
`make test` and `make lint` already used `$(VENV)`.
"""
from __future__ import annotations

import re
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"


def _recipe_lines() -> list[tuple[int, str]]:
    out = []
    for n, line in enumerate(MAKEFILE.read_text().splitlines(), 1):
        if line.startswith("\t") and not line.lstrip().startswith("#"):
            out.append((n, line.strip()))
    return out


def test_no_recipe_runs_a_bare_python():
    bad = []
    for n, line in _recipe_lines():
        # a python interpreter word not preceded by the venv path
        for m in re.finditer(r"(?<![\w/.)-])(python3(\.\d+)?|python)(?=\s)", line):
            before = line[:m.start()]
            if "$(VENV)" not in before[-40:] and "$(abspath $(VENV))" not in before[-60:] \
                    and ".venv/bin/" not in before[-20:]:
                bad.append(f"Makefile:{n}: {line}")
    assert not bad, "\n".join(bad)


def test_no_recipe_executes_a_python_file_by_its_shebang():
    bad = [f"Makefile:{n}: {line}" for n, line in _recipe_lines()
           if re.match(r"(?:\S+=\S+\s+)*\./\S+\.py\b", line)]
    assert not bad, "\n".join(bad)


def test_the_guard_sees_the_recipes_it_protects():
    lines = "\n".join(l for _, l in _recipe_lines())
    assert "benchmarks/handshake_timer.py" in lines
    assert "manim" in lines
