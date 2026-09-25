"""The deploy scripts add firewall rules; they never wipe the host's.

Both scripts ran `ufw --force reset` and re-enabled with 22/80/443 only. On a
host serving anything else, or with SSH on another port, a redeploy dropped
those services or locked the operator out. deploy/lib.sh replaces that.
This runs it against stub `ufw` and `sshd` binaries and reads the calls.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIREWALL = ROOT / "deploy" / "lib.sh"


def _run(tmp_path: Path, *, active: bool, ssh_ports: str) -> list[str]:
    calls = tmp_path / "calls"
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "ufw").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{calls}"\n'
        f'if [ "$1" = status ]; then echo "Status: {"active" if active else "inactive"}"; fi\n')
    (stub / "sshd").write_text(
        "#!/usr/bin/env bash\n" + "".join(f'echo "port {p}"\n' for p in ssh_ports.split()))
    for f in stub.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    script = f'log() {{ :; }}; source "{FIREWALL}"; configure_firewall'
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}
    subprocess.run(["bash", "-c", script], check=True, env=env)
    return calls.read_text().splitlines() if calls.exists() else []


def test_never_resets(tmp_path):
    calls = _run(tmp_path, active=True, ssh_ports="22")
    assert not any(c.startswith("reset") for c in calls), calls
    assert "allow 80/tcp" in calls and "allow 443/tcp" in calls


def test_opens_the_ssh_port_sshd_actually_uses(tmp_path):
    calls = _run(tmp_path, active=True, ssh_ports="2222")
    assert "allow 2222/tcp" in calls
    assert "allow 22/tcp" not in calls


def test_leaves_an_active_firewall_policy_alone(tmp_path):
    calls = _run(tmp_path, active=True, ssh_ports="22")
    assert not any(c.startswith("default") or c.startswith("--force enable") for c in calls), calls


def test_sets_default_deny_only_when_it_is_the_one_enabling(tmp_path):
    calls = _run(tmp_path, active=False, ssh_ports="22")
    assert "default deny incoming" in calls
    assert "--force enable" in calls
    # And the ssh rule lands BEFORE the firewall comes up.
    assert calls.index("allow 22/tcp") < calls.index("--force enable")


def test_no_deploy_script_still_resets():
    for f in ("deploy/deploy.sh", "deploy/deploy-demo.sh"):
        code = "\n".join(l for l in (ROOT / f).read_text().splitlines() if not l.lstrip().startswith("#"))
        assert "ufw --force reset" not in code, f
        assert "configure_firewall" in code, f
        assert "fast_forward_to_branch" in code, f"{f} does not share the --pull routine"


@pytest.mark.parametrize("script", ["deploy/deploy.sh", "deploy/deploy-demo.sh", "deploy/lib.sh"])
def test_scripts_parse(script):
    subprocess.run(["bash", "-n", str(ROOT / script)], check=True)


# ---- the shared --pull routine ----------------------------------------------
def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}).stdout


def _pull(clone: Path) -> subprocess.CompletedProcess:
    script = f'log() {{ echo "LOG $*"; }}; DEPLOY_BRANCH=main; DEPLOY_NAME=t; source "{FIREWALL}"; fast_forward_to_branch'
    return subprocess.run(["bash", "-c", script], cwd=clone, capture_output=True, text=True)


def _repos(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "f").write_text("1\n")
    _git(origin, "add", "f")
    _git(origin, "commit", "-qm", "one")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    return origin, clone


def test_pull_fast_forwards_and_reports_the_range(tmp_path):
    origin, clone = _repos(tmp_path)
    (origin / "f").write_text("2\n")
    _git(origin, "commit", "-qam", "two")
    r = _pull(clone)
    assert r.returncode == 0, r.stderr
    assert (clone / "f").read_text() == "2\n"
    assert "two" in r.stdout


def test_pull_refuses_to_overwrite_a_local_edit(tmp_path):
    origin, clone = _repos(tmp_path)
    (origin / "f").write_text("2\n")
    _git(origin, "commit", "-qam", "two")
    (clone / "f").write_text("local\n")
    r = _pull(clone)
    assert r.returncode != 0
    assert (clone / "f").read_text() == "local\n", "a local edit was overwritten"
    assert "fast-forward refused" in r.stderr
