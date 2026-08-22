"""A file this repository tells you to run has to be a file that exists.

`services/webui-backend/app/main.py:136` told readers to check the deployment's
posture with `scripts/verify-demo-hardening.sh`. There was no such script. The
comment had been there through several rounds of review, and nothing could
contradict it: the reference is in a docstring, so it costs nothing at import
time and never appears in a traceback.

That is the same shape as the other citation defects found on 2026-08-22 -- a
pointer nobody followed, in a repository whose numbers were all correct. It is
worth a guard precisely because the build cannot notice.

Scope: paths under `scripts/` and `tools/`, which are the two directories whose
whole purpose is "run this". Prose references to `docs/...` and source files
are already covered by the link and checklist guards.

One trap, hit while writing this. `git ls-files` lists submodule gitlinks as
paths, so

    git ls-files | xargs grep -r ...

recurses INTO the submodules and reports every `scripts/*.sh` that liboqs and
oqs-provider mention in their own documentation -- 27 false positives against
one real finding. Read each tracked path as a file, and skip anything that is
a directory.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `scripts/foo.sh`, `tools/bar.py` -- the runnable surface.
REFERENCE = re.compile(r"\b((?:scripts|tools)/[A-Za-z0-9_.\-]+\.(?:sh|py))")

# Text that is quoting some OTHER project's layout rather than ours.
FOREIGN_CONTEXT = ("liboqs", "oqs-provider", "PQClean", "strongswan/scripts")

SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webm", ".ico", ".woff2"}


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    files = []
    for rel in out:
        p = ROOT / rel
        # is_file() is what excludes submodule gitlinks, which are directories.
        if p.is_file() and p.suffix not in SKIP_SUFFIXES:
            files.append(p)
    return files


def test_every_referenced_script_exists():
    missing: list[str] = []
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for line_no, line in enumerate(body.splitlines(), 1):
            if any(token in line for token in FOREIGN_CONTEXT):
                continue
            for ref in REFERENCE.findall(line):
                if not (ROOT / ref).is_file():
                    missing.append(f"{rel}:{line_no} -> {ref}")

    assert not missing, (
        "these files are referenced but do not exist. Either create them or "
        "remove the reference -- an instruction to run a missing script is "
        "worse than no instruction, because it reads as a capability:\n  "
        + "\n  ".join(missing)
    )


def test_the_guard_can_see_the_defect_it_was_written_for():
    """Guard the guard.

    If `REFERENCE` stopped matching, `test_every_referenced_script_exists`
    would pass vacuously over an empty set and look like evidence. Assert it
    actually finds the real references.
    """
    found = set()
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update(REFERENCE.findall(body))

    assert len(found) >= 3, (
        f"the reference pattern matched only {sorted(found)}; it is supposed to "
        "find the scripts/ and tools/ paths named across the tree, so a near-"
        "empty result means the pattern broke rather than that the tree is clean"
    )
    # The one the file was written for, now that it exists.
    assert "scripts/verify-demo-hardening.sh" in found
