"""The WireGuard lane's second interface, wg1, is reported beside wg0.

Release 0.2.0 gives each WireGuard node two interfaces, the layering of
arXiv:2604.05599:

  * wg0, the hop tunnel. arnika writes its preshared key: HKDF-SHA3-256 over
    the QKD key and a PQC-HPKE key that arnika agrees with its peer;
  * wg1, the end-to-end data tunnel. Its peer endpoint is the peer's wg0
    address, so it runs inside wg0, and Rosenpass writes its preshared key.

Before this, the API could only show wg0. A reader of /api/wg/{node} or /vpn
would have seen a healthy hop tunnel and nothing at all about the tunnel that
carries the data, so a wg1 that never came up, or whose handshake never
completed because its two ends did not hold the same Rosenpass key, would have
been invisible.

What shows that wg1 is keyed is its handshake, not its `preshared key:` line.
Since release 0.2.0 the node entrypoint installs a random placeholder PSK on
every wg0 and wg1 peer when it creates it, so the line is present before
Rosenpass (or, on wg0, arnika) has written anything. A handshake completes only
when both ends hold the same key, and the placeholders of the two ends never
match. So `peers_with_psk` is still reported, but no test here treats it as
evidence of keying. What is pinned here:

  1. `GET /api/wg/{node}` keeps its wg0 fields at the top level and adds
     `data_tunnel` for wg1 with the same keys, each with its `psk_source`;
  2. wg1 goes through the same redactor, and through the non-dump command,
     because its preshared key is as secret as wg0's;
  3. a wg1 failure is reported in place and does not turn the wg0 reading into
     a 404, and it never becomes an invented rc or output;
  4. `GET /api/wg/{node}` is cached per node for WG_SHOW_TTL_S, 404s included,
     and says when it was sampled, because each sample costs two execs on a
     public GET the rate limiter does not meter; the 404 detail, cached or
     not, is cut at ERROR_TEXT_MAX_CHARS;
  5. `GET /api/vpn/protocols` carries wg1 under `wireguard.data_tunnel` in the
     same key set as wg0, while the flat fields stay wg0's, and a wg1 whose
     peers all carry a PSK but none has handshaked does not read as
     established;
  6. each interface reports, beside `active_sa` (peers that EVER handshaked
     since the interface came up, a count that cannot fall while the peer
     exists because `latest handshake:` is never cleared), `peers_fresh`:
     peers whose latest handshake is younger than WireGuard's
     REJECT_AFTER_TIME, the age at which WireGuard refuses a session key, with
     that limit as `fresh_within_s`;
  7. `/api/topology` draws both alice-bob tunnels;
  8. the rotation counter /vpn shows still counts the VICI adapter's line
     after the arnika pin moved to slog, where the line arrives as the quoted
     `msg` of a key=value record.

The wg1 fixture is CONSTRUCTED from the deployment defaults (wg1 10.0.1.1 and
10.0.1.2, UDP 51830 and 51831, endpoint on the peer's wg0 address). It is not
captured output: no deployment ran wg1 when this file was written. The wg0
fixture is the captured one from tests/test_wg_endpoint_redacts_secrets.py.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

load_service_app("webui-backend", "webui_backend_app")
_main = importlib.import_module("webui_backend_app.main")

# Placeholder keys, real shape: 43 base64 characters + '='.
_PRIV = "PRIVpvtKEYplaceholder0000000000000000000000="
_PSK = "PSKpskKEYplaceholder00000000000000000000000="
_PUB_A0 = "PUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUB="
_PUB_B0 = "PUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUB="
_PUB_A1 = "PUBcPUBcPUBcPUBcPUBcPUBcPUBcPUBcPUBcPUBcPUB="
_PUB_B1 = "PUBdPUBdPUBdPUBdPUBdPUBdPUBdPUBdPUBdPUBdPUB="

# alice's wg0, captured 2026-08-27 (see test_wg_endpoint_redacts_secrets.py).
WG0 = f"""\
interface: wg0
  public key: {_PUB_A0}
  private key: (hidden)
  listening port: 51820

peer: {_PUB_B0}
  preshared key: (hidden)
  endpoint: 10.30.0.11:51821
  allowed ips: 10.0.0.2/32
  latest handshake: 1 minute, 32 seconds ago
  transfer: 726.21 KiB received, 980.89 KiB sent
  persistent keepalive: every 25 seconds
