"""Three documents claimed an NS-3 network layer that never executes.

`composite_sim_to_net` POSTs a SimQN-computed key rate to the `qkdnetsim-kme`
container and then pulls keys back over ETSI 014. Its docstring described
step 2 as:

    We POST that keyRate to the qkdnetsim-kme container, which uses it as
    the `DataRate` parameter for its NS-3 `QuantumChannel` and serves keys
    over its ETSI 014 endpoint.

There is no `QuantumChannel`. The container's entrypoint is
`services/qkdnetsim-kme/kme_facade.py`, a Flask app whose keys come from
`secrets.token_bytes` -- the CODE is the evidence, which is what the first class
below asserts on. It imports no NS-3 binding, spawns no process, and
constructs no simulator object. The image genuinely compiles NS-3 v3.46 and
qkdnetsim -- and since 2026-08-28 fails the build when that compile fails --
but nothing at runtime executes the result.

The facade's own docstring is not evidence, and this file used to lean on it as
if it were. It said the facade "exposes qkdnetsim's QKD-derived key material",
was "bug-compatible" with the C++ KMS and indistinguishable from it to arnika --
the same overclaim, in the one file every other correction pointed to as the
honest source. It is scanned now like any other document.

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
import subprocess
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
# into qkdnetsim". The list was then extended by hand to five and described as
# covering "every document that mentions the service" -- while the facade's own
# docstring, the backend registry, the Dockerfile, NOTICE and the roadmap all
# mentioned it and none was scanned. Picking files by hand is how a claim moves
# rather than dies, so the scope is now DERIVED: every tracked file outside
# tests/ and submodules/ that names the service. tests/ is left out because this
# file and its neighbours quote the claims in order to forbid them.
KNOWN = [FACADE, COMPOSITE, LIMITATIONS, README, PHASES, ARCHITECTURE, DOCKERFILE]
_TEXT_SUFFIXES = {".md", ".py", ".ts", ".tsx", ".yml", ".yaml", ".sh", ".example", ""}


def _documents_that_name_the_service() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout
    found = []
    for rel in (r for r in out.split("\0") if r):
        if rel.startswith(("tests/", "submodules/")):
            continue
        p = ROOT / rel
        if p.suffix not in _TEXT_SUFFIXES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "qkdnetsim" in text.lower():
            found.append(p)
    return sorted(found)


SCANNED = _documents_that_name_the_service()


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
        r"previously|used to (?:say|claim|name)|this line previously|no longer"
        r"|an earlier (?:version|docstring)|said otherwise", re.I)
    WINDOW = 400

    @pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(ROOT)))
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

    # The facade-specific overclaims. Narrow on purpose: "QKD-derived" alone is
    # the right phrase for arnika's output all over this repository, so only
    # the forms that describe THIS server as NS-3's are matched.
    FACADE_OVERCLAIM = re.compile(
        r"qkdnetsim(?:'s)?\s+QKD-derived"
        r"|qkdnetsim\s+network"
        r"|\bNS-3\s+KME\b"
        r"|bug-compatible"
        r"|byte-for-byte\s+ETSI"
        r"|cannot\s+tell\s+whether\s+it\s+is\s+talking\s+to\s+NS-3", re.I)

    @pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(ROOT)))
    def test_no_document_presents_the_facade_as_ns3(self, path: Path) -> None:
        text = _read(path)
        offending = []
        for m in self.FACADE_OVERCLAIM.finditer(text):
            around = text[max(0, m.start() - self.WINDOW): m.end() + self.WINDOW]
            if not self.RETRACTION.search(around):
                offending.append(text[max(0, m.start() - 80): m.end() + 80])
        assert not offending, (
            f"{path.relative_to(ROOT)} presents the Flask facade as NS-3 or as "
            f"serving qkdnetsim's keys:\n  " + "\n  ".join(offending)
        )

    def test_the_facade_patterns_match_the_claims_they_exist_for(self) -> None:
        for claim in ("exposes qkdnetsim's QKD-derived key material",
                      "composite  -- SimQN physical + qkdnetsim network",
                      "proxy to external NS-3 KME (cross-validation)",
                      "behaviour is bug-compatible with the C++ implementation",
                      "a byte-for-byte ETSI 014 compatible HTTP server"):
            assert self.FACADE_OVERCLAIM.search(claim), claim
        for honest in ("arnika installs the QKD-derived PSK",
                       "a Flask facade, not the NS-3 C++ KMS"):
            assert not self.FACADE_OVERCLAIM.search(honest), honest

    def test_the_derived_scope_is_not_vacuous(self) -> None:
        missing = [str(p.relative_to(ROOT)) for p in KNOWN if p not in SCANNED]
        assert not missing, (
            f"the derived scope lost files known to name the service: {missing}. "
            "The derivation broke, or a document stopped naming it.")

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
