"""The local build-tag narrowing must fix one build and change no other.

`services/arnika-vici/build.sh` assembles a temporary tree -- the pinned arnika
plus this repository's strongSwan VICI adapter -- and rewrites the build tag of
upstream's default writer there. Upstream selects that writer with a TRAILING
NEGATION:

    //go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)

so the default is compiled in for any adapter tag upstream has not been taught
about. `strongswan_vici` is not among them, and every writer's wiring file
defines `getKeyWriterService`, so `-tags strongswan_vici` yields two
definitions. The narrowing adds `&& !strongswan_vici`.

The layout is upstream PR #51's, which the pin (f4cf9ba) is the head of: one
package per adapter under `repositories/<pkg>/` and one wiring file per backend
at the root, named `wire_` plus the build tag (its KEYCONTROL.md, "Naming and
File Layout Conventions"). So the default writer's wiring is
`wire_wireguard_netlink.go`, the adapter is `repositories/swanvici/`, and its
wiring is `wire_strongswan_vici.go`. The first line of the default writer is
byte-identical to the pre-#51 `wireguardnetlink.go`, so the narrowing itself is
unchanged; what moved is the file it is applied to.

WHAT THIS FILE PINS, AND WHY IT IS NOT OBVIOUS. The open question when the
narrowing was introduced was whether it breaks the netns build upstream had just
fixed in #48 -- this repository does not use netns, so nothing here would have
noticed. Measured 2026-09-16 by building the assembled tree under every tag, in
Docker against golang:1.26-bookworm (the same image the node Dockerfiles use):

    tag                        upstream      narrowed
    <none>                     OK            OK
    wireguard_netlink          OK            OK
    wireguard_mikrotik         OK            OK
    wireguard_netlink_netns    OK            OK      <- the one in question
    strongswan_vici            FAILS         OK

That table was measured on the pre-#51 file names; the expression it depends
on is the same string at f4cf9ba.

Two kinds of check follow. The SHAPE of the rewritten expression is asserted
against the pinned tree, because a Docker build is not something a unit test
should do: each adapter tag must appear as its own negated conjunct, so adding
an adapter without adding a conjunct is the bug. And build.sh's own guards are
exercised by running it against a synthetic tree with a stand-in `go` that
records what it was asked to build -- the guards are shell, and the only way to
know a guard fires is to make it fire.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SH = ROOT / "services" / "arnika-vici" / "build.sh"
ADAPTER_SRC = ROOT / "services" / "arnika-vici"
ARNIKA = ROOT / "submodules" / "arnika"
# The FILE, not the directory. `submodules/arnika/` exists as an empty
# directory whenever the submodule is not checked out, so `ARNIKA.is_dir()` is
# true in the `python` job and the read below then fails instead of skipping.
DEFAULT_WRITER_NAME = "wire_wireguard_netlink.go"
DEFAULT_WRITER = ARNIKA / DEFAULT_WRITER_NAME
# The pre-#51 name of the same file. Its presence means the pin moved back.
LEGACY_DEFAULT_WRITER_NAME = "wireguardnetlink.go"

# What this repository overlays, per the layout above.
ADAPTER_PACKAGE = Path("repositories") / "swanvici"
ADAPTER_WIRING = "wire_strongswan_vici.go"
ADAPTER_TAG = "strongswan_vici"


def _checked_out() -> bool:
    """The submodule has sources at all -- as opposed to an empty directory."""
    return (ARNIKA / "main.go").is_file()


def _require_known_layout() -> None:
    """Skip only when there is nothing to read; FAIL when the layout moved.

    A pin bump that changes the layout must not turn every check here into a
    skip -- green, and blind -- while build.sh points at a file that no longer
    exists. A checked-out submodule without the default writer's wiring file is
    a layout change build.sh has to be taught, not a missing checkout.
    """
    if not _checked_out():
        pytest.skip("arnika submodule not checked out")
    legacy = (ARNIKA / LEGACY_DEFAULT_WRITER_NAME).is_file()
    assert DEFAULT_WRITER.is_file(), (
        f"submodules/arnika is checked out but has no {DEFAULT_WRITER_NAME}"
        + (f"; it has {LEGACY_DEFAULT_WRITER_NAME} -- the layout from before upstream "
           "PR #51" if legacy else "")
        + ". Update services/arnika-vici/build.sh (its EXPECTED tag and the file it "
          "rewrites) and this test for the new layout before moving the pin."
    )


def _writers() -> dict[str, str]:
    """Every root-level file that defines getKeyWriterService, with its first line."""
    out = {}
    for p in sorted({*ARNIKA.glob("wire_*.go"), *ARNIKA.glob("wireguard*.go")}):
        if p.name.endswith("_test.go"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "func getKeyWriterService(" in text:
            out[p.name] = text.splitlines()[0] if text.startswith("//go:build") else ""
    return out


def _sh() -> str:
    return BUILD_SH.read_text(encoding="utf-8")


def _rewritten_tag() -> str:
    m = re.search(r"printf '%s\\n' '(//go:build [^']+)'", _sh())
    assert m, "build.sh no longer writes a //go:build line"
    return m.group(1)


def _expected_tag() -> str:
    m = re.search(r"EXPECTED='(//go:build [^']+)'", _sh())
    assert m, "build.sh no longer pins an expected upstream tag"
    return m.group(1)


def _narrowed(expected: str) -> str:
    """EXPECTED with exactly one conjunct added inside its trailing group."""
    assert expected.endswith(")"), f"the expected tag no longer ends in a group: {expected}"
    return f"{expected[:-1]} && !{ADAPTER_TAG})"


# ------------------------------------------------------- shape of the rewrite --

def test_the_rewritten_tag_is_present_and_parseable():
    tag = _rewritten_tag()
    # Go rejects a stray backslash here, and a shell-escaping slip produced
    # exactly that during this investigation: `\&\&` reached the file and every
    # build failed with "parsing //go:build line: invalid syntax at \".
    assert "\\" not in tag, f"the rewritten tag contains a backslash: {tag}"
    assert tag.startswith("//go:build wireguard_netlink || (")


def test_the_rewrite_adds_one_conjunct_and_keeps_upstreams():
    """Dropping `!wireguard_netlink_netns` here would silently re-break the
    case upstream fixed in #48, in a tree upstream never sees."""
    assert _rewritten_tag() == _narrowed(_expected_tag())