"""

# alice's wg1, constructed: endpoint = bob's wg0 address and bob's wg1 port.
# Its handshake age differs from wg0's on purpose, so a test can tell which
# interface a field came from.
WG1 = f"""\
interface: wg1
  public key: {_PUB_A1}
  private key: (hidden)
  listening port: 51830

peer: {_PUB_B1}
  preshared key: (hidden)
  endpoint: 10.0.0.2:51831
  allowed ips: 10.0.1.2/32
  latest handshake: 12 seconds ago
  transfer: 1.20 KiB received, 1.53 KiB sent
"""

# wg1 with no preshared key. wg(8) omits the `preshared key:` line entirely for
# a peer that has none. A parser case only: since release 0.2.0 the entrypoint
# gives every peer a placeholder PSK at creation, so a deployed peer always has
# the line, and its absence is not the failure this lane is watched for.
WG1_NO_PSK = WG1.replace("  preshared key: (hidden)\n", "")

# wg1 as it looks before Rosenpass has keyed it: the peer carries the
# entrypoint's random placeholder PSK, so the `preshared key:` line is there,
# but no handshake has completed, so `latest handshake:` is absent (show.c
# prints it only for a non-zero handshake time). The initiations the peer sent
# still count as bytes sent. Constructed, like WG1.
WG1_PLACEHOLDER_ONLY = (
    WG1.replace("  latest handshake: 12 seconds ago\n", "")
       .replace("  transfer: 1.20 KiB received, 1.53 KiB sent\n",
                "  transfer: 0 B received, 1.48 KiB sent\n")
)

# wg1 after its two ends diverged: the handshake that last succeeded is still
# listed, because show.c prints `latest handshake:` for any non-zero handshake
# time and the kernel never clears it while the peer exists, but it is exactly
# REJECT_AFTER_TIME old (show.c renders 180 s as "3 minutes"), so the session
# key it produced is refused. Constructed, like WG1.
WG1_STALE = WG1.replace("  latest handshake: 12 seconds ago\n",
                        "  latest handshake: 3 minutes ago\n")

# One second younger than that: the last age at which the key is still used.
WG1_LAST_FRESH_SECOND = WG1.replace("  latest handshake: 12 seconds ago\n",
                                    "  latest handshake: 2 minutes, 59 seconds ago\n")

# show.c's rendering for a handshake time in the future. The age is unknown,
# so the peer is neither fresh nor stale as far as the API can tell.
WG1_CLOCK_BACKWARD = WG1.replace(
    "  latest handshake: 12 seconds ago\n",
    "  latest handshake: (System clock wound backward; connection problems may ensue.)\n")

# What wireguard-tools prints for an interface that does not exist (show.c's
# perror), e.g. on a node deployed before release 0.2.0.
WG1_ABSENT = "Unable to access interface: No such device\n"

# The dump form of wg1, as a leak would look.
WG1_DUMP = (
    f"{_PRIV}\t{_PUB_A1}\t51830\toff\n"
    f"{_PUB_B1}\t{_PSK}\t10.0.0.2:51831\t10.0.1.2/32\t1787829729\t1229\t1567\toff\n"
)


class _Node:
    """A container whose `exec_run` answers per command, and records each one."""

    def __init__(self, answers: dict[str, tuple[int, str] | Exception], seen: list[str]):
        self.answers = answers
        self.seen = seen

    def exec_run(self, cmd):
        self.seen.append(cmd)
        a = self.answers[cmd]
        if isinstance(a, Exception):
            raise a
        rc, text = a
        return rc, text.encode()


class _Docker:
    """Only `alice` and `bob` exist; any other lookup raises, as Docker's does."""

    def __init__(self, answers):
        self.seen: list[str] = []
        outer = self

        class _Containers:
            def get(self, name):
                if name not in ("alice", "bob"):
                    raise LookupError(f"no such container: {name}")
                return _Node(answers, outer.seen)

        self.containers = _Containers()


def _answers(wg1=(0, WG1)):
    return {_main.WG_SHOW_CMD: (0, WG0), _main.WG_DATA_SHOW_CMD: wg1}


def _get(path: str, fake: _Docker):
    prev = getattr(_main.app.state, "docker", None)
    try:
        with TestClient(_main.app) as client:
            # TestClient's lifespan re-runs startup, which resets the client.
            _main.app.state.docker = fake
            return client.get(path)
    finally:
        _main.app.state.docker = prev


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    monkeypatch.setattr(_main, "_vpn_sample", {})
    monkeypatch.setattr(_main, "_rotation_sample", {})
    # /api/wg/{node} caches in the shared pure cache under `wg:<node>`.
    monkeypatch.setattr(_main, "_pure_cache", {})


