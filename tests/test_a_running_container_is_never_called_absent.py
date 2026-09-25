"""A cosmetic field must not be able to erase an observed status.

`/api/stack` wrapped the whole per-container block in one `try`:

    try:
        c = cli.containers.get(n)
        out.append({... "status": c.status,
                    "image": c.image.tags[0] if c.image.tags else "", ...})
    except Exception:
        out.append({"name": n, "status": "absent", ...})

`c.image` raises `ImageNotFound` whenever the image a container runs has lost
its tag, which happens routinely: rebuilding `pqcqkd/node-alice:local` leaves
every other container still running the previous, now dangling, image ID. The
exception escaped the same `try` as the lookup, so the handler reported the
container as ABSENT.

Measured on the deployed host, after rebuilding alice:

    docker ps           bob   Up 4 days   1a2e95e58251   (a bare ID, untagged)
    containers.get      bob   status=running
    bob.image           ImageNotFound: 404 ... /images/1a2e95e58251
    GET /api/stack      bob   "absent"       <-- three polls, not transient

bob was rotating keys normally throughout. The Overview page showed a working
container as absent, which is worse than the reverse: it invites someone to
"fix" a service that is fine.

The two failures are now separate. Only a failed lookup may say `absent`; a
failed image read yields `<untagged>`, which is a real state rather than an
empty string that would read as "no information".

And only ONE KIND of failed lookup. The lookup's handler was `except
Exception:`, so a Docker API error or a socket timeout -- "we could not look"
-- was reported as "not there", and for qkdnetsim-kme annotated "not that
anything failed". `docker.errors.NotFound` (Docker's 404) is now the only
exception that yields `absent`; anything else yields `unknown` with the error.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from conftest import load_service_app

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "services" / "webui-backend" / "app" / "main.py").read_text(encoding="utf-8")


def _stack_handler() -> str:
    """The code that looks containers up and classifies them.

    That was the body of `async def stack(`. Since 2026-09-25 `stack` is a plain
    `def` that serves a short-lived cache, and the lookup lives in
    `_stack_uncached` -- so find that, not the decorator, or this guard would
    silently stop reading the code it exists to read.
    """
    i = SRC.index("def _stack_uncached(")
    j = SRC.index("\n@app.", i)
    return SRC[i:j]


def test_the_lookup_and_the_image_read_are_separate_blocks():
    h = _stack_handler()
    # The lookup's except must `continue`, so nothing after it can fall into
    # the same handler.
    assert re.search(
        r"c = cli\.containers\.get\(n\)\s*\n\s*except docker\.errors\.NotFound:", h), (
        "the container lookup is no longer in a try of its own, or its absent "
        "branch catches more than Docker's 404"
    )
    assert "continue" in h, "the absent branch does not short-circuit"


def test_only_a_failed_lookup_may_report_absent():
    h = _stack_handler()
    # Exactly one place constructs an absent row inside the loop.
    assert h.count('"status": "absent"') == 1, (
        "more than one path reports absent; a second one is how a running "
        "container gets called missing again"
    )


def test_a_failed_image_read_does_not_reach_the_absent_branch():
    h = _stack_handler()
    # `c.image` must sit in its own try AFTER the lookup's except/continue.
    img = h.index("c.image")
    absent = h.index('"status": "absent"')
    assert absent < img, (
        "the image read still precedes the absent branch, so it can still "
        "fall into it"
    )
    assert re.search(r"try:\s*\n\s*tags = c\.image\.tags", h), (
        "the image read is not guarded on its own"
    )


def test_an_untagged_image_is_reported_as_a_state_not_as_emptiness():
    h = _stack_handler()
    assert "<untagged>" in h, (
        'an unreadable image yields "" again, which reads as "no image '
        'information" rather than "this image has no tag"'
    )


def test_the_measurement_is_recorded_where_the_next_reader_will_be():
    # The comment is the only place the reproduction lives; without it the
    # separation looks like defensive noise and gets folded back together.
    h = _stack_handler()
    assert "ImageNotFound" in h
    assert "dangling" in h


# ---- behaviour, not only source text ------------------------------------------
docker = pytest.importorskip("docker")
load_service_app("webui-backend", "webui_backend_app")
_main = importlib.import_module("webui_backend_app.main")


class _Running:
    status = "running"
    attrs = {"State": {"StartedAt": "2026-09-25T00:00:00Z"}}

    class image:  # noqa: N801 - mimics the SDK attribute
        tags = ["pqcqkd/example:local"]


class _Docker:
    """Answers per name: a container, NotFound, or some other failure."""

    def __init__(self, behaviour):
        outer = self
        self.behaviour = behaviour

        class _C:
            def get(self, name):
                out = outer.behaviour(name)
                if isinstance(out, Exception):
                    raise out
                return out

        self.containers = _C()


def _stack_with(monkeypatch, behaviour):
    monkeypatch.setattr(_main.app.state, "docker", _Docker(behaviour), raising=False)
    return {row["name"]: row for row in _main._stack_uncached()}


def test_a_docker_404_is_absent(monkeypatch):
    rows = _stack_with(monkeypatch, lambda n: docker.errors.NotFound(f"no {n}"))
    assert rows["bb84-kme-a"]["status"] == "absent"
    assert rows["qkdnetsim-kme"]["status"] == "absent"


@pytest.mark.parametrize("error", [
    TimeoutError("read timed out"),
    ConnectionError("docker socket unreachable"),
    docker.errors.APIError("500 Server Error: daemon restarting"),
])
def test_any_other_lookup_failure_is_unknown_never_absent(monkeypatch, error):
    rows = _stack_with(monkeypatch, lambda n: error)
    for name, row in rows.items():
        assert row["status"] == "unknown", (
            f"{name}: a {type(error).__name__} was reported as {row['status']!r}; "
            "we could not look, which is not the same fact as 'not there'")
        assert row["error"], "the reason we could not look is not reported"
    note = rows["qkdnetsim-kme"]["note"]
    assert "not that anything failed" not in note, (
        "an optional row whose lookup FAILED still says nothing failed")


def test_the_absence_note_rides_only_on_absent_rows(monkeypatch):
    """A running optional container must not carry 'Absent here means...'."""
    rows = _stack_with(
        monkeypatch,
        lambda n: _Running() if n == "alice-ipsec" else docker.errors.NotFound(n))
    assert rows["alice-ipsec"]["status"] == "running"
    assert rows["alice-ipsec"]["optional"] is True
    assert "Absent here" not in rows["alice-ipsec"]["note"]
    assert "Absent here" in rows["bob-ipsec"]["note"]
