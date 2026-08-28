"""A guard that self-skips in every job that runs it is not a guard.

Several test files in this suite derive a claim from a pinned submodule rather
than restating it -- which is the right shape, and the reason they exist. But
each one also has to survive not finding that submodule, so each carries a
`pytest.skip`. The `python` job runs `pytest tests/` and checked out exactly one
of the fifteen submodules, so the skip fired and the job went green having
asserted nothing.

Read out of the last green `python` job on `main` before this change -- the real
runner, not a developer machine and not a local simulation of one:

    test_paper_comparison_says_what_it_averaged.py    4 skipped,  0 passed
    test_claims_about_the_pinned_strongswan_hold.py   5 skipped,  2 passed
    test_tno_no_key_is_not_no_engine.py               2 skipped, 11 passed

Eleven assertions, not the nine an earlier count gave by dropping the last row.

The first file is the sharpest case: `benchmarks/results/` is gitignored and no
job generated it, so it could only ever run on a machine that had produced the
artefact by hand at some point. It passed for weeks locally and had never
executed in CI once.

This is the same defect the suite exists to catch -- a claim nothing in the
build can contradict -- with the guard itself as the subject. A skip is not a
pass, and the whole-suite summary is where that hides: that job printed
`544 passed, 79 skipped` and went green. With this change it prints
`569 passed, 73 skipped` -- six fewer skips, being the four and the two above.
The strongSwan file's five still skip here and run in the `go` job instead.

A local reproduction of the same condition gave the per-file numbers exactly but
`549 passed, 74 skipped` for the total, because a developer virtualenv carries
optional dependencies the runner does not. The per-file numbers are the load
bearing ones; the totals are quoted from the runner for that reason.

So: for every test file whose skips are gated on a submodule, some CI job must
both run that file and have that submodule. Which job is free to change; that
one exists is not.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="pyyaml absent; it ships in services/bb84-kme/requirements.txt, "
           "which the CI python job installs, so this runs there",
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
TESTS = ROOT / "tests"

# `submodules/X` and `"submodules" / "X"` -- both spellings are in use.
_SUB_SLASH = re.compile(r"submodules/([A-Za-z0-9_.-]+)")
_SUB_PATH = re.compile(r'"submodules"\s*/\s*"([A-Za-z0-9_.-]+)"')


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", []) if isinstance(s, dict)]


def _runs(step: dict) -> str:
    """A step's shell, normalised so it can be read as COMMANDS not as text.

    Both of this file's first-draft parsers matched substrings anywhere in the
    `run:` block, and both were trivially satisfiable by prose:

      - a shell COMMENT saying "we do NOT check out submodules/strongswan"
        counted as checking it out;
      - `echo "to reproduce, run pytest tests/"` in a job that runs no Python
        counted as running the whole suite with that job's submodules.

    Both were constructed and both left the file at 8 passed. So: drop
    full-line comments, then join backslash continuations, so one shell command
    is one line. Joining is also what makes the `images` job's line-continued
    `python -m pytest` block visible at all -- previously the regex stopped at
    the first newline, and that job, which runs three test files inside the
    pqc-validator container, appeared to run none.
    """
    text = str(step.get("run", ""))
    text = "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))
    return re.sub(r"\\\n\s*", " ", text)


def _commands(step: dict) -> list[str]:
    """Split a step's shell into individual commands at operator boundaries."""
    return [c.strip() for c in re.split(r"[\n;&|]+", _runs(step)) if c.strip()]


def _skipped(step: dict) -> bool:
    """A step behind `if: false` does not run, whatever it says.

    Only a literal falsy constant is treated as skipped. An expression is
    assumed live, because guessing at `${{ }}` semantics would be a worse
    error than over-crediting a conditional step.
    """
    return str(step.get("if", "")).strip().lower() in ("false", "off", "no")


def _submodules_available(job: dict) -> set[str] | None:
    """None means "all of them" -- i.e. `submodules: recursive`."""
    got: set[str] = set()
    for step in _steps(job):
        if _skipped(step):
            continue
        with_ = step.get("with") or {}
        if str(with_.get("submodules", "")).lower() in ("recursive", "true"):
            return None
        for cmd in _commands(step):
            # Only an actual `git submodule` invocation counts. A path named
            # in an echo, a comment or any other command does not.
            if re.match(r"^git\b", cmd) and "submodule" in cmd:
                got |= set(_SUB_SLASH.findall(cmd))
    return got


# pytest at a COMMAND position: start of a command, or after `python -m`.
# Deliberately not "the word pytest appears".
_PYTEST_CMD = re.compile(r"^(?:\S+=\S+\s+)*(?:python3?\s+-m\s+)?pytest\b(.*)$")


def _pytest_invocations(step: dict) -> list[str]:
    out = []
    for cmd in _commands(step):
        m = _PYTEST_CMD.match(cmd)
        if m:
            out.append(m.group(1))
    return out


def _test_files_run(job: dict) -> set[str] | None:
    """Which files under tests/ this job runs. None means "the whole suite"."""
    named: set[str] = set()
    runs_all = False
    for step in _steps(job):
        if _skipped(step):
            continue
        for args in _pytest_invocations(step):
            paths = [t for t in args.split() if t.startswith("tests/")]
            if any(p.rstrip("/") == "tests" for p in paths):
                runs_all = True
            named |= {pathlib.Path(p).name for p in paths if p.endswith(".py")}
    return None if runs_all else named