# Top-level fields of /api/wg/{node} that describe the sample, not wg0.
_SAMPLE_FIELDS = {"data_tunnel", "observed_at", "cache_ttl_s"}


# ---- 1. /api/wg/{node} --------------------------------------------------
def test_the_data_tunnel_command_is_the_non_dump_form():
    """The one-word difference that leaked wg0's keys applies to wg1 too."""
    assert "dump" not in _main.WG_DATA_SHOW_CMD
    assert _main.WG_DATA_SHOW_CMD.split() == ["wg", "show", "wg1"]
    assert _main.WG_SHOW_CMD.split() == ["wg", "show", "wg0"]


def test_the_psk_sources_are_the_ones_the_contract_names():
    assert _main.WG_PSK_SOURCE == {
        "wg0": "arnika: HKDF-SHA3-256(QKD || PQC-HPKE)",
        "wg1": "rosenpass",
    }


@pytest.mark.parametrize("node", ["alice", "bob"])
def test_the_route_reports_wg0_at_the_top_and_wg1_as_the_data_tunnel(node):
    fake = _Docker(_answers())
    body = _get(f"/api/wg/{node}", fake).json()

    # The fields every existing reader relies on keep meaning wg0.
    assert body["node"] == node
    assert body["rc"] == 0
    assert body["output"] == WG0
    assert body["interface"] == "wg0"
    assert body["psk_source"] == "arnika: HKDF-SHA3-256(QKD || PQC-HPKE)"

    dt = body["data_tunnel"]
    assert dt["node"] == node
    assert dt["interface"] == "wg1"
    assert dt["rc"] == 0
    assert dt["output"] == WG1
    assert dt["psk_source"] == "rosenpass"
    assert dt["error"] is None

    # Same keys on both, so one renderer reads either.
    assert set(dt) == set(body) - _SAMPLE_FIELDS
    # Both commands ran, wg0 first, and nothing else was asked.
    assert fake.seen == [_main.WG_SHOW_CMD, _main.WG_DATA_SHOW_CMD]


def test_wg1_goes_through_the_redactor():
    """A wg1 answer shaped like dump is withheld, exactly as wg0's would be."""
    fake = _Docker(_answers(wg1=(0, WG1_DUMP)))
    dt = _get("/api/wg/alice", fake).json()["data_tunnel"]
    assert _PRIV not in dt["output"], "the route emitted wg1's private key"
    assert _PSK not in dt["output"], "the route emitted wg1's preshared key (Rosenpass's key)"
    assert "[withheld]" in dt["output"]


def test_a_missing_wg1_is_reported_with_its_own_rc_and_text():
    """`wg show wg1` exiting 1 is an answer, not something to hide or replace."""
    fake = _Docker(_answers(wg1=(1, WG1_ABSENT)))
    body = _get("/api/wg/alice", fake).json()
    assert body["rc"] == 0 and body["output"] == WG0
    assert body["data_tunnel"]["rc"] == 1
    assert body["data_tunnel"]["output"] == WG1_ABSENT


def test_a_wg1_exec_failure_keeps_the_wg0_reading():
    """No 404 for a node whose wg0 answered, and no invented rc or output."""
    fake = _Docker(_answers(wg1=RuntimeError("exec failed")))
    r = _get("/api/wg/alice", fake)
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == WG0
    dt = body["data_tunnel"]
    assert dt["rc"] is None and dt["output"] is None
    assert "exec failed" in dt["error"]
    assert dt["psk_source"] == "rosenpass"
    assert set(dt) == set(body) - _SAMPLE_FIELDS


def test_a_wg1_exec_error_is_bounded():
    """The exception text echoed to the public is cut at ERROR_TEXT_MAX_CHARS."""
    long_text = "x" * (_main.ERROR_TEXT_MAX_CHARS * 3)
    fake = _Docker(_answers(wg1=RuntimeError(long_text)))
    dt = _get("/api/wg/alice", fake).json()["data_tunnel"]
    assert dt["error"] == long_text[:_main.ERROR_TEXT_MAX_CHARS]


def test_the_allow_list_still_applies():
    fake = _Docker(_answers())
    assert _get("/api/wg/alice-ipsec", fake).status_code == 404
    assert fake.seen == []


