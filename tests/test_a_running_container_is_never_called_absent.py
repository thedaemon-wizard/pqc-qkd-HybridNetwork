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
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "services" / "webui-backend" / "app" / "main.py").read_text(encoding="utf-8")


def _stack_handler() -> str:
    i = SRC.index("async def stack(")
    j = SRC.index("\n@app.", i)
    return SRC[i:j]


def test_the_lookup_and_the_image_read_are_separate_blocks():
    h = _stack_handler()
    # The lookup's except must `continue`, so nothing after it can fall into
    # the same handler.
    assert re.search(r"c = cli\.containers\.get\(n\)\s*\n\s*except Exception:", h), (
        "the container lookup is no longer in a try of its own"
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