def test_it_also_excludes_the_adapter_this_repository_adds():
    """The reason the narrowing exists at all."""
    assert f"!{ADAPTER_TAG}" in _rewritten_tag()


def test_every_other_writer_is_excluded_by_name():
    """A new adapter that is not named here collides with the default."""
    tag = _rewritten_tag()
    _require_known_layout()
    writers = _writers()
    others = []
    for name, first in writers.items():
        if name == DEFAULT_WRITER_NAME:
            continue
        t = re.search(r"//go:build\s+(\w+)", first)
        if t:
            others.append(t.group(1))
    assert others, f"no non-default writers found among {sorted(writers)}"
    missing = [t for t in others if f"!{t}" not in tag]
    assert not missing, (
        f"the narrowed tag does not exclude {missing}, so `-tags {missing[0]}` "
        f"compiles that writer AND the default, giving two definitions of "
        f"getKeyWriterService. Tag is: {tag}"
    )


def test_the_guard_expects_what_upstream_currently_has():
    """EXPECTED must match the real first line, or the build stops before the
    rewrite -- which is the design, and which is what caught upstream's #48
    change when the pin moved."""
    expected = _expected_tag()
    _require_known_layout()
    actual = DEFAULT_WRITER.read_text(encoding="utf-8").splitlines()[0]
    assert expected == actual, f"build.sh expects\n  {expected}\nbut the pin has\n  {actual}"


def test_upstream_does_not_ship_what_this_repository_overlays():
    """If upstream adopts the adapter, the overlay must stop, not replace it."""
    _require_known_layout()
    assert not (ARNIKA / ADAPTER_WIRING).exists()
    assert not (ARNIKA / ADAPTER_PACKAGE).exists()


def test_a_moved_layout_fails_rather_than_skips(tmp_path, monkeypatch):
    """Guard the guard: simulate the pre-#51 layout and check the check fires."""
    import sys
    mod = sys.modules[__name__]
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / LEGACY_DEFAULT_WRITER_NAME).write_text("//go:build x\npackage main\n")
    monkeypatch.setattr(mod, "ARNIKA", tmp_path)
    monkeypatch.setattr(mod, "DEFAULT_WRITER", tmp_path / DEFAULT_WRITER_NAME)
    with pytest.raises(AssertionError, match="layout from before upstream PR #51"):
        _require_known_layout()


# ------------------------------------------- build.sh's guards, made to fire --

# A stand-in for the Go toolchain. It records every invocation, and for a build
# it records what the assembled tree looked like at that moment, which is the
# only point at which the temporary tree can be observed (build.sh deletes it on
# exit). A build that names the adapter tag together with another writer's tag
# fails, as the real one does: two definitions of getKeyWriterService.
_GO_STUB = r"""#!/bin/sh
echo "$*" >> "$GO_STUB_DIR/calls"
[ "$1" = build ] || exit 0
tags=""
prev=""
out=""
for a in "$@"; do
  [ "$prev" = "-tags" ] && tags="$a"
  [ "$prev" = "-o" ] && out="$a"
  prev="$a"
done
case "$tags" in
  *strongswan_vici*wireguard_*|*wireguard_*strongswan_vici*) exit 1 ;;
esac
head -1 wire_wireguard_netlink.go > "$GO_STUB_DIR/first_line" 2>/dev/null
ls repositories/swanvici > "$GO_STUB_DIR/package_files" 2>/dev/null
[ -f wire_strongswan_vici.go ] && : > "$GO_STUB_DIR/wiring_present"
[ -n "$out" ] && : > "$out"
exit 0
"""