# ---- the /api/wg/{node} cache -------------------------------------------
def test_a_second_request_inside_the_ttl_costs_no_exec():
    """Two execs per node per WG_SHOW_TTL_S, whatever the request rate."""
    fake = _Docker(_answers())
    first = _get("/api/wg/alice", fake).json()
    second = _get("/api/wg/alice", fake).json()
    assert fake.seen == [_main.WG_SHOW_CMD, _main.WG_DATA_SHOW_CMD], (
        "the second request ran `wg show` again; the route is uncached")
    assert second == first
    # The answer says when it was taken and for how long it is reused.
    assert isinstance(first["observed_at"], float)
    assert first["cache_ttl_s"] == _main.WG_SHOW_TTL_S


def test_the_cache_is_per_node():
    fake = _Docker(_answers())
    assert _get("/api/wg/alice", fake).json()["node"] == "alice"
    assert _get("/api/wg/bob", fake).json()["node"] == "bob"
    assert len(fake.seen) == 4


def test_an_expired_entry_is_sampled_again():
    fake = _Docker(_answers())
    _get("/api/wg/alice", fake)
    # Age the entry past the TTL rather than freezing the clock the test
    # client runs on, as tests/test_docker_routes_are_allow_listed.py does.
    _main._pure_cache["wg:alice"]["at"] -= _main.WG_SHOW_TTL_S + 1
    _get("/api/wg/alice", fake)
    assert len(fake.seen) == 4


def test_a_404_is_cached_too():
    """A node whose exec fails must not cost an exec on every request."""
    fake = _Docker({_main.WG_SHOW_CMD: RuntimeError("container is not running"),
                    _main.WG_DATA_SHOW_CMD: (0, WG1)})
    first = _get("/api/wg/alice", fake)
    second = _get("/api/wg/alice", fake)
    assert (first.status_code, second.status_code) == (404, 404)
    assert "container is not running" in second.json()["detail"]
    assert fake.seen == [_main.WG_SHOW_CMD]


def test_a_404_detail_is_bounded_cached_or_not():
    """ERROR_TEXT_MAX_CHARS applies to the public 404 and to what is cached."""
    long_text = "y" * (_main.ERROR_TEXT_MAX_CHARS * 3)
    fake = _Docker({_main.WG_SHOW_CMD: RuntimeError(long_text),
                    _main.WG_DATA_SHOW_CMD: (0, WG1)})
    first = _get("/api/wg/alice", fake)
    second = _get("/api/wg/alice", fake)
    bounded = long_text[:_main.ERROR_TEXT_MAX_CHARS]
    assert first.json()["detail"] == bounded
    assert second.json()["detail"] == bounded
    assert _main._pure_cache["wg:alice"]["value"] == {"not_found": bounded}


def test_the_ttl_is_a_named_setting():
    """A named, environment-overridable constant, like VPN_SAMPLE_TTL_S."""
    assert _main.WG_SHOW_TTL_S > 0
    src = Path(_main.__file__).read_text(encoding="utf-8")
    assert re.search(r'^WG_SHOW_TTL_S = float\(os\.environ\.get\("WG_SHOW_TTL_S", ', src, re.M)


# ---- 2. /api/vpn/protocols ----------------------------------------------
def _protocols(wg1=(0, WG1)):
    return _get("/api/vpn/protocols", _Docker(_answers(wg1=wg1))).json()


def test_the_data_tunnel_is_in_the_lane_status_with_the_same_key_set():
    wg = _protocols()["wireguard"]
    dt = wg["data_tunnel"]
    assert set(dt) == set(_main._wg_unknown("absent")) | {"interface", "psk_source"}
    assert set(wg) == set(dt) | {"data_tunnel"}
    assert (wg["interface"], dt["interface"]) == ("wg0", "wg1")
    assert wg["psk_source"] == _main.WG_PSK_SOURCE["wg0"]
    assert dt["psk_source"] == _main.WG_PSK_SOURCE["wg1"]


def test_the_flat_fields_stay_wg0_and_the_data_tunnel_is_wg1():
    """The two handshake ages differ, so a swap cannot pass."""
    wg = _protocols()["wireguard"]
    assert wg["last_handshake_s"] == 92            # wg0: 1 minute, 32 seconds
    assert wg["data_tunnel"]["last_handshake_s"] == 12
    assert wg["status"] == "established"
    assert wg["data_tunnel"]["status"] == "established"
    assert wg["data_tunnel"]["peers_with_psk"] == 1


