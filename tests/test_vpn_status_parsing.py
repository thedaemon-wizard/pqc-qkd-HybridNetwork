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
    """A classical proposal now reports False. It used to report None.

    This assertion read `is None`, and that was the defect rather than the
    contract. `"ML_KEM" in (proposal or "") or None` can only ever yield True
    or None -- so "we read the proposal and there is no ML-KEM in it" produced
    exactly the same value as "we never got a proposal at all". The test
    encoded the collapse instead of catching it, which is part of why nothing
    flagged it for so long.

    The distinction is the entire point of the field: a lane that established
    with a CLASSICAL-ONLY proposal is a finding; a lane that has not come up
    yet is not. See test_pq_key_exchange_can_now_say_no.
    """
    sas = SAS_ESTABLISHED.replace("/ML_KEM_768", "")
    st = _parse_ipsec_sas(sas, CONNS_PPK)
    assert st["proposal"] == "AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256"
    assert st["pq_key_exchange"] is False
    # ...and the genuine unknown stays distinctly expressible.
    assert _parse_ipsec_sas("", "")["pq_key_exchange"] is None


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


# --------------------------------------------------------------------------
# ESP counters, PPK USE, and the both-ends aggregates
#
# Three checklist rows (2.3, 2.11, 2.14) said "Measured on the public host".
# The measurements were real, but taken over SSH with swanctl -- the public API
# exposed no ESP byte/packet fields and a single `ppk_required` boolean sourced
# only from alice-ipsec, so a reader with a browser could reproduce none of the
# three.
#
# The fixtures below are verbatim `swanctl --list-sas` output captured from the
# running demo's alice-ipsec and bob-ipsec on 2026-08-27. Note the SPIs: alice's
# `out` is bob's `in` and vice versa. That pairing is the one fact here that a
# single end could not fabricate.
# --------------------------------------------------------------------------
_parse_child_sas = importlib.import_module("webui_backend_app.main")._parse_child_sas
_both_ends = importlib.import_module("webui_backend_app.main")._both_ends

SAS_ALICE = """\
pqcqkd-vpn: #6261, ESTABLISHED, IKEv2, 05f7a6680d8a2024_i* 5c08b6797100ef13_r
  local  'alice@pqcqkd.local' @ 10.30.0.20[4500]
  remote 'bob@pqcqkd.local' @ 10.30.0.21[4500]
  AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK
  established 20s ago, reauth in 266s
  tunnel: #6261, reqid 1, INSTALLED, TUNNEL-in-UDP, ESP:AES_GCM_16-256
    installed 20s ago, rekeying in 3288s, expires in 3940s
    in  cb1df209,   1680 bytes,    20 packets
    out c15c9a27,    840 bytes,    10 packets
    local  10.30.0.20/32
    remote 10.30.0.21/32
"""

SAS_BOB = """\
pqcqkd-vpn: #6261, ESTABLISHED, IKEv2, 05f7a6680d8a2024_i 5c08b6797100ef13_r*
  local  'bob@pqcqkd.local' @ 10.30.0.21[4500]
  remote 'alice@pqcqkd.local' @ 10.30.0.20[4500]
  AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK
  established 21s ago
  tunnel: #6258, reqid 1, INSTALLED, TUNNEL-in-UDP, ESP:AES_GCM_16-256
    installed 21s ago, rekeying in 3262s, expires in 3939s
    in  c15c9a27,    840 bytes,    10 packets
    out cb1df209,   1680 bytes,    20 packets
    local  10.30.0.21/32
    remote 10.30.0.20/32
"""

# A rekey window: TWO tunnel blocks under ONE IKE_SA. This is why the parser
# has to be a line-scanning state machine -- pairing the Nth `in` with the Nth
# `out` across the whole document mixes the old SA's inbound counters with the
# new SA's outbound ones.
SAS_REKEYING = """\
pqcqkd-vpn: #7, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK
  established 12s ago
  tunnel: #7, reqid 1, REKEYING, TUNNEL, ESP:AES_GCM_16-256
    installed 3500s ago, rekeying in 0s
    in  11111111,  99000 bytes,   900 packets
    out 22222222,  98000 bytes,   880 packets
    local  10.30.0.20/32
    remote 10.30.0.21/32
  tunnel: #8, reqid 1, INSTALLED, TUNNEL, ESP:AES_GCM_16-256
    installed 1s ago, rekeying in 3599s
    in  33333333,      0 bytes,     0 packets
    out 44444444,      0 bytes,     0 packets
    local  10.30.0.20/32
    remote 10.30.0.21/32
"""

