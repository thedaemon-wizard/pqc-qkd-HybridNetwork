"""This repository must not claim the QCI-CAT HSM use case it does not implement.

`submodules/arnika`'s README states arnika was developed within EU EUROQCI /
QCI-CAT for the use case "HSM BACKUP USING QKD". This repository vendors arnika
and cites that lineage, so a reader can reasonably assume the use case is
implemented here.

It is not. Reviewed at <https://qci-cat.at/hsm-backup-using-qkd> on 2026-08-28,
the use case is: cryptographic material moved from an HSM to a BACKUP HSM over a
QKD-protected VPN, where the protected link is HA partition synchronisation /
cloning, exercised through the HSMs' PKCS#11 interface.

This project implements the transport half and none of the HSM half. Its claim
is "a WireGuard or IPsec key was rotated from QKD-derived material"; QCI-CAT's
is "HSM key material crossed a QKD-protected link". The first does not imply the
second, and the gap is invisible unless someone states it.

The specific way not to close it: SoftHSM2 emulates a PKCS#11 surface but has no
HA partition cloning and no cross-instance replication -- the actual payload of
the use case. Standing one up and calling the result "HSM backup over QKD" would
manufacture the overstatement this file guards.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = [REPO / "README.md", REPO / "ARCHITECTURE.md"] + \
       sorted((REPO / "docs").rglob("*.md"))
SCOPE = REPO / "docs" / "threat-model.md"


def _tracked_docs():
    return [f for f in DOCS if f.exists()]


def test_nothing_in_the_tree_implements_pkcs11():
    """The premise. If this fails, the scope statement needs rewriting."""
    # Excluding itself: this file names PKCS#11 in order to forbid it, and a
    # guard that counts its own text as the offence can never go green. Third
    # time this trap has appeared in this suite -- see the SELF note in
    # test_every_config_key_is_read_by_something.py.
    SELF = pathlib.Path(__file__).resolve()
    hits = []
    for pat in ("*.py", "*.go", "*.ts", "*.tsx"):
        for f in REPO.rglob(pat):
            if f.resolve() == SELF:
                continue
            if any(x in f.parts for x in ("node_modules", "submodules", ".venv")):
                continue
            if any(part.startswith(".") for part in f.parts):
                continue
            if re.search(r"pkcs.?11|SoftHSM", f.read_text(encoding="utf-8",
                                                          errors="replace"), re.I):
                hits.append(str(f.relative_to(REPO)))
    assert hits == [], (
        f"something now speaks PKCS#11 ({hits}) -- update docs/threat-model.md "
        f"section 7, which states the tree contains none")


def test_no_document_claims_this_project_backs_up_an_hsm():
    """A sentence putting HSM and this project's own verb together."""
    offenders = []
    for f in _tracked_docs():
        if f == SCOPE:
            continue           # the scope statement names it in order to deny it
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if "hsm" not in low:
                continue
            # "out of scope", "not implemented" and the like are the honest uses.
            if any(w in low for w in ("out of scope", "not implement", "none",
                                      "does not", "no hsm", "without")):
                continue
            offenders.append(f"{f.relative_to(REPO)}:{n}: {line.strip()[:90]}")
    assert offenders == [], (
        "these mention HSM without disclaiming it; this project implements no "
        f"HSM, PKCS#11 or partition cloning: {offenders}")


def test_the_scope_boundary_is_written_down():
    """It is only a boundary if someone can read it."""
    assert SCOPE.exists()
    txt = SCOPE.read_text(encoding="utf-8")
    for needed in ("HSM BACKUP USING QKD", "PKCS#11", "partition",
                   "does not imply", "SoftHSM"):
        assert needed in txt, f"the scope section no longer states {needed!r}"


def test_the_licence_position_is_recorded():
    """qci-cat.at publishes no terms, so nothing may be reproduced from it."""
    txt = SCOPE.read_text(encoding="utf-8")
    assert "no licence terms" in txt.lower() or "publishes no licence" in txt.lower()
    assert "cited by URL" in txt or "cited by url" in txt.lower()