def test_a_peer_with_no_psk_line_is_counted_as_such():
    """The parser counts the `preshared key:` line and nothing else.

    A parser test, not the deployed failure mode: a deployed peer always
    carries at least the entrypoint's placeholder, so this count is never the
    evidence that Rosenpass keyed wg1. The handshake is; see the next test.
    """
    dt = _protocols(wg1=(0, WG1_NO_PSK))["wireguard"]["data_tunnel"]
    assert (dt["peers_with_psk"], dt["peers"]) == (0, 1)


def test_a_full_psk_count_without_a_handshake_is_not_established():
    """The placeholder state: every peer has a PSK, and wg1 is not keyed.

    Before Rosenpass writes the same key on both ends, the two ends hold
    different random placeholders, so no handshake completes. The PSK count is
    full all the same. The lane must read from the handshake: not established,
    no peer handshaked, and no handshake age invented.
    """
    dt = _protocols(wg1=(0, WG1_PLACEHOLDER_ONLY))["wireguard"]["data_tunnel"]
    assert (dt["peers_with_psk"], dt["peers"]) == (1, 1)
    assert dt["status"] == "running"
    assert dt["active_sa"] == 0
    assert dt["last_handshake_s"] is None and dt["last_handshake"] is None


# ---- 3. recency: fresh against ever ------------------------------------
def test_the_freshness_limit_is_wireguards_reject_after_time():
    """A named constant with WireGuard's value, carried in every state.

    messages.h `REJECT_AFTER_TIME = 180`; wireguard-go `RejectAfterTime`. The
    limit is a definition, not a measurement, so the unknown template carries
    it too and a reader can always label the count.
    """
    assert _main.WG_REJECT_AFTER_TIME_S == 180
    src = Path(_main.__file__).read_text(encoding="utf-8")
    assert re.search(r"^WG_REJECT_AFTER_TIME_S = 180$", src, re.M)
    assert "REJECT_AFTER_TIME = 180" in src, "the citation of messages.h is gone"
    for status in ("absent", "error", "running"):
        unknown = _main._wg_unknown(status)
        assert unknown["fresh_within_s"] == _main.WG_REJECT_AFTER_TIME_S
        assert unknown["peers_fresh"] is None


def test_a_recent_handshake_is_fresh_on_both_interfaces():
    wg = _protocols()["wireguard"]
    assert (wg["peers_fresh"], wg["active_sa"], wg["peers"]) == (1, 1, 1)
    dt = wg["data_tunnel"]
    assert (dt["peers_fresh"], dt["active_sa"], dt["peers"]) == (1, 1, 1)
    assert dt["fresh_within_s"] == _main.WG_REJECT_AFTER_TIME_S


def test_a_stale_handshake_is_ever_but_not_fresh():
    """The divergence case the lifetime count could not show.

    `active_sa` keeps its meaning (ever handshaked since the interface came
    up), and so does `status`, which follows it; only `peers_fresh` falls.
    """
    dt = _protocols(wg1=(0, WG1_STALE))["wireguard"]["data_tunnel"]
    assert dt["last_handshake_s"] == _main.WG_REJECT_AFTER_TIME_S
    assert dt["peers_fresh"] == 0
    assert dt["active_sa"] == 1
    assert dt["status"] == "established"


def test_one_second_younger_is_still_fresh():
    """The kernel refuses a key once its age reaches the limit, not before."""
    dt = _protocols(wg1=(0, WG1_LAST_FRESH_SECOND))["wireguard"]["data_tunnel"]
    assert dt["last_handshake_s"] == _main.WG_REJECT_AFTER_TIME_S - 1
    assert dt["peers_fresh"] == 1


def test_an_unreadable_age_is_not_counted_either_way():
    """None, not 0 and not 1: the age is unknown, so is the freshness."""
    dt = _protocols(wg1=(0, WG1_CLOCK_BACKWARD))["wireguard"]["data_tunnel"]
    assert dt["active_sa"] == 1
    assert dt["last_handshake_s"] is None
    assert dt["peers_fresh"] is None


def test_the_placeholder_state_has_no_fresh_handshake():
    dt = _protocols(wg1=(0, WG1_PLACEHOLDER_ONLY))["wireguard"]["data_tunnel"]
    assert dt["peers_fresh"] == 0