# charon omits the line it has nothing for. An absent direction must be None.
SAS_INBOUND_ONLY = """\
pqcqkd-vpn: #1, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK
  established 5s ago
  tunnel: #1, reqid 1, INSTALLED, TUNNEL, ESP:AES_GCM_16-256
    installed 5s ago, rekeying in 3599s
    in  aabbccdd,    512 bytes,     4 packets
    local  10.30.0.20/32
"""

# The same lane WITHOUT a PPK: charon establishes, negotiates ML-KEM, and
# silently falls back to NO_PPK_AUTH. The proposal simply lacks the /PPK
# suffix. This is the case the whole project exists to make visible.
SAS_NO_PPK = SAS_ALICE.replace("/KE1_ML_KEM_768/PPK", "/KE1_ML_KEM_768")

CONNS_BOB = """\
bypass-arnika-control: IKEv1/2, no reauthentication, rekeying every 14400s
  local:  %any[500]
  remote: %any[500]
  control-to-peer: PASS, no rekeying

pqcqkd-vpn: IKEv2, no reauthentication, no rekeying
  ppk: ppk-qkd@pqcqkd.local, required
  local:  10.30.0.21[500]
  remote: 10.30.0.20[500]
"""


def test_esp_counters_are_parsed_from_output_we_already_fetched():
    """Rows 2.3 and 2.11 become browser-reproducible with zero extra execs."""
    kids = _parse_child_sas(SAS_ALICE)
    assert len(kids) == 1
    k = kids[0]
    assert k["in"] == {"spi": "cb1df209", "bytes": 1680, "packets": 20}
    assert k["out"] == {"spi": "c15c9a27", "bytes": 840, "packets": 10}
    assert k["state"] == "INSTALLED"
    assert k["esp_proposal"] == "AES_GCM_16-256"
    assert k["reqid"] == 1


def test_a_rekey_window_keeps_its_two_blocks_separate():
    """The reason this is a state machine and not two findall()s.

    Two `tunnel:` blocks under one IKE_SA. A whole-document scan would pair
    in[0] with out[0] and in[1] with out[1] -- which happens to be right here,
    but only because both blocks are complete. Add an inbound-only block and
    the pairing shifts silently. What must hold is that each block keeps ITS
    OWN counters, which is what is asserted.
    """
    kids = _parse_child_sas(SAS_REKEYING)
    assert len(kids) == 2
    old, new = kids
    assert old["state"] == "REKEYING"
    assert old["in"]["spi"] == "11111111" and old["out"]["spi"] == "22222222"
    assert old["in"]["bytes"] == 99000
    assert new["state"] == "INSTALLED"
    assert new["in"]["spi"] == "33333333" and new["out"]["spi"] == "44444444"
    # The new SA has genuinely carried nothing yet. 0 here is a measurement.
    assert new["out"]["bytes"] == 0


def test_an_absent_direction_is_none_not_zero():
    """charon omits the line; "no outbound line" is not "zero bytes sent"."""
    k = _parse_child_sas(SAS_INBOUND_ONLY)[0]
    assert k["in"]["bytes"] == 512
    assert k["out"] is None, (
        "an omitted direction became 0, so a half-installed SA now reads as an "
        "idle one"
    )


