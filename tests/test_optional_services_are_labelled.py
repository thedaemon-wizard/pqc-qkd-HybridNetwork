"""`PROFILE_GATED` in webui-backend must match the compose files it describes.

`/api/stack` marks a row `optional: true`, with the profile and compose file
that would create it, when the service is defined only behind a compose
`profiles:` entry. Absent is the expected state for such a row, and the
Overview renders it that way instead of as a failure.

The table's own comment said it was "checked against [the compose files] by
tests/test_optional_services_are_labelled.py". That file did not exist, so
nothing checked it. This is that file. It reads every `docker-compose*.yml` at
the repository root and requires, for every service /api/stack reports on:

  * a service defined behind `profiles:` is in PROFILE_GATED, with that
    profile and that file;
  * nothing is in PROFILE_GATED that no compose file gates.

Profile-gated services that /api/stack does not report on (the multihop
overlay's `charlie`) are outside this check, because no row can mislabel them.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from conftest import load_service_app

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")


def _gated_in_compose() -> dict[str, tuple[str, str]]:
    """container name -> (profile, compose file) for every profile-gated service."""
    found: dict[str, tuple[str, str]] = {}
    files = sorted(ROOT.glob("docker-compose*.yml"))
    assert files, "no compose files at the repository root"
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for key, svc in (doc.get("services") or {}).items():
            profiles = (svc or {}).get("profiles")
            if not profiles:
                continue
            assert len(profiles) == 1, (
                f"{f.name}:{key} has several profiles {profiles}; PROFILE_GATED "
                "holds one per service and would have to change shape")
            found[svc.get("container_name", key)] = (profiles[0], f.name)
    return found


def test_every_gated_service_on_the_stack_page_is_labelled():
    compose = _gated_in_compose()
    for name in main.STACK_SERVICES:
        if name in compose:
            assert main.PROFILE_GATED.get(name) == compose[name], (
                f"{name} is gated by {compose[name]} but PROFILE_GATED says "
                f"{main.PROFILE_GATED.get(name)}; /api/stack would call its "
                "absence a failure, or name the wrong overlay")


def test_nothing_is_labelled_optional_that_compose_does_not_gate():
    compose = _gated_in_compose()
    for name, label in main.PROFILE_GATED.items():
        assert compose.get(name) == label, (
            f"PROFILE_GATED marks {name} optional via {label}, but the compose "
            "files do not gate it that way; a required service would read as "
            "absent by design")


def test_every_labelled_service_is_on_the_stack_page():
    assert set(main.PROFILE_GATED) <= set(main.STACK_SERVICES)
