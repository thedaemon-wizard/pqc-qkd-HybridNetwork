"""Tests for the IPsec lane status parser.

These guard against the defect this parser replaced: `/api/vpn/protocols` used
to return a hardcoded proposal string and a literal "via swanctl" handshake
time, so the WebUI advertised an RFC 9370 ML-KEM hybrid tunnel regardless of
what charon had actually negotiated -- including when charon was not running.

The fixtures below are verbatim `swanctl` output from the pinned strongSwan
6.0.7 image (nodes/strongswan/Dockerfile).
"""

from __future__ import annotations

import importlib

import pytest
from conftest import load_service_app

load_service_app("webui-backend", "webui_backend_app")
_parse_ipsec_sas = importlib.import_module("webui_backend_app.main")._parse_ipsec_sas

# Real output shape: `swanctl --list-conns` for the PPK-enabled connection.
CONNS_PPK = """\
pqcqkd-vpn: IKEv2, reauthentication every 30s, no rekeying
  ppk: ppk-qkd@pqcqkd.local, required
  local:  10.30.0.20[500]
  remote: 10.30.0.21[500]
  local pre-shared key authentication:
    id: alice@pqcqkd.local
  remote pre-shared key authentication:
    id: bob@pqcqkd.local
  tunnel: TUNNEL, rekeying every 3600s
    local:  10.30.0.20/32
    remote: 10.30.0.21/32
"""

SAS_ESTABLISHED = """\
pqcqkd-vpn: #1, ESTABLISHED, IKEv2, 8f3ad9c1b2e4f5a6_i* c1d2e3f4a5b60718_r
  local  'alice@pqcqkd.local' @ 10.30.0.20[500]
  remote 'bob@pqcqkd.local' @ 10.30.0.21[500]
  AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/ML_KEM_768
  established 12s ago, reauth in 18s
  tunnel: #1, INSTALLED, TUNNEL, ESP:AES_GCM_16-256/ECP_256/ML_KEM_768
    installed 12s ago, rekeying in 3421s
    in  c1a2b3c4,  0 bytes,     0 packets
    out d4e5f6a7,  0 bytes,     0 packets
    local  10.30.0.20/32
    remote 10.30.0.21/32
"""


def test_established_sa_reports_negotiated_proposal():
    st = _parse_ipsec_sas(SAS_ESTABLISHED, CONNS_PPK)
    assert st["status"] == "established"
    assert st["active_sa"] == 1
    # Parsed from charon, not a constant.
    assert st["proposal"] == "AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/ML_KEM_768"
    assert st["last_handshake"] == "12s ago"


def test_rfc9370_and_rfc8784_reported_separately():
    """ML-KEM in the proposal must not be taken as evidence of a PPK.

    They are different mechanisms: RFC 9370 strengthens the key exchange,
    RFC 8784 mixes the QKD key into SK_d. Conflating them is exactly the
    overclaim this endpoint used to make.
    """
    st = _parse_ipsec_sas(SAS_ESTABLISHED, CONNS_PPK)
    assert st["pq_key_exchange"] is True
    assert st["ppk_id"] == "ppk-qkd@pqcqkd.local"
    assert st["ppk_required"] is True

    # ML-KEM negotiated but no PPK configured -> PPK fields must be empty.
    conns_no_ppk = CONNS_PPK.replace("  ppk: ppk-qkd@pqcqkd.local, required\n", "")
    st = _parse_ipsec_sas(SAS_ESTABLISHED, conns_no_ppk)
    assert st["pq_key_exchange"] is True
    assert st["ppk_id"] is None
    assert st["ppk_required"] is None


def test_ppk_optional_is_not_reported_as_required():
    """`ppk_required = no` permits a silent NO_PPK_AUTH downgrade."""
    conns = CONNS_PPK.replace(", required", ", optional")
    st = _parse_ipsec_sas(SAS_ESTABLISHED, conns)
    assert st["ppk_id"] == "ppk-qkd@pqcqkd.local"
    assert st["ppk_required"] is False


def test_classical_only_sa_does_not_claim_post_quantum():
    sas = SAS_ESTABLISHED.replace("/ML_KEM_768", "")
    st = _parse_ipsec_sas(sas, CONNS_PPK)
    assert st["proposal"] == "AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256"
    assert st["pq_key_exchange"] is None


@pytest.mark.parametrize("sas", ["", "   \n"])
def test_no_daemon_output_is_absent_not_established(sas):
    """A dead charon must read as 'absent', never as a healthy tunnel."""
    st = _parse_ipsec_sas(sas, "")
    assert st["status"] == "absent"
    assert st["active_sa"] == 0
    assert st["proposal"] is None
    assert st["last_handshake"] is None