def test_the_comments_do_not_say_a_ping_shows_the_latest_key():
    """What a ping, and a fresh handshake, show -- and what they do not.

    A new preshared key takes effect only at the next handshake, and the
    session keypair from the last completed one stays usable until it is
    WG_REJECT_AFTER_TIME_S old. So after the two ends diverge a ping keeps
    answering, just as the fresh count stays full. Neither shows that the
    key written most recently is in use; a handshake completed after that
    write does. main.py said "Proof that the current key carries traffic is a
    ping" until 2026-09-26.
    """
    src = Path(_main.__file__).read_text(encoding="utf-8")
    prose = " ".join(re.sub(r"^\s*#\s?", "", src, flags=re.M).split())
    assert "Proof that the current key carries traffic is a ping" not in prose
    assert "shows only that the current WireGuard session carries traffic" in prose
    assert ("a `last_handshake_s` smaller than the time since arnika's (wg0) "
            "or Rosenpass's (wg1) last write") in prose


def test_a_failed_wg1_is_error_and_leaves_wg0_alone():
    wg = _protocols(wg1=(1, WG1_ABSENT))["wireguard"]
    assert wg["data_tunnel"]["status"] == "error"
    assert wg["data_tunnel"]["peers"] is None
    assert wg["status"] == "established"


def test_an_unreachable_alice_leaves_both_interfaces_absent():
    class _NoAlice:
        class containers:
            @staticmethod
            def get(_name):
                raise LookupError("no such container")

    wg = _get("/api/vpn/protocols", _NoAlice()).json()["wireguard"]
    assert wg["status"] == "absent"
    assert wg["data_tunnel"]["status"] == "absent"


# ---- 4. /api/topology ---------------------------------------------------
def test_the_topology_draws_both_alice_bob_tunnels():
    body = _get("/api/topology", _Docker(_answers())).json()
    ab = [e["label"] for e in body["edges"] if {e["source"], e["target"]} == {"alice", "bob"}]
    assert len(ab) == 2
    assert any(lbl.startswith("wg0") and "PQC-HPKE" in lbl for lbl in ab)
    assert any(lbl.startswith("wg1") and "Rosenpass" in lbl for lbl in ab)
    # "RP" was never expanded anywhere on the page.
    assert not any(re.search(r"\bRP\b", n["label"]) for n in body["nodes"])
    assert any("Rosenpass" in n["label"] for n in body["nodes"] if n["id"] == "alice")


# ---- 5. the rotation counter after the move to slog --------------------
# At the old pin the adapter's log.Printf line was the whole line. At f4cf9ba
# arnika installs an slog TextHandler as the default logger, which carries the
# standard `log` package's output as the quoted msg of a key=value record.
_OLD_FORM = ("2026/09/25 06:48:38 [INFO] [VICI] PPK rotated "
             "(id=qkd-alice-7 ppk_id=ppk-qkd bytes=32)")
_SLOG_FORM = ('time=2026-09-26T10:00:00.000Z level=INFO msg="[INFO] [VICI] PPK rotated '
              '(id=qkd-alice-8 ppk_id=ppk-qkd bytes=32)" arnika_id=11')
# A new-format arnika line that is NOT a rotation, to show the pattern is not
# merely matching any slog record.
_SLOG_OTHER = ('time=2026-09-26T10:00:00.000Z level=INFO msg="round agreed a fresh '
               'PQC key" arnika_id=11 component=pqc-hpke round=42 as=initiator')


@pytest.mark.parametrize("line,expected_id", [
    (_OLD_FORM, "qkd-alice-7"),
    (_SLOG_FORM, "qkd-alice-8"),
])
def test_the_rotation_pattern_reads_both_log_formats(line, expected_id):
    assert _main._ROTATION_RE.findall(line) == [expected_id]


def test_the_rotation_pattern_ignores_other_slog_records():
    assert _main._ROTATION_RE.findall(_SLOG_OTHER) == []


def test_the_endpoint_counts_slog_lines():
    log = "\n".join([_OLD_FORM, _SLOG_OTHER, _SLOG_FORM]).encode()

    class _Logs:
        def logs(self, **_):
            return log

    class _D:
        class containers:
            @staticmethod
            def get(_name):
                return _Logs()

    body = _get("/api/vpn/ppk-rotations?window_s=600", _D()).json()
    for node in ("alice-ipsec", "bob-ipsec"):
        assert body["nodes"][node]["count"] == 2
        assert body["nodes"][node]["distinct_ids"] == 2
