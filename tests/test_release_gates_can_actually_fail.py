"""Two release gates could not fail. This runs them against inputs that must.

A gate that always exits 0 is worse than no gate: the checklist cites it, a
release reads "ok", and the absence of an error is taken as evidence. Both of
the scripts below were in that state, and both are cited by
VERIFICATION_CHECKLIST as things that were run.

`scripts/secret_scan.sh` -- the fallback branch (the one that runs wherever
gitleaks is not installed, which is every developer machine here) was:

    set +e
    grep -rEn ... . | head -n 50

`set +e` disarms `set -e`, and a pipeline's status is its LAST command's, so the
script took `head`'s 0 regardless of what grep found. Measured 2026-08-27:
planting a file holding an OpenSSH private-key header made it print the path,
the line number AND the matching line, then exit 0. So the one output that
should have stopped a release instead copied key material into the operator's
terminal -- or, on a public repository, into a CI log.

Why the fixture below is assembled from fragments rather than written out: the
FIXED scanner immediately flagged this file. Spelling the trigger patterns
literally here would make the repository fail its own secret scan, which is the
"always fail" failure mode this file exists to prevent -- the same defect
wearing the other sign. Every fragment is joined at runtime, so no tracked line
matches, and the assembled string still trips the scanner exactly as intended
(asserted by test_the_fixture_actually_trips_the_scanner).

`scripts/check_env_example.sh` -- the CI `env-example` gate -- sent grep's
errors to /dev/null, so a missing, renamed or moved compose file produced an
EMPTY set of mandatory variables, and a loop over an empty set finds nothing
missing. Measured against a directory holding only the two `.env.example`
files, it printed `ok: ... satisfies all 0 mandatory variable(s)` twice and
exited 0. This gate exists because the public demo sat on a two-month-old build
when `deploy/.env.example` lacked `ARNIKA_PSK`.

Each test below asserts BOTH directions, because only asserting the failure
would let someone "fix" a gate by making it always fail, which is the same
defect wearing the other sign.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET_SCAN = ROOT / "scripts" / "secret_scan.sh"
ENV_CHECK = ROOT / "scripts" / "check_env_example.sh"

# The marker sits ON a line that the scanner's own pattern matches, so an
# echoing scanner necessarily reproduces it. A first draft put the marker on
# line 2, between two BEGIN/END markers -- grep matched only lines 1 and 3, so
# the marker was never in the output and the "does not echo" test passed against
# the ECHOING script. A guard whose fixture cannot trigger the defect is the
# same class of thing this file exists to catch.
SECRET_MARKER = "MARKERTHATMUSTNOTBEECHOEDBACK0000"

# Assembled, never spelled. See the module docstring: a literal here makes the
# repository fail its own scan.
_PK = " ".join(["PRIVATE", "KEY"])                      # noqa: S105 - not a secret
_HDR = "-----BEGIN OPEN" + "SSH " + _PK + "-----"
_PWD = "pass" + "word = " + '"' + SECRET_MARKER + '"'
PLANTED = _HDR + "\n" + _PWD + "\n"


def _run(script: Path, cwd: Path, shell: str = "bash") -> subprocess.CompletedProcess:
    return subprocess.run(
        [shell, str(script)], cwd=cwd, capture_output=True, text=True, timeout=120,
    )


# --------------------------------------------------------------------------
# secret_scan.sh
# --------------------------------------------------------------------------

@pytest.mark.skipif(not SECRET_SCAN.is_file(), reason="secret_scan.sh absent")
def test_a_planted_private_key_fails_the_scan(tmp_path: Path):
    """The case that used to exit 0."""
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    shutil.copy(SECRET_SCAN, tmp_path / "secret_scan.sh")
    (tmp_path / "planted_id_ed25519").write_text(PLANTED, encoding="utf-8")

    r = _run(tmp_path / "secret_scan.sh", tmp_path)
    assert r.returncode != 0, (
        "the scan found a private key and exited 0. A gate that cannot fail is "
        f"not a gate.\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )
    assert "planted_id_ed25519" in (r.stdout + r.stderr), "it did not say WHERE"


@pytest.mark.skipif(not SECRET_SCAN.is_file(), reason="secret_scan.sh absent")
def test_the_scan_does_not_echo_the_secret_it_found(tmp_path: Path):
    """Reporting a leak must not itself leak.

    The gitleaks branch passes --redact. The fallback printed the matched line
    verbatim, so on a public repository a finding would be copied into a public
    CI log -- turning a private mistake into a published one.
    """
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    shutil.copy(SECRET_SCAN, tmp_path / "secret_scan.sh")
    (tmp_path / "planted_id_ed25519").write_text(PLANTED, encoding="utf-8")

    r = _run(tmp_path / "secret_scan.sh", tmp_path)
    both = r.stdout + r.stderr
    assert SECRET_MARKER not in both, (
        "the scanner printed the secret material it found:\n" + both
    )


@pytest.mark.skipif(not SECRET_SCAN.is_file(), reason="secret_scan.sh absent")
def test_a_clean_tree_passes(tmp_path: Path):
    """The other direction: 'always fail' is the same defect, inverted."""
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    shutil.copy(SECRET_SCAN, tmp_path / "secret_scan.sh")
    (tmp_path / "readme.txt").write_text("nothing to see here\n", encoding="utf-8")

    r = _run(tmp_path / "secret_scan.sh", tmp_path)
    assert r.returncode == 0, f"a clean tree failed:\n{r.stdout}\n{r.stderr}"


@pytest.mark.skipif(not SECRET_SCAN.is_file(), reason="secret_scan.sh absent")
def test_the_scanner_does_not_flag_its_own_patterns(tmp_path: Path):
    """It used to report itself, which trains a reader to skim past hits."""
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    shutil.copy(SECRET_SCAN, tmp_path / "secret_scan.sh")
    r = _run(tmp_path / "secret_scan.sh", tmp_path)
    assert r.returncode == 0
    assert "secret_scan.sh" not in r.stdout


# --------------------------------------------------------------------------
# check_env_example.sh
# --------------------------------------------------------------------------

def _env_fixture(tmp_path: Path, *, with_compose: bool, with_mandatory: bool) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "deploy").mkdir()
    shutil.copy(ENV_CHECK, tmp_path / "scripts" / "check_env_example.sh")
    for p in (tmp_path / ".env.example", tmp_path / "deploy" / ".env.example"):
        p.write_text("FOO=1\nARNIKA_PSK=x\n", encoding="utf-8")
    if with_compose:
        body = "services:\n  a:\n    image: x\n"
        if with_mandatory:
            body += "    environment:\n      - P=${ARNIKA_PSK:?set me}\n"
        for rel in ("docker-compose.yml", "docker-compose.strongswan.yml",
                    "docker-compose.multihop.yml",
                    "deploy/docker-compose.cloud.yml",
                    "deploy/docker-compose.demo.yml"):
            (tmp_path / rel).write_text(body, encoding="utf-8")
    return tmp_path / "scripts" / "check_env_example.sh"


@pytest.mark.skipif(not ENV_CHECK.is_file(), reason="check_env_example.sh absent")
def test_missing_compose_files_fail_instead_of_passing_with_zero_variables(tmp_path: Path):
    """The measured case: 'satisfies all 0 mandatory variable(s)', exit 0."""
    script = _env_fixture(tmp_path, with_compose=False, with_mandatory=False)
    r = _run(script, tmp_path, shell="sh")
    assert r.returncode != 0, (
        "no compose file existed and the gate reported success. Read the "
        f"output -- it is the shape that made this vacuous:\n{r.stdout}"
    )
    assert "does not exist" in r.stdout
    assert "satisfies all 0" not in r.stdout


@pytest.mark.skipif(not ENV_CHECK.is_file(), reason="check_env_example.sh absent")
def test_compose_files_with_no_mandatory_variables_fail(tmp_path: Path):
    """Zero matches means the pattern stopped matching, not that the rule went away."""
    script = _env_fixture(tmp_path, with_compose=True, with_mandatory=False)
    r = _run(script, tmp_path, shell="sh")
    assert r.returncode != 0, f"nothing was checked and it passed:\n{r.stdout}"
    assert "NO ${VAR:?}" in r.stdout


@pytest.mark.skipif(not ENV_CHECK.is_file(), reason="check_env_example.sh absent")
def test_a_satisfiable_pair_still_passes(tmp_path: Path):
    """The other direction, so the fix cannot be 'always fail'."""
    script = _env_fixture(tmp_path, with_compose=True, with_mandatory=True)
    r = _run(script, tmp_path, shell="sh")
    assert r.returncode == 0, f"a satisfiable pair failed:\n{r.stdout}\n{r.stderr}"
    assert "satisfies all 1 mandatory variable(s)" in r.stdout


@pytest.mark.skipif(not ENV_CHECK.is_file(), reason="check_env_example.sh absent")
def test_the_real_repository_passes():
    """And the gate still does its actual job here."""
    r = _run(ENV_CHECK, ROOT, shell="sh")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "satisfies all 0" not in r.stdout, (
        "the real repository reported zero mandatory variables, which means "
        "the check read nothing"
    )


@pytest.mark.skipif(not SECRET_SCAN.is_file(), reason="secret_scan.sh absent")
def test_the_fixture_actually_trips_the_scanner(tmp_path: Path):
    """The fixture is assembled, so prove it still matches.

    Assembling the trigger patterns from fragments keeps this file out of the
    repository's own scan results -- but a fixture that no longer matches would
    make every test above pass vacuously, which is precisely the class of
    defect this module is about. So assert the assembly, not just the outcome.
    """
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    assert "PRIVATE" in PLANTED and "KEY" in PLANTED
    assert SECRET_MARKER in PLANTED

    shutil.copy(SECRET_SCAN, tmp_path / "secret_scan.sh")
    (tmp_path / "planted").write_text(PLANTED, encoding="utf-8")
    assert _run(tmp_path / "secret_scan.sh", tmp_path).returncode != 0, (
        "the assembled fixture no longer matches the scanner's patterns, so "
        "every 'a planted secret fails the scan' test above proves nothing"
    )


def test_this_repository_passes_its_own_secret_scan():
    """The fix must not make the tree fail on its own documentation.

    It did, briefly: the working scanner flagged this test file and a checklist
    row for spelling the patterns out. Both were rewritten to assemble or
    paraphrase instead of excluding them by name -- an exclusion would have
    blinded the scanner to a real key committed under tests/.
    """
    if shutil.which("gitleaks"):
        pytest.skip("gitleaks installed; this exercises the fallback branch")
    r = _run(SECRET_SCAN, ROOT)
    assert r.returncode == 0, (
        "the repository fails its own secret scan:\n" + r.stdout + r.stderr
    )


def _case_branch(body: str, pattern: str) -> str:
    """One `case` arm: from its pattern to its own `;;`, not to `esac`.

    Slicing to `esac` was the original bug here. Every later arm -- including
    the `*)` catch-all, which also sets `fail=1` -- fell inside the slice, so
    the assertion below passed on the strength of a DIFFERENT branch's failure
    handling. Deleting `fail=1` from the null arm alone left the script
    printing "::error::rate_limit is null" and exiting 0, and this test still
    went green. Exactly the defect it was written to prevent, one level up.
    """
    start = body.index(pattern)
    end = body.index(";;", start)
    return body[start:end]


def test_the_hardening_script_fails_on_a_null_rate_limit():
    """It printed /api/config verbatim and certified "hardened" regardless.

    Until 2026-08-28 the POST limiter was gated on DEMO_MODE, which the public
    host runs unset -- so `"rate_limit":null` was the honest report of an inert
    limiter, this script printed it, and then said "ok". The limiter is now
    unconditional, so a null means something is wrong.

    Asserts on the script's SOURCE, not by running it: reaching the null
    branch needs a host whose limiter is off, and standing one up is more
    machinery than the check is worth. So it verifies the branch exists AND
    that it sets `fail=1` rather than merely printing -- a report that does not
    change the exit code is how this script certified an unprotected host in
    the first place.
    """
    body = (ROOT / "scripts" / "verify-demo-hardening.sh").read_text(
        encoding="utf-8")
    assert '"rate_limit":null' in body, (
        "the script no longer checks rate_limit, so it would again certify a "
        "host whose POST limiter is not running")
    assert "fail=1" in _case_branch(body, '*\'"rate_limit":null\'*'), (
        "the null case reports but does not fail, so the script still exits 0 "
        "on an unprotected host")


def test_that_assertion_can_actually_fail():
    """The extraction must isolate the arm, or the test above is decorative.

    Feeds a script shaped like the real one but with `fail=1` removed from the
    null arm and left in the catch-all -- the precise mutation the `esac` slice
    could not see.
    """
    mutated = """
case "$cfg" in
    *'"rate_limit":null'*)
        echo "::error::rate_limit is null"
        ;;
    *'"rate_limit":{'*) say "POST rate limiter active" "ok" ;;
    *)
        echo "::error::could not read rate_limit"
        fail=1 ;;
esac
"""
    assert "fail=1" in mutated, "the mutation must keep a fail=1 elsewhere"
    assert "fail=1" not in _case_branch(mutated, '*\'"rate_limit":null\'*'), (
        "the branch extractor is reaching past this arm's `;;` again, so a "
        "null rate_limit could stop failing the script without this test "
        "noticing")