def test_connecting_sa_is_running_not_established():
    sas = "pqcqkd-vpn: #1, CONNECTING, IKEv2\n  local  'alice@pqcqkd.local' @ 10.30.0.20[500]\n"
    st = _parse_ipsec_sas(sas, CONNS_PPK)
    assert st["status"] == "running"
    assert st["active_sa"] == 0


def test_multiple_established_sas_are_counted():
    st = _parse_ipsec_sas(SAS_ESTABLISHED + SAS_ESTABLISHED, CONNS_PPK)
    assert st["active_sa"] == 2


# The failure mode the exit-code check exists for: charon is not answering, so
# swanctl writes an error and exits non-zero. Verbatim from a container whose
# charon had died.
SWANCTL_ERROR = """\
connecting to 'unix:///var/run/charon.vici' failed: No such file or directory
unable to connect to daemon, is it running?
"""


def test_swanctl_error_text_would_otherwise_read_as_running():
    """Error output is non-empty, so a naive parse calls a dead charon "running".

    This documents WHY app.main checks exec_run's exit code rather than
    handing whatever came back to the parser. The parser is given only the
    text, so on its own it cannot tell an error from real output -- it decides
    "running" purely because the string is non-empty. That is exactly the
    "healthy while doing nothing" mode the strongSwan lane rewrite exists to
    eliminate, and it would have been reproduced in the status API.
    """
    out = _parse_ipsec_sas(SWANCTL_ERROR, "")
    assert out["status"] == "running", (
        "fixture no longer reproduces the trap this guard is about; if the "
        "parser learned to detect error text, tighten the assertion instead "
        "of deleting the test"
    )
    # And it invents nothing, which is why the exit-code check upstream is the
    # right place to catch this rather than pattern-matching error strings.
    assert out["active_sa"] == 0
    assert out["proposal"] is None
    assert out["ppk_id"] is None
    assert out["pq_key_exchange"] is None


# --------------------------------------------------------------------------
# WireGuard lane
#
# The IPsec branch above has parsed every field from the daemon since it was
# written. The WireGuard branch sixteen lines above it in main.py did not: it
# returned
#
#     "proposal":       "ChaCha20-Poly1305 + Noise + PSK"
#     "last_handshake": "via wg show"
#
# The second is a description of WHERE a value would come from, shipped as the
# value, and both went out over the public API -- confirmed by fetching
# /api/vpn/protocols from the deployment on 2026-08-27. It also decided status
# purely from a substring, so a non-zero exit code degraded to "running", which
# VpnProtocols.tsx renders green.
#
# WG_SHOW is verbatim `docker exec alice wg show wg0` output from the running
# demo, with the public keys replaced by same-length placeholders.
# --------------------------------------------------------------------------
_parse_wg = importlib.import_module("webui_backend_app.main")._parse_wg
_wg_unknown = importlib.import_module("webui_backend_app.main")._wg_unknown
_ipsec_unknown = importlib.import_module("webui_backend_app.main")._ipsec_unknown
_wg_handshake_seconds = importlib.import_module(
    "webui_backend_app.main"
)._wg_handshake_seconds

WG_SHOW = """\
interface: wg0
  public key: PUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUB=
  private key: (hidden)
  listening port: 51820

peer: PUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUB=
  preshared key: (hidden)
  endpoint: 10.30.0.11:51821
  allowed ips: 10.0.0.2/32
  latest handshake: 1 minute, 32 seconds ago
  transfer: 726.21 KiB received, 980.89 KiB sent
  persistent keepalive: every 25 seconds
"""

# A peer with no PSK installed omits the line entirely -- wireguard-tools
# src/show.c guards that printf with `peer->flags & WGPEER_HAS_PRESHARED_KEY`.
# That is what makes peers_with_psk a measurement rather than a restatement.
WG_SHOW_NO_PSK = WG_SHOW.replace("  preshared key: (hidden)\n", "")

# Before the first handshake, `latest handshake:` is absent too (the printf is
# guarded on a non-zero handshake time).
WG_SHOW_NO_HANDSHAKE = WG_SHOW.replace(
    "  latest handshake: 1 minute, 32 seconds ago\n", ""
)


