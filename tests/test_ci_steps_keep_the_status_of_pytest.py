"""A CI step that pipes pytest into another command reports that command's status.

The live-stack job's physics step ran `python -m pytest ... 2>&1 | tee /tmp/out`
inside `sh -c`, then grepped the output for skips. Without pipefail a pipeline's
status is its last command's, so it was tee's: a failing assertion passed the
step whenever nothing skipped, and only a skip could fail it. The contract step
of the same job had the opposite gap -- no pipe, but no skip check either -- so
KMEs that never answered would have turned all sixteen contract tests into
skips and the step green.

Both steps now keep pytest's status (`... > out 2>&1 || rc=$?`, then
`exit "$rc"`) and fail on a skip. This file keeps the first shape out of every
workflow and pins the second on the contract step.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="pyyaml absent; it ships in services/bb84-kme/requirements.txt, "
           "which the CI python job installs, so this runs there",
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
CI = ROOT / ".github" / "workflows" / "ci.yml"

# pytest, then a single `|` later on the same logical line. `||` is not a pipe.
_PIPED_PYTEST = re.compile(r"\bpytest\b.*?(?<!\|)\|(?!\|)")
_SKIP_CHECK = re.compile(r'grep -qE "\^SKIPPED\|\[0-9\]\+ skipped"')


def _logical_lines(run: str) -> list[str]:
    """`run:` text with backslash continuations joined and comment lines dropped."""
    joined = re.sub(r"\\\n\s*", " ", run)
    return [line for line in joined.splitlines() if not line.lstrip().startswith("#")]


def _steps():
    for wf in WORKFLOWS:
        jobs = yaml.safe_load(wf.read_text(encoding="utf-8")).get("jobs") or {}
        for job_name, job in jobs.items():
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    yield wf.name, job_name, step


def test_there_are_steps_that_run_pytest():
    # Without this floor the next test passes on a parser that finds nothing.
    running = [s for _, _, s in _steps() if "pytest" in s["run"]]
    assert len(running) >= 4, f"only {len(running)} steps run pytest"


def test_no_step_pipes_pytest_away_from_its_status():
    offenders = []
    for wf, job, step in _steps():
        if "pipefail" in step["run"]:
            continue
        for line in _logical_lines(step["run"]):
            if _PIPED_PYTEST.search(line):
                offenders.append(f"{wf} {job} / {step.get('name', '?')}: {line.strip()[:100]}")
    assert not offenders, (
        "these steps pipe pytest into another command, so the step reports that "
        "command's status, not pytest's:\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("line, hit", [
    ("cd /repo && python -m pytest tests/a.py -v -p no:cacheprovider 2>&1 | tee /tmp/out", True),
    ("pytest tests/test_x.py -v | tail -n 20", True),
    ("pytest tests/a.py tests/b.py -v -rs > /tmp/contract.out 2>&1 || rc=$?", False),
    ("pip install --quiet --no-cache-dir pytest pytest-asyncio || exit 1", False),
    ("pip install pytest pytest-asyncio numpy pyyaml", False),
])
def test_the_pipe_pattern_matches_what_it_promises(line, hit):
    assert bool(_PIPED_PYTEST.search(line)) is hit


def test_the_contract_step_fails_when_its_tests_skip():
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    steps = [s for s in jobs["live-stack"]["steps"]
             if isinstance(s, dict) and "test_etsi014_contract.py" in s.get("run", "")]
    assert len(steps) == 1, f"{len(steps)} live-stack steps run the 014 contract"
    run = steps[0]["run"]
    assert _SKIP_CHECK.search(run), "the contract step no longer fails on a skip"
    assert 'exit "$rc"' in run, "the contract step no longer exits with pytest's status"