def _fake_arnika(root: Path, first_line: str, layout: str = "wire") -> Path:
    """A tree with the file names and first lines of the pinned layout."""
    tree = root / "arnika"
    (tree / "repositories" / "pqchpke").mkdir(parents=True)
    (tree / "config").mkdir()
    (tree / "go.mod").write_text("module github.com/arnika-project/arnika\n\ngo 1.26\n")
    (tree / "main.go").write_text("package main\n\nfunc main() {}\n")
    (tree / "config" / "config.go").write_text('package config\n\nconst _ = "PQC_ENABLED"\n')
    (tree / "repositories" / "pqchpke" / "pqchpke.go").write_text("package pqchpke\n")
    writer = "func getKeyWriterService() {}\n"
    default = DEFAULT_WRITER_NAME if layout == "wire" else LEGACY_DEFAULT_WRITER_NAME
    (tree / default).write_text(f"{first_line}\n\npackage main\n\n{writer}")
    for tag in ("wireguard_mikrotik", "wireguard_netlink_netns"):
        name = f"wire_{tag}.go" if layout == "wire" else f"{tag.replace('_', '')}.go"
        (tree / name).write_text(f"//go:build {tag}\n\npackage main\n\n{writer}")
    return tree


def _run_build(tmp_path: Path, tree: Path) -> tuple[subprocess.CompletedProcess, Path]:
    stub_dir = tmp_path / "stub"
    bin_dir = stub_dir / "bin"
    bin_dir.mkdir(parents=True)
    go = bin_dir / "go"
    go.write_text(_GO_STUB)
    go.chmod(go.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = {k: v for k, v in os.environ.items() if k != "ARNIKA_VICI_VET_AND_TEST"}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GO_STUB_DIR"] = str(stub_dir)
    proc = subprocess.run(
        [shutil.which("sh") or "/bin/sh", str(BUILD_SH), str(tree), str(ADAPTER_SRC),
         str(tmp_path / "arnika-vici")],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    return proc, stub_dir


def _built(stub_dir: Path) -> bool:
    calls = stub_dir / "calls"
    return calls.is_file() and any(c.startswith("build") for c in calls.read_text().splitlines())


def test_build_sh_overlays_the_adapter_and_narrows_the_default_writer(tmp_path):
    tree = _fake_arnika(tmp_path, _expected_tag())
    proc, stub = _run_build(tmp_path, tree)
    assert proc.returncode == 0, f"build.sh failed on the expected layout:\n{proc.stderr}"
    assert _built(stub), "build.sh exited 0 without building"
    builds = [c for c in (stub / "calls").read_text().splitlines() if c.startswith("build")]
    assert any(f"-tags {ADAPTER_TAG}" in c for c in builds), builds
    assert (stub / "first_line").read_text().strip() == _narrowed(_expected_tag())
    files = (stub / "package_files").read_text().split()
    assert any(f.endswith(".go") and not f.endswith("_test.go") for f in files), (
        f"no adapter source was overlaid into {ADAPTER_PACKAGE}: {files}")
    assert (stub / "wiring_present").exists(), f"{ADAPTER_WIRING} was not overlaid"
    assert not (tree / ADAPTER_WIRING).exists(), "build.sh modified the source tree it was given"


def test_build_sh_stops_when_upstream_changes_the_default_writers_tag(tmp_path):
    tree = _fake_arnika(tmp_path, "//go:build wireguard_netlink || !wireguard_mikrotik")
    proc, stub = _run_build(tmp_path, tree)
    assert proc.returncode != 0 and proc.stderr.strip()
    assert not _built(stub), "build.sh built against a default-writer tag it does not know"


def test_build_sh_stops_on_the_layout_from_before_pr_51(tmp_path):
    tree = _fake_arnika(tmp_path, _expected_tag(), layout="legacy")
    proc, stub = _run_build(tmp_path, tree)
    assert proc.returncode != 0
    assert not _built(stub), "build.sh built a tree without wire_wireguard_netlink.go"


def test_build_sh_stops_if_upstream_already_ships_the_wiring_file(tmp_path):
    tree = _fake_arnika(tmp_path, _expected_tag())
    (tree / ADAPTER_WIRING).write_text("//go:build strongswan_vici\n\npackage main\n")
    proc, stub = _run_build(tmp_path, tree)
    assert proc.returncode != 0 and proc.stderr.strip()
    assert not _built(stub), f"build.sh overwrote an upstream {ADAPTER_WIRING}"


def test_build_sh_stops_if_upstream_already_ships_the_adapter_package(tmp_path):
    tree = _fake_arnika(tmp_path, _expected_tag())
    (tree / ADAPTER_PACKAGE).mkdir(parents=True)
    (tree / ADAPTER_PACKAGE / "vici.go").write_text("package swanvici\n")
    proc, stub = _run_build(tmp_path, tree)
    assert proc.returncode != 0 and proc.stderr.strip()
    assert not _built(stub), f"build.sh overlaid onto an upstream {ADAPTER_PACKAGE}"
