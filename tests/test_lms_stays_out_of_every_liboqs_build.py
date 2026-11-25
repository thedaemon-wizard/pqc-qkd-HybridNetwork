"""No liboqs built here compiles LMS, and every build proves it.

The liboqs pin, 0.16.0, is inside two LMS advisories that only 0.17.0 fixes,
and 0.17.0 was not released on 2026-11-25:

  * GHSA-wh5q-mpc8-67wf -- heap out-of-bounds read in LMS/HSS signature
    verification (liboqs 0.11.0 to 0.16.0);
  * GHSA-xv6c-h66p-6mfq -- LMS signing goes ahead when the application's lock
    callback fails, so an LM-OTS one-time key can be used twice, and
    verification accepts a signature of another parameter set (up to 0.16.0).

Nothing here is exposed because nothing here compiles LMS. That rests on a
default: liboqs leaves the stateful-signature families and their key generation
OFF unless a build turns them on. So this checks, for every build that compiles
liboqs from `submodules/liboqs` (each Dockerfile that copies it, and the
Makefile's `build-liboqs` target), that it

  1. passes no CMake option that turns LMS, XMSS or stateful key and signature
     generation on, and
  2. reads the installed `oqsconfig.h` after the install and fails if LMS is
     defined there, so a default flipped upstream breaks the build instead of
     shipping.

Whether the pinned liboqs itself still defaults LMS to OFF is not read here:
that would need the 78 MB submodule in the `python` job, which checks out only
the small submodules its guards read. CI's `images` job builds
`services/pqc-validator/Dockerfile` from the pin, so check 2 runs there against
the real default on every change.

Rosenpass's own liboqs 0.8.0 (vendored by oqs-sys, see the rosenpass notes in
docs/THIRD_PARTY_NOTICES.md) predates LMS in liboqs and is not built from the
submodule, so it is not one of these builds.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TURNS_ON = re.compile(
    r"-D\s*OQS_(?:ENABLE_SIG_STFL_(?:LMS|XMSS)\w*"
    r"|HAZARDOUS_EXPERIMENTAL_ENABLE_SIG_STFL_KEY_SIG_GEN)\s*=\s*(?:ON|1|TRUE|YES)\b", re.I)
HEADER_CHECK = re.compile(r"grep -q ['\"]\^#define OQS_ENABLE_SIG_STFL_LMS['\"]\s+\S*oqsconfig\.h")


def _dockerfiles() -> dict[str, str]:
    files = subprocess.run(["git", "ls-files", "*Dockerfile*"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in files
            if "COPY submodules/liboqs" in (ROOT / f).read_text(encoding="utf-8")}


def _make_target(name: str) -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}:"))
    body = []
    for ln in lines[start + 1:]:
        if ln and not ln.startswith("\t"):
            break
        body.append(ln)
    return "\n".join(body)


def _builds() -> dict[str, str]:
    builds = dict(_dockerfiles())
    builds["Makefile: build-liboqs"] = _make_target("build-liboqs")
    return builds


def test_every_build_of_the_submodule_is_seen():
    """Guard the guard: the known builds must be found, or the checks below pass on nothing."""
    assert {"services/pqc-validator/Dockerfile",
            "services/pqc-tls-demo/Dockerfile.oqs-provider",
            "Makefile: build-liboqs"} <= set(_builds())


@pytest.mark.parametrize("name", sorted(_builds()))
def test_no_build_turns_a_stateful_signature_on(name):
    text = _builds()[name]
    assert not TURNS_ON.search(text), f"{name} turns on {TURNS_ON.search(text).group(0)}"


@pytest.mark.parametrize("name", sorted(_builds()))
def test_every_build_checks_the_installed_header_after_the_install(name):
    text = _builds()[name]
    install = text.find("cmake --install")
    assert install >= 0, f"{name} has no `cmake --install`"
    check = HEADER_CHECK.search(text, install)
    assert check, f"{name} does not read oqsconfig.h for OQS_ENABLE_SIG_STFL_LMS after the install"
    assert "oqsconfig.h" in text[install:] and "test -f" in text[install:], (
        f"{name} must first check that oqsconfig.h exists: grep on a missing file is not 'LMS off'")

