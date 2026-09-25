"""pqc-validator's `/api/agility` must not run on the event loop.

It was `async def` around nine synchronous liboqs calls with no await between
them. On the public demo (2026-09-25) each agility POST held the validator's only
event loop long enough that concurrent GET /api/pqc/algorithms calls from the
backend hit their 3 s timeout and surfaced as 503s, while the validator logged the
same GETs as 200 once the POST finished. A plain `def` runs in the threadpool.

Checked on the source text, so the test runs without liboqs installed.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "services/pqc-validator/app/main.py"


def _handlers() -> dict[str, ast.AST]:
    tree = ast.parse(SRC.read_text())
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_agility_is_a_plain_function():
    fn = _handlers()["agility"]
    assert isinstance(fn, ast.FunctionDef), (
        "/api/agility is `async def` again: its liboqs loop blocks the event loop")


def test_agility_is_still_the_route_handler():
    """Guard the guard: the route must still be bound to this function."""
    fn = _handlers()["agility"]
    routes = [ast.unparse(d) for d in fn.decorator_list]
    assert "app.post('/api/agility')" in routes
