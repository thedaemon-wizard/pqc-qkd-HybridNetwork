"""`make lint` says "same rules as CI". That has to be true, not asserted.

It was not. The Makefile ran

    ruff check services/ tests/ tools/ animations/ benchmarks/

while .github/workflows/ci.yml's `python` job runs

    ruff check services/ tests/ tools/ benchmarks/

animations/ carries 149 errors today, so the documented command failed locally
on code every CI run is green about -- while its own help text read
"(same rules as CI)".

That is worse than a mismatch. A developer who runs the documented command sees
a wall of errors no gate cares about; the reasonable response is to stop running
`make lint`, which also stops running it for the four paths that DO gate. A
lint target people have learned to ignore is a lint target that is not
protecting anything.

Two further facts the same target carried:

  * it invoked `python3.12 -m ruff`, and the system interpreter has no ruff
    here, so it exited "No module named ruff" before linting anything. A target
    that cannot run in the environment the docs describe is not a gate either.
  * `make test` had the same `python3.12 -m pytest` problem.

Both files are parsed here rather than compared by eye, so the claim is checked
on every run instead of at review time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _ci_ruff_paths() -> list[str]:
    """The argument list of CI's `ruff check`, from the workflow itself."""
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    found: list[str] = []
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []) or []:
            run = step.get("run") or ""
            for line in run.splitlines():
                line = line.strip()
                if line.startswith("ruff check"):
                    found.append(line[len("ruff check"):].strip())
    assert found, "no `ruff check` step in ci.yml; this guard is checking nothing"
    assert len(found) == 1, f"expected one ruff check step, found {found}"
    return sorted(found[0].split())


def _make_lint_paths() -> list[str]:
    """CI_LINT_PATHS from the Makefile, plus a check that `lint` uses it."""
    text = MAKEFILE.read_text(encoding="utf-8")
    m = re.search(r"^CI_LINT_PATHS\s*=\s*(.+)$", text, re.M)
    assert m, (
        "Makefile has no CI_LINT_PATHS. The lint scope must live in one named "
        "variable so this guard can compare it with the workflow."
    )
    lint_body = re.search(r"^lint:.*?(?=^\.PHONY|\Z)", text, re.M | re.S)
    assert lint_body and "$(CI_LINT_PATHS)" in lint_body.group(0), (
        "the `lint` target does not use $(CI_LINT_PATHS), so the variable can "
        "be right while the target is wrong"
    )
    return sorted(m.group(1).split())


def test_make_lint_lints_exactly_what_ci_lints():
    ci, mk = _ci_ruff_paths(), _make_lint_paths()
    assert mk == ci, (
        "`make lint` advertises the same rules as CI and does not run them.\n"
        f"  CI:          {ci}\n"
        f"  make lint:   {mk}\n"
        "Either add the path to CI's ruff step or drop it from CI_LINT_PATHS. "
        "Do not leave them different and reword the help text -- the value of "
        "this target is that running it locally means something."
    )


def test_animations_is_deliberately_excluded_and_says_so():
    """The exclusion must be a decision on the page, not a silence."""
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "animations/" not in re.search(r"^CI_LINT_PATHS\s*=\s*(.+)$", text, re.M).group(1)
    assert "lint-animations:" in text, (
        "animations/ is unlinted with no way to lint it on purpose. Provide the "
        "escape hatch so the exclusion reads as a choice."
    )
    # The contiguous comment run immediately above the ASSIGNMENT, not a fixed
    # window before the first mention of the name -- the first mention is inside
    # that very comment, so a byte-offset window looked backwards past it and
    # missed the paragraph it was meant to read.
    lines = text.splitlines()
    at = next(i for i, ln in enumerate(lines) if re.match(r"^CI_LINT_PATHS\s*=", ln))
    j = at - 1
    while j >= 0 and (lines[j].startswith("#") or not lines[j].strip()):
        j -= 1
    note = "\n".join(lines[j + 1:at])
    assert "Manim" in note, (
        "nothing says WHY animations/ is excluded. An unexplained exclusion is "
        "indistinguishable from an oversight, which is how this started."
    )


@pytest.mark.parametrize("target", ["lint", "fmt", "test"])
def test_the_documented_targets_can_actually_run(target: str):
    """`python3.12 -m ruff` exited 'No module named ruff' in this environment.

    The project's tools live in .venv -- VERIFICATION_CHECKLIST's one-command
    block already said so. The Makefile invoked the system interpreter, so
    every one of these targets failed before doing any work.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    body = re.search(rf"^{target}:.*?(?=^\.PHONY|\Z)", text, re.M | re.S)
    assert body, f"no `{target}` target"
    recipe = "\n".join(
        line for line in body.group(0).splitlines() if line.startswith("\t")
    )
    assert "python3.12 -m" not in recipe, (
        f"`make {target}` invokes the system python3.12, which has neither ruff "
        f"nor pytest here:\n{recipe}\nUse $(VENV)."
    )
    assert "$(VENV)" in recipe, f"`make {target}` does not use $(VENV):\n{recipe}"