def test_ppk_use_is_read_from_the_sa_not_from_the_config():
    """/PPK on the proposal line is per-SA proof the PPK was applied.

    strongSwan 6.0.7:
      sa/ike_sa.h:258        COND_PPK -- "A Postquantum Preshared Key was used
                             when this IKE_SA was created"
      vici/vici_query.c:640  add_condition(b, ike_sa, "ppk", COND_PPK)
      swanctl/list_sas.c:322 if ppk == yes -> printf("/PPK")
      ikev2/tasks/ike_auth.c:1187  set inside apply_ppk(), only AFTER
                             derive_ike_keys_ppk() succeeded

    main.py's comment used to say charon does not report this over VICI. It
    does, in output the function was already being handed. This project's own
    CI job asserts on the same "/PPK" marker.
    """
    used = _parse_ipsec_sas(SAS_ALICE, CONNS_BOB)
    assert used["ppk_used"] is True
    assert used["ppk_required"] is True          # configuration, separate fact

    # Established, ML-KEM negotiated, PPK silently absent -- charon fell back
    # to NO_PPK_AUTH. Configuration still says "required"; use says no.
    fell_back = _parse_ipsec_sas(SAS_NO_PPK, CONNS_BOB)
    assert fell_back["status"] == "established"
    assert fell_back["pq_key_exchange"] is True
    assert fell_back["ppk_used"] is False, (
        "a lane that established WITHOUT the PPK reports the same as one that "
        "used it; that is the exact failure this project exists to surface"
    )
    assert fell_back["ppk_required"] is True


def test_pq_key_exchange_can_now_say_no():
    """It could previously say True or None and never False.

    `"ML_KEM" in (proposal or "") or None` yields None for a proposal WITHOUT
    ML-KEM -- the same value it yields when there is no proposal at all. So "we
    read it and there is no ML-KEM" was indistinguishable from "we never
    looked", and both render as an em dash.
    """
    classical = SAS_ALICE.replace("/KE1_ML_KEM_768/PPK", "/PPK")
    assert _parse_ipsec_sas(classical, CONNS_BOB)["pq_key_exchange"] is False
    # No SA at all -> genuinely unknown.
    assert _parse_ipsec_sas("", "")["pq_key_exchange"] is None


def test_the_spis_pair_across_the_two_ends():
    """alice.out == bob.in and alice.in == bob.out.

    The one aggregate here a single end could not fabricate: an SPI is chosen
    by the receiver and echoed by the sender, so a match proves both containers
    describe the SAME pair of ESP SAs rather than two unrelated tunnels that
    both happen to be up.
    """
    a = _parse_ipsec_sas(SAS_ALICE, CONNS_BOB)
    b = _parse_ipsec_sas(SAS_BOB, CONNS_BOB)
    agg = _both_ends(a, b)
    assert agg["spi_paired"] is True
    assert agg["ppk_used_both_ends"] is True
    assert agg["ppk_required_both_ends"] is True
    assert agg["pq_key_exchange_both_ends"] is True

    # Two tunnels that are each up but not to each other.
    unrelated = SAS_BOB.replace("c15c9a27", "deadbeef").replace("cb1df209", "feedface")
    assert _both_ends(a, _parse_ipsec_sas(unrelated, CONNS_BOB))["spi_paired"] is False


def test_one_end_unknown_makes_the_aggregate_unknown_not_false():
    """`null && true` is falsy in JS, which is why this is computed here.

    A client-side `a.ppk_used && b.ppk_used` would render "not in use" when one
    end simply failed to answer -- turning an unknown into a negative finding.
    """
    a = _parse_ipsec_sas(SAS_ALICE, CONNS_BOB)
    down = _ipsec_unknown("error")
    agg = _both_ends(a, down)
    assert agg["ppk_used_both_ends"] is None
    assert agg["ppk_required_both_ends"] is None
    assert agg["spi_paired"] is None, (
        "an unreachable peer must not read as an unpaired tunnel"
    )
    # And the genuine negative must still be expressible.
    assert _both_ends(a, _parse_ipsec_sas(SAS_NO_PPK, CONNS_BOB))["ppk_used_both_ends"] is False


def test_the_conns_parse_is_not_fooled_by_an_earlier_connection():
    """bob-ipsec lists `bypass-arnika-control` before `pqcqkd-vpn`."""
    st = _parse_ipsec_sas(SAS_BOB, CONNS_BOB)
    assert st["ppk_id"] == "ppk-qkd@pqcqkd.local"
    assert st["ppk_required"] is True
