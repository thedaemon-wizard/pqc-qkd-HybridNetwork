"""The "Logs" button must hand back a log that exists, and the right one.

`ExportToolbar` offers two mutually exclusive sources:

  * `logProvider` -- a closure returning text the page already holds, saved
    client-side;
  * `logService="X"` -- a fetch of `/api/logs/download/X`, the backend's
    rotating file for service X.

Three separate defects came out of picking the wrong one, and the first two
were fixed a page at a time without anyone checking the rest:

  1. `/e2e`, `/paper-flow`, `/bb84`, `/physics` and `/pqc` each ran their
     simulation in the browser and then offered `logService="webui-backend"`,
     which downloads the server's HTTP request log -- unrelated to the run the
     user just watched.
  2. `/console` did something stranger. Its switcher lists CONTAINER names
     (alice, bob, bb84-kme-a, bb84-kme-b) while the KME writes its rotating
     file under the NODE name it is acting as -- `logging_setup.configure(
     os.environ.get("SAE_ID", "bb84-kme").lower())`, and compose sets
     SAE_ID=ALICE on bb84-kme-a. The two namespaces overlap on the strings
     "alice"/"bob" but mean different processes, and the ternary
     `active.includes("kme") ? active : "webui-backend"` mapped them backwards:

         alice / bob      -> "webui-backend", a different service entirely
         bb84-kme-a / -b  -> bb84-kme-a.log, which no process writes

     Measured against the deployed demo on 2026-08-22: all four selections
     failed, and the two KME ones returned HTTP 200 with the body
     "# log file bb84-kme-a.log not found" under a Content-Disposition header,
     so the browser saved a one-line file that looked like an empty log.

  3. That stub is the reason (2) went unnoticed, so it is now a 404.

This file guards the rule rather than the five instances, because "fix the
page I am looking at" is what let the class survive three rounds.

The set of producible names is DERIVED from the `logging_setup.configure(...)`
call sites and the compose files, not listed here. A hardcoded list would have
to be edited in lockstep with the thing it checks, which is the failure mode
one level up.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "services" / "webui-frontend" / "src" / "pages"
BACKEND_MAIN = ROOT / "services" / "webui-backend" / "app" / "main.py"

LOG_SERVICE = re.compile(r'logService=(?:"([^"]+)"|\{([^}]*)\})')
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def _pages() -> list[Path]:
    return sorted(PAGES.glob("*.tsx"))


def _code(src: str) -> str:
    """Source with comments removed.

    Every page that was fixed carries a comment explaining why it uses
    `logProvider` and not the other one, and those comments necessarily name
    the thing they warn against -- so a raw substring search reports the
    explanation as the defect. The first run of this file did exactly that on
    `Console.tsx`.

    `(?<!:)` keeps `https://` out of the line-comment pattern.
    """
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", src))


def _producible_log_names() -> set[str]:
    """Service names for which some process actually writes <name>.log.

    Two producers call `logging_setup.configure`:

      * webui-backend, with the literal "webui-backend";
      * bb84-kme, with `os.environ.get("SAE_ID", "bb84-kme").lower()`.

    So the KME's filename is whatever SAE_ID compose gives it, lowercased.
    """
    names = {"webui-backend", "bb84-kme"}
    for compose in sorted(ROOT.glob("docker-compose*.yml")):
        doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        for svc in (doc.get("services") or {}).values():
            env = (svc or {}).get("environment") or {}
            if isinstance(env, list):  # "KEY=value" form
                env = dict(
                    item.split("=", 1) for item in env if isinstance(item, str) and "=" in item
                )
            sae = env.get("SAE_ID")
            if isinstance(sae, str) and sae:
                names.add(sae.lower())
    return names


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_a_page_that_displays_a_log_exports_that_log(page: Path):
    """If the page fetched the text, it must save the text.

    `getLogs` is the only way a page obtains log content to render. Having
    rendered it, the page holds the exact bytes on screen, so routing the
    export back through the server can only produce a different file -- which
    is what `/console` did for every one of its four containers.
    """
    src = _code(page.read_text(encoding="utf-8"))
    if "getLogs" not in src:
        pytest.skip("page does not display a log")
    assert "logService" not in src, (
        f"{page.name} renders a log fetched with getLogs but exports via "
        "logService, so the file the user saves is not the text on screen. "
        "Pass logProvider={() => log} instead."
    )


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_every_log_service_names_a_producible_log(page: Path):
    """A `logService` string must name a file some process writes.

    `/api/logs/download/<name>` now 404s on an unknown name, so a wrong string
    here is a broken button rather than a misleading one -- still worth
    catching before it ships.
    """
    src = _code(page.read_text(encoding="utf-8"))
    producible = _producible_log_names()
    for literal, expression in LOG_SERVICE.findall(src):
        if not literal:
            pytest.fail(
                f"{page.name}: logService is computed ({{{expression.strip()}}}) "
                "so its value cannot be checked here. Use a literal, or "
                "logProvider if the page holds the text. /console used a "
                "ternary and both of its branches were wrong."
            )
        assert literal in producible, (
            f"{page.name}: logService={literal!r} but no process writes "
            f"{literal}.log. Producible names, derived from the "
            f"logging_setup.configure call sites and SAE_ID in the compose "
            f"files: {sorted(producible)}."
        )


def test_a_missing_log_is_a_404_not_an_empty_file():
    """The stub that hid defect (2).

    Guarding the source text because the behaviour needs a running backend
    with a populated LOG_DIR, which the host suite does not have.
    """
    src = BACKEND_MAIN.read_text(encoding="utf-8")
    body = src.split("async def download_log", 1)
    assert len(body) == 2, "download_log is gone; update this test"
    handler = body[1].split("\n@app.", 1)[0]

    code = "\n".join(line.split("#", 1)[0] for line in handler.splitlines())
    assert "log file" not in code or "404" in code, (
        "download_log still substitutes a '# log file ... not found' body for "
        "a missing file. That returns HTTP 200 with a Content-Disposition "
        "header, so the caller saves a one-line file that looks like a log."
    )
    assert "404" in code, (
        "download_log must 404 when the requested log does not exist, so a "
        "wrong service name fails loudly instead of downloading a comment."
    )
