"""Three documents claimed an NS-3 network layer that never executes.

`composite_sim_to_net` POSTs a SimQN-computed key rate to the `qkdnetsim-kme`
container and then pulls keys back over ETSI 014. Its docstring described
step 2 as:

    We POST that keyRate to the qkdnetsim-kme container, which uses it as
    the `DataRate` parameter for its NS-3 `QuantumChannel` and serves keys
    over its ETSI 014 endpoint.

There is no `QuantumChannel`. The container's entrypoint is
`services/qkdnetsim-kme/kme_facade.py`, a Flask app, and its own module
docstring says the keys "are produced by a small CSPRNG calibrated to a
`keyRate_bps` value". It imports no NS-3 binding, spawns no process, and
constructs no simulator object. The image genuinely compiles NS-3 v3.46 and
qkdnetsim -- and since 2026-08-28 fails the build when that compile fails --
but nothing at runtime executes the result.

Two more places carried the same claim:

  * `docs/LIMITATIONS.md` listed the backend as "SimQN physical layer +
    qkdnetsim NS-3 v3.46 network layer".
  * `README.md` called the service "NS-3 ETSI 014 reference KME".

The repository already contained the correction, twice -- in the Dockerfile
header and in the `qkdnetsim_proxy` bullet three lines below the LIMITATIONS
entry that contradicted it. The honest text was written later and the older
claims were never revisited, so a reader's belief depended on which paragraph
they happened to read. This file makes the build able to notice.

WHY THIS IS ASSERTED ON THE SOURCE TEXT. The claim is about what does NOT
happen at runtime, and no unit test can observe an absence by running the
thing. What is checkable is that the facade contains no mechanism by which
NS-3 could be reached, and that no shipped prose promises one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

FACADE = ROOT / "services" / "qkdnetsim-kme" / "kme_facade.py"
COMPOSITE = ROOT / "services" / "bb84-kme" / "app" / "backends" / "composite_sim_to_net.py"
LIMITATIONS = ROOT / "docs" / "LIMITATIONS.md"
README = ROOT / "README.md"
DOCKERFILE = ROOT / "services" / "qkdnetsim-kme" / "Dockerfile"
PHASES = ROOT / "docs" / "phases.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"

# The first version of this guard scanned three files, and the claim survived in
# two more: docs/phases.md called the proxy "ETSI 014 reference (NS-3 v3.46)"
# and the composite "Physical layer feeds network layer", while the SAME FILE
# refuted both 430 lines later; ARCHITECTURE.md said the rate was "injected
# into qkdnetsim". Picking the files by hand is how a claim moves rather than
# dies, so the list now covers every document that mentions the service.
SCANNED = [COMPOSITE, LIMITATIONS, README, PHASES, ARCHITECTURE]


def _read(p: Path) -> str:
    assert p.is_file(), f"{p.relative_to(ROOT)} is missing"
    return p.read_text(encoding="utf-8")


class TestTheFacadeCannotReachNs3:
    """Not prose: the mechanisms that would be needed are all absent."""

    def test_it_starts_no_process(self) -> None:
        src = _read(FACADE)
        for spawner in ("subprocess", "os.system", "os.exec", "os.spawn",
                        "popen", "pty.spawn"):
            assert spawner not in src, (
                f"{spawner} appears in kme_facade.py; it may now invoke the "
                f"NS-3 binaries the image ships, which would make this file's "
                f"premise stale rather than the docs wrong"
            )

    def test_it_imports_no_ns3_binding(self) -> None:
        src = _read(FACADE)
        imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M)
        offenders = [m for m in imports if m.split(".")[0] in {"ns", "ns3", "visualizer"}]
        assert not offenders, f"kme_facade.py imports an NS-3 binding: {offenders}"

    def test_the_key_source_is_a_csprng(self) -> None:
        # If this stops being true the docs above need rewriting again, and
        # the failure should say so rather than pass quietly.
        src = _read(FACADE)
        assert "import secrets" in src, (
            "kme_facade.py no longer draws from `secrets`; re-check every "
            "claim about what produces the key material"
        )

    def test_the_image_really_does_build_ns3(self) -> None:
        # The complementary half. The docs must not swing to "NS-3 is not
        # involved at all" either: it is compiled, and a broken compile has
        # failed the image since 2026-08-28.
        df = _read(DOCKERFILE)
        assert "./ns3 build" in df
        assert "pipefail" in df, (
            "the pipefail guard is gone; a failed NS-3 compile would again "
            "produce a green image"
        )


class TestNoShippedTextPromisesARunningSimulator:
    """The claim must not come back in any of the three places it lived."""

    # Deliberately narrow. `QuantumChannel` and `DataRate` are NS-3 API names;
    # their presence in a sentence about this container is the specific
    # overstatement, and neither has any other reason to appear.
    NS3_RUNTIME_API = re.compile(r"NS-3\s+`?QuantumChannel|`DataRate`\s+parameter", re.I)

    # The corrections quote the old wording on purpose, so a bare search finds
    # the retraction as readily as the claim. What distinguishes them is the
    # retraction marker -- and that marker routinely sits on a DIFFERENT LINE
    # from the quoted phrase, because the sentence wraps. The first version of
    # this test filtered line by line and duly failed on its own correction.
    # Match on a character window instead, which does not care about wrapping.
    RETRACTION = re.compile(
        r"previously|used to say|this line previously|no longer", re.I)
    WINDOW = 400

    @pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
    def test_no_ns3_runtime_api_is_claimed(self, path: Path) -> None:
        text = _read(path)
        offending = []
        for m in self.NS3_RUNTIME_API.finditer(text):
            around = text[max(0, m.start() - self.WINDOW): m.end() + self.WINDOW]
            if not self.RETRACTION.search(around):
                offending.append(text[max(0, m.start() - 80): m.end() + 80])
        assert not offending, (
            f"{path.relative_to(ROOT)} claims NS-3 runtime machinery outside "
            f"any retraction:\n  " + "\n  ".join(offending)
        )

    def test_that_window_rule_is_not_vacuous(self) -> None:
        # A window wide enough to swallow every mention would make the test
        # above unable to fail. Plant a claim far from any retraction marker
        # and require it to be caught.
        planted = (
            "x\n" * 40
            + "The container drives its NS-3 `QuantumChannel` at that rate.\n"
            + "y\n" * 40
        )
        found = [
            m for m in self.NS3_RUNTIME_API.finditer(planted)
            if not self.RETRACTION.search(
                planted[max(0, m.start() - self.WINDOW): m.end() + self.WINDOW])
        ]
        assert found, "the detector cannot see an unretracted claim at all"

    def test_the_correction_is_actually_present(self) -> None:
        # Guards against the above passing because someone deleted the whole
        # discussion instead of correcting it.
        for path in (COMPOSITE, LIMITATIONS):
            text = _read(path)
            assert re.search(r"No NS-3 runs|no NS-3 runs", text), (
                f"{path.relative_to(ROOT)} no longer states that NS-3 does "
                f"not run; the reader is back to guessing"
            )

    def test_the_layout_tree_does_not_call_the_service_an_ns3_kme(self) -> None:
        """Follow the tree, do not assume which file holds it.

        This asserted on README.md. The repository-layout tree moved to
        ARCHITECTURE.md in the same round, and the test failed for the right
        reason on the wrong premise: the entry had not vanished, the document
        had. Pinning a filename made a documentation move look like a
        regression.
        """
        hits = [
            (path.relative_to(ROOT), ln)
            for path in (README, ROOT / "ARCHITECTURE.md")
            if path.is_file()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if "qkdnetsim-kme/" in ln and ln.lstrip().startswith(("│", "├", "└"))
        ]
        assert hits, "the qkdnetsim-kme entry is in no repository-layout tree"
        offending = [f"{p}: {ln.strip()}" for p, ln in hits
                     if re.search(r"NS-3 ETSI 014 reference KME", ln)]
        assert not offending, "\n  ".join(offending)
