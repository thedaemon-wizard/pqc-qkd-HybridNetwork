"""The local build-tag narrowing must fix one build and change no other.

`services/arnika-vici/build.sh` rewrites `wireguardnetlink.go`'s build tag in
its temporary assembled tree. Upstream selects the default writer with a
TRAILING NEGATION:

    //go:build wireguard_netlink || (!wireguard_mikrotik && !wireguard_netlink_netns)

so the default is compiled in for any adapter tag upstream has not been taught
about. `strongswan_vici` is not among them, and all three of
wireguardnetlink.go, wireguardmikrotik.go and wireguardnetlinknetns.go define
`getKeyWriterService`, so `-tags strongswan_vici` yields two definitions.

The narrowing adds `&& !strongswan_vici`.

WHAT THIS FILE PINS, AND WHY IT IS NOT OBVIOUS. The open question was whether
the narrowing breaks the netns build upstream had just fixed in #48 -- this
repository does not use netns, so nothing here would have noticed. Measured
2026-09-16 by building the assembled tree under every tag, in Docker against
golang:1.26-bookworm (the same image the node Dockerfiles use):

    tag                        upstream      narrowed
    <none>                     OK            OK
    wireguard_netlink          OK            OK
    wireguard_mikrotik         OK            OK
    wireguard_netlink_netns    OK            OK      <- the one in question
    strongswan_vici            FAILS         OK

Upstream's failure is `main.go:128:20: undefined: getKeyWriterService` once the
adapter file is present -- the narrowing is what makes that build work, and it
changes nothing else.

This test asserts the SHAPE of the rewritten expression rather than re-running
the build, because a Docker build is not something a unit test should do. The
shape is what makes the table above hold: each adapter tag must appear as its
own negated conjunct, so adding an adapter without adding a conjunct is the
bug, not the fix.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_SH = ROOT / "services" / "arnika-vici" / "build.sh"
ARNIKA = ROOT / "submodules" / "arnika"
# The FILE, not the directory. `submodules/arnika/` exists as an empty
# directory whenever the submodule is not checked out, so `ARNIKA.is_dir()` is
# true in the `python` job and the read below then fails instead of skipping.
# Measured in CI: test_the_guard_expects_what_upstream_currently_has failed
# there while passing locally and in `go`.
DEFAULT_WRITER = ARNIKA / "wireguardnetlink.go"


def _checked_out() -> bool:
    """The submodule has sources at all -- as opposed to an empty directory."""
    return (ARNIKA / "main.go").is_file()


def _require_known_layout() -> None:
    """Skip only when there is nothing to read; FAIL when the layout moved.

    Upstream's PR #51 (open on 2026-09-25) renames every writer file to
    `wire_*.go`. With the old `if not DEFAULT_WRITER.is_file(): skip`, a pin
    bump past it would have made every check in this file skip -- green, and
    blind -- while build.sh's EXPECTED line pointed at a file that no longer
    exists. A checked-out submodule without `wireguardnetlink.go` is a layout
    change that build.sh has to be taught, not a missing checkout.
    """
    import pytest
    if not _checked_out():
        pytest.skip("arnika submodule not checked out")
    renamed = sorted(p.name for p in ARNIKA.glob("wire_*.go"))
    assert DEFAULT_WRITER.is_file(), (
        "submodules/arnika is checked out but has no wireguardnetlink.go"
        + (f"; it has {renamed} -- the wire_*.go layout of upstream PR #51" if renamed else "")
        + ". Update services/arnika-vici/build.sh (its EXPECTED tag and the file it "
          "rewrites) and this test for the new layout before moving the pin."
    )

# Every root-level file that defines getKeyWriterService is a writer, and every
# writer except the default must be named in the default's negation.
def _writers() -> dict[str, str]:
    out = {}
    if not DEFAULT_WRITER.is_file():
        return out
    for p in [*ARNIKA.glob("wireguard*.go"), *ARNIKA.glob("wire_*.go")]:
        text = p.read_text(encoding="utf-8", errors="replace")
        if "func getKeyWriterService(" in text:
            out[p.name] = text.splitlines()[0] if text.startswith("//go:build") else ""
    return out


def test_the_rewritten_tag_is_present_and_parseable():
    sh = BUILD_SH.read_text(encoding="utf-8")
    m = re.search(r"printf '%s\\n' '(//go:build [^']+)'", sh)
    assert m, "build.sh no longer writes a //go:build line"
    tag = m.group(1)
    # Go rejects a stray backslash here, and a shell-escaping slip produced
    # exactly that during this investigation: `\&\&` reached the file and every
    # build failed with "parsing //go:build line: invalid syntax at \".
    assert "\\" not in tag, f"the rewritten tag contains a backslash: {tag}"
    assert tag.startswith("//go:build wireguard_netlink || (")


def test_every_other_writer_is_excluded_by_name():
    """A new adapter that is not named here collides with the default."""
    sh = BUILD_SH.read_text(encoding="utf-8")
    tag = re.search(r"printf '%s\\n' '(//go:build [^']+)'", sh).group(1)
    _require_known_layout()
    writers = _writers()

    # Derive the tag each non-default writer selects on, from its own first line.
    others = []
    for name, first in writers.items():
        if name == "wireguardnetlink.go":
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


def test_it_also_excludes_the_adapter_this_repository_adds():
    """The reason the narrowing exists at all."""
    sh = BUILD_SH.read_text(encoding="utf-8")
    tag = re.search(r"printf '%s\\n' '(//go:build [^']+)'", sh).group(1)
    assert "!strongswan_vici" in tag


def test_the_guard_expects_what_upstream_currently_has():
    """EXPECTED must match the real first line, or the build stops before the
    rewrite -- which is the design, and which is what caught upstream's #48
    change when the pin moved."""
    sh = BUILD_SH.read_text(encoding="utf-8")
    m = re.search(r"EXPECTED='(//go:build [^']+)'", sh)
    assert m, "build.sh no longer pins an expected upstream tag"
    _require_known_layout()
    actual = DEFAULT_WRITER.read_text(encoding="utf-8").splitlines()[0]
    assert m.group(1) == actual, (
        f"build.sh expects\n  {m.group(1)}\nbut the pin has\n  {actual}"
    )


def test_a_moved_layout_fails_rather_than_skips(tmp_path, monkeypatch):
    """Guard the guard: simulate the #51 layout and check the check fires."""
    import sys

    import pytest
    mod = sys.modules[__name__]
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "wire_netlink.go").write_text("//go:build x\npackage main\n")
    monkeypatch.setattr(mod, "ARNIKA", tmp_path)
    monkeypatch.setattr(mod, "DEFAULT_WRITER", tmp_path / "wireguardnetlink.go")
    with pytest.raises(AssertionError, match="wire_\\*.go layout of upstream PR #51"):
        _require_known_layout()
