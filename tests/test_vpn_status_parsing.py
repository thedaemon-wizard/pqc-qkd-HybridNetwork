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