def _guarded_submodules(path: pathlib.Path) -> set[str]:
    """Submodules a file mentions, IF that file can skip at all.

    Deliberately imprecise, and named here rather than left to be discovered:
    this does not prove the skip is gated on the submodule. It reports
    `test_etsi014_contract.py -> {arnika}`, and that file's skip is gated on a
    live KME, not on the arnika tree.

    Over-reporting is the safe direction. The cost is a demand that some job
    check out a tree the file might not need; the cost of under-reporting is a
    guard that goes quiet, which is the entire subject of this file. Tightening
    it would mean deciding which names are load-bearing inside a skip
    expression, and being wrong there fails silently.

    A file that never skips is not at risk either way: if it reads a submodule
    that is absent it fails loudly, which is the outcome we want anyway.
    """
    txt = path.read_text(encoding="utf-8", errors="replace")
    if "pytest.skip" not in txt and "skipif" not in txt:
        return set()
    return set(_SUB_SLASH.findall(txt)) | set(_SUB_PATH.findall(txt))


def _jobs_running(name: str) -> list[str]:
    out = []
    for job_id, job in _jobs().items():
        files = _test_files_run(job)
        if files is None or name in files:
            out.append(job_id)
    return out


# --------------------------------------------------------------------------
# The invariant.
# --------------------------------------------------------------------------

SELF = pathlib.Path(__file__).name


def _files_with_guards() -> list[pathlib.Path]:
    # Excluding this file is not a convenience. Its "references" to submodule
    # paths are the regexes above and the prose describing them -- placeholders
    # like `submodules/X`, not dependencies -- so scanning itself makes it
    # demand a checkout of a submodule that does not exist. A guard that
    # matches its own text is the failure mode this suite has hit repeatedly;
    # it is cheaper to name the exception than to write a cleverer regex.
    return sorted(f for f in TESTS.glob("test_*.py")
                  if f.name != SELF and _guarded_submodules(f))


def test_the_scan_finds_the_files_it_is_supposed_to_check():
    """Guard the guard: a broken regex here would pass everything silently."""
    found = {f.name for f in _files_with_guards()}
    for expected in ("test_claims_about_the_pinned_strongswan_hold.py",
                     "test_paper_comparison_says_what_it_averaged.py",
                     "test_tno_no_key_is_not_no_engine.py"):
        assert expected in found, (
            f"{expected} has a submodule-gated skip and the scan missed it; "
            f"the detection below is not doing anything")


@pytest.mark.parametrize("path", _files_with_guards(), ids=lambda p: p.name)
def test_some_job_runs_this_file_with_its_submodule_present(path):
    need = _guarded_submodules(path)
    running = _jobs_running(path.name)
    assert running, f"{path.name} is not run by any CI job at all"

    jobs = _jobs()
    unmet = []
    for sub in sorted(need):
        if not any(
            (avail := _submodules_available(jobs[j])) is None or sub in avail
            for j in running
        ):
            unmet.append(sub)

    assert not unmet, (
        f"{path.name} skips without {unmet}, and none of the jobs that run it "
        f"({', '.join(running)}) check {'them' if len(unmet) > 1 else 'it'} "
        f"out. The file goes green in CI having asserted nothing. Either add a "
        f"shallow `git submodule update --init --depth 1` to one of those "
        f"jobs, or run the file in a job that already has the tree."
    )


# --------------------------------------------------------------------------
# The gitignored artefact, which no submodule checkout can supply.
# --------------------------------------------------------------------------

def test_the_paper_comparison_artefact_is_produced_before_it_is_read():
    """`benchmarks/results/` is gitignored, so a fresh checkout has no JSON.

    This is not covered by the submodule rule above: the supplementary tree
    being present is necessary but not sufficient -- something has to run the
    producer. Without that step all four guards in the reader skip, including
    the one checking that an absent measurement is distinguishable from a
    measured zero, which is the finding that file was written for.
    """
    reader = "test_paper_comparison_says_what_it_averaged.py"
    assert (TESTS / reader).is_file()

    # The premise: still gitignored, so still absent on a fresh checkout.
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "benchmarks/results/" in ignore, (
        "benchmarks/results/ is no longer gitignored -- if the artefact is "
        "committed now, this test and the CI step it guards are both obsolete")

    jobs = _jobs()
    producers = []
    for j in _jobs_running(reader):
        steps = _steps(jobs[j])
        made = [i for i, s in enumerate(steps)
                if not _skipped(s)
                and any("compare_to_paper.py" in c for c in _commands(s))]
        read = [i for i, s in enumerate(steps)
                if not _skipped(s) and _pytest_invocations(s)]
        # "before" is in this test's name, so assert it. A producer step that
        # runs AFTER the tests leaves them skipping exactly as if it were
        # absent -- and an `if: false` on it does the same. Both were
        # constructed against the first draft, which read neither, and both
        # left this file green.
        if made and read and min(made) < max(read):
            producers.append(j)

    assert producers, (
        f"no job runs tools/compare_to_paper.py BEFORE {reader}, so "
        f"benchmarks/results/paper_comparison.json will not exist when the "
        f"guards read it and all four will skip. Check the step is present, "
        f"is ordered before the test step, and is not disabled by `if:`.")


def test_the_producer_emits_the_shape_the_guards_read():
    """The CI step is only worth adding if it produces what the reader wants.

    Asserted against the script rather than by running it, so this stays a
    fast unit test -- but on the two fields the reader keys off, not on the
    file merely existing.
    """
    src = (ROOT / "tools" / "compare_to_paper.py").read_text(encoding="utf-8")
    assert '"y_column"' in src or "y_column" in src, (
        "the producer no longer names the column it averaged; that field is "
        "the whole point of the reader's first guard")
    assert '"note"' in src, (
        "the producer no longer records WHY `ours` is empty, so n=0 becomes "
        "indistinguishable from a measured zero again")
