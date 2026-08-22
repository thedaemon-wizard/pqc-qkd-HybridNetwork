"""The word "PSK" means two opposite things here, and both must be labelled.

`docs/vici-ppk.md` argues at length that a PSK cannot carry post-quantum
confidentiality, and moves the IPsec lane to an RFC 8784 PPK. That is correct
for the **IKEv2** PSK, which enters only the `AUTH` payload and never
`SKEYSEED`.

WireGuard's `PresharedKey` is the opposite: it is mixed into the Noise_IKpsk2
chaining key, so it does contribute to the transport keys, which makes it
mechanically the analogue of the PPK rather than of the IKEv2 PSK. Rosenpass
says so in its own vendored README -- supplying WireGuard through "the PSK
feature" is what gives the hybrid security property.

`/e2e` and `/paper-flow` model the WireGuard lane. Both used the bare word
"PSK", so a reader coming from vici-ppk.md would reasonably conclude those
pages demonstrate the construction that document argues against. The
implementation was always right; the vocabulary was not. `/vpn` was the worst
case, presenting "arnika derives a 32 B PSK" and `SK_d = prf+(PPK, SK_d')` on
one page with nothing to say they are different mechanisms.

This test keeps the qualification attached. It is a wording check, which is
usually a bad idea -- but the failure here IS a wording failure, and it was
reported by a reader rather than caught by anything.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "services" / "webui-frontend" / "src"

# Files that show a PSK to the user for the WireGuard lane, and so must say
# which kind it is.
WIREGUARD_LANE = [
    FRONTEND / "pages" / "QuantumSecureE2E.tsx",
    FRONTEND / "lib" / "sim" / "paperSim.ts",
    FRONTEND / "pages" / "VpnProtocols.tsx",
]


@pytest.mark.parametrize("path", WIREGUARD_LANE, ids=lambda p: p.name)
def test_the_wireguard_lane_says_which_psk_it_means(path: Path):
    text = path.read_text(encoding="utf-8")
    assert "PSK" in text or "preshared" in text.lower(), (
        f"{path.name} no longer mentions a PSK; if the panel moved, move this "
        "check with it rather than deleting it."
    )
    qualified = (
        "WireGuard preshared key" in text
        or "WireGuard PSK" in text
        or "WireGuard</b> preshared key" in text
        or "WireGuard&apos;s preshared key" in text
    )
    assert qualified, (
        f"{path.name} shows a PSK for the WireGuard lane without saying so. "
        "Unqualified, it reads as the IKEv2 PSK that docs/vici-ppk.md argues "
        "cannot carry confidentiality -- the opposite of what this lane does."
    )


def test_the_two_meanings_are_explained_in_one_place():
    """A qualifier in the UI is not enough on its own; it needs somewhere to point."""
    doc = (ROOT / "docs" / "vici-ppk.md").read_text(encoding="utf-8")
    assert "Noise_IKpsk2" in doc, (
        "docs/vici-ppk.md no longer explains that WireGuard's preshared key "
        "enters the Noise chaining key. Without that, the document's PSK "
        "argument reads as applying to the WireGuard lane too."
    )
    for token in ("RFC 7296", "RFC 8784"):
        assert token in doc, f"{token} is no longer cited alongside the comparison"