def test_wg_reports_no_proposal_because_there_is_none_to_report():
    """The constant that used to live here, and why nothing replaces it.

    WireGuard negotiates no cipher suite: ChaCha20-Poly1305 and Noise_IKpsk2 are
    fixed by the protocol and `wg show` reports neither. Any string in this
    field is invented. Moving it server-side would only change which file says
    it as though it were measured.
    """
    out = _parse_wg(WG_SHOW)
    assert out["proposal"] is None
    assert "ChaCha20" not in str(out), (
        "a cipher-suite constant is back in the WireGuard status; there is "
        "nothing in `wg show` to derive one from"
    )


def test_wg_parses_the_handshake_age_it_used_to_describe():
    out = _parse_wg(WG_SHOW)
    assert out["last_handshake_s"] == 92          # 1 minute + 32 seconds
    assert out["last_handshake"] == "92s ago"
    assert out["status"] == "established"
    assert out["active_sa"] == 1


def test_wg_counts_peers_with_a_psk_installed():
    """The observable security fact that replaces the invented proposal."""
    assert _parse_wg(WG_SHOW)["peers_with_psk"] == 1
    assert _parse_wg(WG_SHOW)["peers"] == 1

    without = _parse_wg(WG_SHOW_NO_PSK)
    assert without["peers"] == 1
    assert without["peers_with_psk"] == 0, (
        "a peer carrying no QKD-derived PSK must be distinguishable from one "
        "that does; the tunnel comes up either way, which is what makes the "
        "loss silent"
    )


def test_wg_before_the_first_handshake_is_running_not_established():
    out = _parse_wg(WG_SHOW_NO_HANDSHAKE)
    assert out["status"] == "running"
    assert out["active_sa"] == 0
    assert out["last_handshake"] is None
    assert out["last_handshake_s"] is None


def test_wg_zero_components_are_omitted_so_positions_cannot_be_trusted():
    """show.c's pretty_time() prints only non-zero components.

        if (years) ... if (days) ... if (hours) ... if (minutes) ... if (seconds)

    So "2 days, 5 seconds ago" is a legal rendering, and a parser reading the
    second number as minutes would report 2 days 5 minutes. Units are matched by
    name for exactly this reason.
    """
    assert _wg_handshake_seconds("2 days, 5 seconds ago") == 2 * 86400 + 5
    assert _wg_handshake_seconds("1 minute, 32 seconds ago") == 92
    assert _wg_handshake_seconds("3 hours ago") == 10800
    # Singular at 1, plural otherwise -- both must parse.
    assert _wg_handshake_seconds("1 second ago") == 1
    assert _wg_handshake_seconds("2 seconds ago") == 2
    # A year is 365 * 24 * 60 * 60 in show.c, not a calendar year.
    assert _wg_handshake_seconds("1 year ago") == 365 * 86400


def test_wg_now_is_zero_and_unreadable_is_none():
    """0 is a measurement; None is the absence of one. They must not collide.

    show.c renders a zero-second age as the literal "Now", and renders a
    backwards clock as a sentence with no number in it at all -- in that case
    the age is genuinely unknown, not small.
    """
    assert _wg_handshake_seconds("Now") == 0
    assert _wg_handshake_seconds(
        "(System clock wound backward; connection problems may ensue.)"
    ) is None
    assert _wg_handshake_seconds("") is None
    assert _wg_handshake_seconds("some future format we do not know") is None


def test_wg_and_ipsec_each_answer_with_one_key_set():
    """The invariant main.py's comment claimed while the WG branch broke it.

    Its default path was a two-key dict, so "same keys as the success path" held
    for the IPsec error path only. Both templates are now the single definition
    and every return path is seeded from one, so this compares shapes rather
    than trusting a comment.
    """
    assert set(_parse_wg(WG_SHOW)) == set(_wg_unknown("absent"))
    assert set(_parse_wg(WG_SHOW_NO_PSK)) == set(_wg_unknown("error"))
    # peers == 0 takes an early return; it must not skip a key either.
    assert set(_parse_wg("interface: wg0\n")) == set(_wg_unknown("running"))
    assert set(_parse_ipsec_sas(SAS_ESTABLISHED, CONNS_PPK)) == set(_ipsec_unknown("absent"))
    assert set(_parse_ipsec_sas(SWANCTL_ERROR, "")) == set(_ipsec_unknown("error"))


def test_wg_unknown_measures_nothing():
    """Every data field None, so "error" cannot carry a leftover number."""
    err = _wg_unknown("error")
    assert err["status"] == "error"
    for key in ("active_sa", "proposal", "last_handshake", "last_handshake_s",
                "peers", "peers_with_psk"):
        assert err[key] is None, f"{key} should be None in the unknown template"
