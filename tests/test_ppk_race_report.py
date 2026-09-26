"""scripts/ppk_race_report.py applies its counting rules to both arnika formats.

The report exists for one comparison: the intermittent PPK mismatch on the
IPsec lane before and after the pin moved from arnika 3a8cc13 to upstream PR
#51's head (f4cf9ba). The two arms log in different formats -- bracketed Go
`log` tags before, log/slog key=value records after -- so the same rule has to
be exercised against both, or the comparison measures the parser.

The fixtures below are synthetic, built from the message strings of the two
arnika trees and of charon, and each scenario isolates one class:

  C1  an invalidation wrote a random PPK (on alice, and separately on bob),
      including f4cf9ba's two fail-closed paths that the report names: a
      BACKUP interval that ended with `no key_id from the peer`, and a PRIMARY
      whose key_id was never acknowledged (`the peer did not confirm the
      key_id`). Neither random write may be counted as a rotation.
  C2  the failure precedes the first key-driven rotation after a start
  C3  bob answered before loading the generation carrying alice's key_id
  C4  bob had loaded it and still mismatched, with and without a PQC round
      agreed in between (the read-gap flag)
  C5  bob never loaded a generation carrying alice's key_id
  U   no bob mismatch can be paired with the failure

plus the rule the class depends on most: nodes are matched by key_id, not by
generation number, because the numbers drift apart after a lag; the rule that
decides which write an invalidation made when a key_id arrives while the
random write is in flight; and the rule that credits a named trigger only to
the invalidation it causes.

A further section covers the interval boundaries: the offset between the two
ends' boundaries per wall-clock tick and its trend, interval-number mismatches
(a restart of one node, or starts more than half an interval apart), key_ids
that reach their receiver before the receiver's own boundary, and the JSON
form's per-tick list with d (the BACKUP's boundary minus the PRIMARY's), the
early flag and how each BACKUP interval ended, counted per segment.

The last section checks that the strings the parser keys on are still in the
sources that write them: the VICI adapter here, and -- where the submodules are
checked out -- the pinned arnika and strongSwan. It also checks that the lines
of the pinned main.go which the report and the adapter README cite still hold
the code they are cited for.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ppk_race_report.py"
ARNIKA = ROOT / "submodules" / "arnika"
STRONGSWAN = ROOT / "submodules" / "strongswan"


def _load():
    spec = importlib.util.spec_from_file_location("ppk_race_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ppk_race_report"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load()

# ------------------------------------------------------------------ fixtures --

BASE = "2026-09-26T12:00:"      # fixtures start at 12:00:00; t is seconds after it
ALICE_ID, BOB_ID = 11, 12        # the ARNIKA_ID defaults of the IPsec lane
ALICE_PREFIX, BOB_PREFIX = "qkd-bob", "qkd-alice"   # VICI_CREDENTIAL_PREFIX
PPK_ID = "ppk-qkd@pqcqkd.local"
IDENTITIES = ("alice@pqcqkd.local", "bob@pqcqkd.local")
PEER_ADDRESS = "10.30.0.20:41000"


def _key(n: int) -> str:
    """A UUID-shaped key_id, distinct per n, like bb84-kme's uuid4()."""
    return f"{n:08x}-4a1b-4c2d-8e3f-{n:012x}"


def _minute_second(t: float) -> tuple[int, float]:
    return int(t) // 60, t - 60 * (int(t) // 60)


def _docker_stamp(t: float) -> str:
    """`docker logs -t`'s stamp for t seconds after 12:00:00, to the nanosecond."""
    whole, frac = divmod(round(t * 1e9), 10**9)
    return f"2026-09-26T12:{whole // 60:02d}:{whole % 60:02d}.{frac:09d}Z"


def _slog_time(t: float) -> str:
    """slog's own `time=` attribute, to the millisecond."""
    m, sec = _minute_second(t)
    return f"2026-09-26T12:{m:02d}:{sec:06.3f}Z"


def _pin_time(t: float) -> str:
    """The Go `log` package's default prefix, to the second."""
    m, sec = _minute_second(t)
    return f"2026/09/26 12:{m:02d}:{int(sec):02d}"


class Log:
    """One container's `docker logs -t` text, in either arnika format."""

    def __init__(self, fmt: str, arnika_id: int):
        self.fmt, self.id, self.rows = fmt, arnika_id, []

    def _raw(self, t: float, text: str) -> None:
        self.rows.append(f"{_docker_stamp(t)} {text}")

    def _arnika(self, t: float, level: str, role: str | None, slog_msg: str,
                pin_tag: str, pin_text: str, **attrs) -> None:
        if self.fmt == "slog":
            parts = [f"time={_slog_time(t)} level={level} msg=\"{slog_msg}\" arnika_id={self.id}"]
            if role:
                parts.append(f"role={role}")
            parts += [f"{k}={v}" for k, v in attrs.items()]
            self._raw(t, " ".join(parts))
        else:
            colour = "\x1b[36m" if self.id % 2 else "\x1b[35m"
            prefix = f"{colour}{role.upper()}[{self.id}]\x1b[0m " if role else ""
            self._raw(t, f"{_pin_time(t)} [{level}] {prefix}{pin_tag}{pin_text}")

    # -- the VICI adapter: log.Printf, wrapped into msg="..." under slog
    def _adapter(self, t: float, text: str) -> None:
        if self.fmt == "slog":
            quoted = text.replace('"', '\\"')
            self._raw(t, f"time={_slog_time(t)} level=INFO msg=\"[INFO] [VICI] {quoted}\" "
                         f"arnika_id={self.id}")
        else:
            self._raw(t, f"{_pin_time(t)} [INFO] [VICI] {text}")

    def started(self, t):
        self._adapter(t, "connected to charon 6.1.0 on /var/run/charon.vici")

    def rotated(self, t, prefix, n):
        self._raw(t - 0.0004, f"05[CFG] loaded PPK shared key with id '{prefix}-{n}' for: '{PPK_ID}'")
        self._adapter(t, f"PPK rotated (id={prefix}-{n} ppk_id={PPK_ID} bytes=32)")

    def responder_loaded(self, t, prefix, n):
        self._raw(t - 0.0004, f"05[CFG] loaded PPK shared key with id '{prefix}-{n}' for: '{PPK_ID}'")
        self._adapter(t, f"PPK {prefix}-{n} loaded; not reauthenticating (the peer drives the SA "
                         f"for \"pqcqkd-vpn\")")
        self._adapter(t + 0.0002, f"PPK rotated (id={prefix}-{n} ppk_id={PPK_ID} bytes=32)")

    # -- arnika
    def primary_sends(self, t, key):
        self._arnika(t - 0.001, "INFO", "primary", "requesting a new QKD key",
                     "[REQ] ", "request QKD key from http://bb84-kme-a:8080/api/v1/keys/BOB",
                     kms="http://bb84-kme-a:8080/api/v1/keys/BOB")
        self._arnika(t, "INFO", "primary", "sending the key_id to the peer",
                     "[SND] ", f"send key_id {key} to bob-ipsec:9998", key_id=key, peer="bob-ipsec:9998")

    def backup_receives(self, t, key):
        self._arnika(t, "INFO", "backup", "received a key_id from the peer",
                     "[RCV] ", f"received key_id {key} from {PEER_ADDRESS}", key_id=key, peer=PEER_ADDRESS)
        self._arnika(t + 0.0002, "INFO", "backup", "requesting the QKD key for the peer's key_id",
                     "[REQ] ", f"request QKD key for key_id {key} from http://bb84-kme-b:8080",
                     key_id=key, kms="http://bb84-kme-b:8080")

    def backup_waits(self, t, interval):
        self._arnika(t, "INFO", "backup", "waiting for a key_id from the peer", "[REQ] ",
                     f"BACKUP for interval {interval}, waiting for key_id from peer", interval=interval)

    def invalidates(self, t, role):
        self._arnika(t, "ERROR", role, "configuring a random PSK to invalidate the WireGuard session",
                     "[STOP] ", "configure random PSK to invalidate WireGuard session")

    def random_write_failed(self, t, role):
        self._arnika(t, "ERROR", role, "failed to configure the random PSK", "",
                     "failed to configure random PSK: vici: cannot connect to /var/run/charon.vici",
                     err='"vici: cannot connect to /var/run/charon.vici"')

    # -- f4cf9ba's fail-closed paths (main.go). The previous pin has neither:
    # its BACKUP kept the old key when no key_id came, and its PRIMARY wrote
    # its key whether or not the send succeeded.
    def no_key_id(self, t, interval):
        """A BACKUP interval ended without a key_id: the trigger, buildPSK's
        reason, then the invalidation, as main.go logs them."""
        assert self.fmt == "slog"
        self._arnika(t, "ERROR", "backup", "no key_id from the peer", "", "", interval=interval)
        self._arnika(t + 0.00001, "ERROR", "backup", "no QKD key received", "", "",
                     mode="QkdAndPqcRequired")
        self.invalidates(t + 0.00002, "backup")

    def not_confirmed(self, t, key):
        """The PRIMARY sent the key_id and no ACK came before the deadline."""
        assert self.fmt == "slog"
        self._arnika(t, "ERROR", "primary", "the peer did not confirm the key_id", "", "",
                     key_id=key, peer="bob-ipsec:9998", err='"no ACK by 12:00:36"')
        self._arnika(t + 0.00001, "ERROR", "primary", "no QKD key received", "", "",
                     mode="QkdAndPqcRequired")
        self.invalidates(t + 0.00002, "primary")

    # -- f4cf9ba's other fail-closed paths, for the trigger bookkeeping
    def build_fails(self, t, role):
        """buildPSK had no PQC key: it logs its reason and invalidates."""
        assert self.fmt == "slog"
        self._arnika(t, "ERROR", role, "failed to retrieve the PQC key", "", "",
                     err='"no PQC key agreed yet"', mode="QkdAndPqcRequired")
        self.invalidates(t + 0.00001, role)

    def not_confirmed_after_failed_build(self, t, key):
        """No ACK, but buildPSK had already failed and invalidated before the
        send: main.go logs the trigger and nothing after it."""
        assert self.fmt == "slog"
        self._arnika(t, "ERROR", "primary", "the peer did not confirm the key_id", "", "",
                     key_id=key, peer="bob-ipsec:9998", err='"no ACK by 12:00:36"')

    def kms_request_fails(self, t):
        """A PRIMARY's KMS request failed: no interval number, and under
        QkdAndPqcRequired a fail-closed write."""
        assert self.fmt == "slog"
        self._arnika(t, "INFO", "primary", "requesting a new QKD key", "", "",
                     kms="http://bb84-kme-b:8080/api/v1/keys/ALICE")
        self._arnika(t + 0.002, "ERROR", "primary", "failed to retrieve a QKD key", "", "",
                     kms="http://bb84-kme-b:8080/api/v1/keys/ALICE", err='"status 503"')
        self._arnika(t + 0.00201, "ERROR", "primary", "no QKD key received", "", "",
                     mode="QkdAndPqcRequired")
        self.invalidates(t + 0.00202, "primary")

    def worker_fetch_fails(self, t, key):
        """The key_id worker could not fetch the peer's key and fails closed."""
        assert self.fmt == "slog"
        self._arnika(t, "INFO", "backup", "received a key_id from the peer", "", "",
                     key_id=key, peer=PEER_ADDRESS)
        self._arnika(t + 0.0002, "INFO", "backup", "requesting the QKD key for the peer's key_id", "", "",
                     key_id=key, kms="http://bb84-kme-b:8080")
        self._arnika(t + 0.002, "ERROR", "backup", "failed to retrieve the QKD key for the peer's key_id",
                     "", "", key_id=key, kms="http://bb84-kme-b:8080", err='"status 404"')
        self._arnika(t + 0.00201, "ERROR", "backup", "no QKD key received", "", "",
                     mode="QkdAndPqcRequired")
        self.invalidates(t + 0.00202, "backup")

    # -- interval boundaries, as the main loop logs them (main.go:331-350 at f4cf9ba)
    def primary_boundary(self, t, interval, fetch):
        """A PRIMARY interval opens with the KMS request; its number follows
        the fetch."""
        self._arnika(t, "INFO", "primary", "requesting a new QKD key",
                     "[REQ] ", "request QKD key from http://bb84-kme-a:8080/api/v1/keys/BOB",
                     kms="http://bb84-kme-a:8080/api/v1/keys/BOB")
        self._arnika(t + fetch, "INFO", "primary", "serving this interval",
                     "[REQ] ", f"PRIMARY for interval {interval}", interval=interval)

    def boundary(self, t, interval, role, fetch=0.0012):
        if role == "primary":
            self.primary_boundary(t, interval, fetch)
        else:
            self.backup_waits(t, interval)

    def sends_key_id(self, t, key):
        """The send alone; the KMS request came at the interval's boundary."""
        self._arnika(t, "INFO", "primary", "sending the key_id to the peer",
                     "[SND] ", f"send key_id {key} to bob-ipsec:9998", key_id=key, peer="bob-ipsec:9998")

    def round_agreed(self, t, rnd, as_):
        if self.fmt == "slog":
            self._raw(t, f"time={_slog_time(t)} level=INFO msg=\"round agreed a fresh PQC key\" "
                         f"arnika_id={self.id} component=pqc-hpke round={rnd} as={as_}")

    # -- charon
    def auth_failed_initiator(self, t):
        self._raw(t, "07[ENC] parsed IKE_AUTH response 2 [ N(AUTH_FAILED) ]")

    def mismatch_responder(self, t):
        self._raw(t, f"09[IKE] tried 1 shared key for '{IDENTITIES[1]}' - '{IDENTITIES[0]}', "
                     "but MAC mismatched")
        self._raw(t + 0.00002, "09[ENC] generating IKE_AUTH response 2 [ N(AUTH_FAILED) ]")

    def ppk_applied(self, t):
        self._raw(t, f"12[CFG] using PPK for PPK_ID '{PPK_ID}'")

    def text(self) -> str:
        return "\n".join(self.rows) + "\n"


def _pair(fmt: str, first_round: bool = True) -> tuple[Log, Log]:
    """Both nodes start together; in the slog format a PQC round is agreed
    before the first rotation, as it must be under QkdAndPqcRequired."""
    alice, bob = Log(fmt, ALICE_ID), Log(fmt, BOB_ID)
    alice.started(0.0)
    bob.started(0.0)
    if first_round:
        alice.round_agreed(0.5, 99, "initiator")
        bob.round_agreed(0.5, 99, "responder")
    return alice, bob


def _healthy(alice: Log, bob: Log, t: float, n: int, alice_primary: bool, key: str) -> None:
    """One clean interval. Timing follows the tree the format belongs to: at the
    pin both ends write as soon as they hold the key; at f4cf9ba the PRIMARY
    writes only after the BACKUP's ACK, so the BACKUP loads first."""
    if alice_primary:
        alice.primary_sends(t, key)
        bob.backup_receives(t + 0.001, key)
        bob.responder_loaded(t + 0.003, BOB_PREFIX, n)
        alice.rotated(t + 0.005, ALICE_PREFIX, n)
    else:
        bob.primary_sends(t, key)
        alice.backup_receives(t + 0.001, key)
        bob.responder_loaded(t + 0.003, BOB_PREFIX, n)
        alice.rotated(t + 0.005, ALICE_PREFIX, n)
    alice.ppk_applied(t + 0.006)


def _report(alice: Log, bob: Log, **kw) -> dict:
    a = R.parse_node("alice", alice.text(), **kw)
    b = R.parse_node("bob", bob.text(), **kw)
    return R.build_report(a, b)


def _classes(report: dict) -> list[tuple[str, str]]:
    return [(f["cell"], f["class"]) for f in report["failures"]]


# ------------------------------------------------------------ classification --

@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_healthy_rotations_are_counted_per_cell_and_nothing_fails(fmt):
    alice, bob = _pair(fmt)
    for n in range(1, 7):
        _healthy(alice, bob, 1.0 + 3 * n, n, alice_primary=n % 2 == 1, key=_key(n))
    rep = _report(alice, bob)
    assert rep["format"] == {"alice": fmt, "bob": fmt}
    assert rep["cells"]["alice PRIMARY"]["R"] == 3
    assert rep["cells"]["alice BACKUP"]["R"] == 3
    assert rep["cells"]["all"]["F"] == 0
    assert rep["corroboration"]["alice_ppk_applied"] == 6
    assert rep["key_id_shapes"] == {"distinct": 6, "uuid": 6, "other": 0}


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_the_race_is_c3_in_the_cell_of_alices_role(fmt):
    """Bob answers the IKE_AUTH, then loads: the signature of the 16 live failures."""
    alice, bob = _pair(fmt)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    # alice PRIMARY: alice loads and reauthenticates at once; bob's MAC check
    # runs 1 ms before bob's own load of the same key.
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    bob.responder_loaded(6.004, BOB_PREFIX, 2)
    # and the same race with alice BACKUP, the side f4cf9ba is expected to expose
    bob.primary_sends(9.0, _key(3))
    alice.backup_receives(9.001, _key(3))
    alice.rotated(9.002, ALICE_PREFIX, 3)
    bob.mismatch_responder(9.003)
    alice.auth_failed_initiator(9.0035)
    bob.responder_loaded(9.004, BOB_PREFIX, 3)

    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "C3"), ("alice BACKUP", "C3")]
    assert rep["cells"]["alice PRIMARY"]["C3"] == 1
    assert rep["cells"]["alice BACKUP"]["C3"] == 1
    assert all(f["matched_by"] == "key_id" for f in rep["failures"])


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_alices_own_invalidation_is_c1_and_not_a_rotation(fmt):
    alice, bob = _pair(fmt)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    # alice BACKUP, no key_id by the end of the interval: fail closed.
    alice.backup_waits(6.0, 2)
    alice.invalidates(9.0, "backup")
    alice.rotated(9.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(9.003)
    alice.auth_failed_initiator(9.0035)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice BACKUP", "C1")]
    assert rep["cells"]["all"]["R"] == 1, "a random PPK was counted as a rotation"
    assert rep["invalidation_writes"]["alice"] == 1


def test_bobs_invalidation_before_the_key_id_is_c1_not_lag():
    """f4cf9ba builds the PRIMARY's PSK before sending; a missing PQC key makes
    bob write a random PPK and then send the key_id anyway, so bob never holds a
    generation carrying it. Without the invalidation window that reads as C5."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, False, _key(1))
    bob.invalidates(6.0, "primary")
    bob.responder_loaded(6.001, BOB_PREFIX, 2)          # the random PPK
    bob.primary_sends(6.002, _key(2))
    alice.backup_receives(6.003, _key(2))
    alice.rotated(6.005, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.006)
    alice.auth_failed_initiator(6.0065)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice BACKUP", "C1")]
    assert rep["invalidation_writes"]["bob"] == 1


NO_TRIGGER = {"no key_id from the peer": 0, "the peer did not confirm the key_id": 0, "other": 0}


def test_a_backup_that_saw_no_key_id_fails_closed_as_c1_not_as_a_rotation():
    """The invalidation shape comes from each of alice's PRIMARY-to-BACKUP
    transitions in a local run on 2026-09-26: bob's BACKUP interval ends with
    no key_id, bob holds a random PPK until its own PRIMARY interval sends the
    next one, and alice, BACKUP now, loads that key and reauthenticates first.
    The authentication failure below is hypothetical: the local run had none
    at those points. It is added to test that such a failure is classified as
    C1."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    bob.no_key_id(6.0, 2)
    bob.responder_loaded(6.001, BOB_PREFIX, 2)          # the random PPK
    bob.primary_sends(6.85, _key(3))
    alice.backup_receives(6.851, _key(3))
    alice.rotated(6.853, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.854)
    alice.auth_failed_initiator(6.8545)
    bob.responder_loaded(6.856, BOB_PREFIX, 3)          # after the ACK
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice BACKUP", "C1")]
    assert rep["cells"]["all"]["R"] == 2
    assert rep["invalidation_writes"] == {"alice": 0, "bob": 1}
    assert rep["invalidation_triggers"] == {
        "alice": NO_TRIGGER, "bob": {**NO_TRIGGER, "no key_id from the peer": 1}}
    assert rep["corroboration"]["bob_rotations"] == 2, "bob's random PPK was counted as a rotation"


def test_an_unacknowledged_key_id_fails_closed_as_c1_and_is_not_carried_forward():
    """alice is PRIMARY, bob loaded the key but its ACK was lost: alice writes
    a random PPK instead. The key_id alice sent is never written on alice, so
    it must not reach alice's next generation either."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, False, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    bob.responder_loaded(6.003, BOB_PREFIX, 2)
    alice.not_confirmed(6.5, _key(2))
    alice.rotated(6.502, ALICE_PREFIX, 2)               # the random PPK
    bob.mismatch_responder(6.503)
    alice.auth_failed_initiator(6.5035)
    # the next interval, alice BACKUP: the race, which must still be found
    bob.primary_sends(9.0, _key(3))
    alice.backup_receives(9.001, _key(3))
    alice.rotated(9.002, ALICE_PREFIX, 3)
    bob.mismatch_responder(9.003)
    alice.auth_failed_initiator(9.0035)
    bob.responder_loaded(9.004, BOB_PREFIX, 3)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "C1"), ("alice BACKUP", "C3")]
    assert rep["cells"]["all"]["R"] == 2, "alice's random PPK was counted as a rotation"
    assert rep["invalidation_triggers"]["alice"] == {
        **NO_TRIGGER, "the peer did not confirm the key_id": 1}
    gens = {g.number: g for g in R.parse_node("alice", alice.text()).generations}
    assert (gens[2].invalidation, gens[2].key_id, gens[2].role) == (True, None, "primary")
    assert (gens[3].invalidation, gens[3].key_id, gens[3].role) == (False, _key(3), "backup")


def test_a_key_id_that_arrives_during_the_random_write_belongs_to_the_next_write():
    """KeyWriterService serialises writes, and a received key_id's own write
    waits for a KMS request first, so a key_id logged between the invalidation
    line and the random load is written after the random PPK. The random write
    stays an invalidation, and the key_id reaches the write that carries it."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    bob.no_key_id(6.0, 2)
    alice.primary_sends(6.0001, _key(2))
    bob.backup_receives(6.0002, _key(2))
    bob.responder_loaded(6.0010, BOB_PREFIX, 2)         # the random PPK
    bob.responder_loaded(6.0030, BOB_PREFIX, 3)         # the key_id's write
    alice.rotated(6.0050, ALICE_PREFIX, 2)
    gens = {g.number: g for g in R.parse_node("bob", bob.text()).generations}
    assert (gens[2].invalidation, gens[2].key_id) == (True, None)
    assert (gens[3].invalidation, gens[3].key_id, gens[3].role) == (False, _key(2), "backup")
    rep = _report(alice, bob)
    assert rep["invalidation_writes"]["bob"] == 1
    assert rep["corroboration"]["bob_rotations"] == 2


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_an_invalidation_whose_own_write_failed_marks_no_later_write(fmt):
    alice, bob = _pair(fmt)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    bob.invalidates(6.0, "backup")
    bob.random_write_failed(6.0001, "backup")
    _healthy(alice, bob, 9.0, 2, True, _key(2))
    rep = _report(alice, bob)
    assert rep["invalidation_writes"]["bob"] == 0
    assert rep["corroboration"]["bob_rotations"] == 2


def test_a_trigger_is_credited_only_to_the_invalidation_it_causes():
    """`the peer did not confirm the key_id` is also logged when buildPSK had
    already failed and invalidated before the send, and then nothing follows
    it. A later invalidation with another cause must not inherit it, whether
    the next KMS request fails or the key_id worker's fetch does. Lines that
    are not arnika's (charon's) may come between a trigger and its own
    invalidation without breaking the link."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, False, _key(1))
    # bob PRIMARY: no PQC key, so buildPSK invalidates before the send; the
    # send goes out anyway and is never acknowledged.
    bob.build_fails(6.0, "primary")
    bob.responder_loaded(6.001, BOB_PREFIX, 2)          # the random PPK
    bob.sends_key_id(6.1, _key(2))
    bob.not_confirmed_after_failed_build(6.5, _key(2))
    # the next interval: bob's KMS request fails and it fails closed
    bob.kms_request_fails(9.0)
    bob.responder_loaded(9.004, BOB_PREFIX, 3)
    # the same unconfirmed send again, then the worker's fetch fails
    bob.sends_key_id(12.0, _key(3))
    bob.not_confirmed_after_failed_build(12.5, _key(3))
    bob.worker_fetch_fails(12.6, _key(4))
    bob.responder_loaded(12.604, BOB_PREFIX, 4)
    # a trigger whose own invalidation comes after a line of charon's
    bob._arnika(15.0, "ERROR", "backup", "no key_id from the peer", "", "", interval=5)
    bob._raw(15.000005, "13[IKE] reauthenticating IKE_SA pqcqkd-vpn[4]")
    bob._arnika(15.00001, "ERROR", "backup", "no QKD key received", "", "", mode="QkdAndPqcRequired")
    bob.invalidates(15.00002, "backup")
    bob.responder_loaded(15.001, BOB_PREFIX, 5)
    rep = _report(alice, bob)
    assert rep["invalidation_writes"]["bob"] == 4
    assert rep["invalidation_triggers"]["bob"] == {
        "no key_id from the peer": 1, "the peer did not confirm the key_id": 0, "other": 3}


def test_the_report_names_the_classes_in_the_order_it_tries_them():
    """The order is stated in the output, and it is the order classify()
    actually assigns them in, with U the default when nothing matches."""
    order = ["C1", "C2", "C5", "C3", "C4", "U"]
    assert list(R.CLASS_ORDER) == order
    assigned = re.findall(r'fail\.klass = "(C\d)"', inspect.getsource(R.classify))
    assert assigned + ["U"] == order
    assert 'Failure(f, g, _cell(g), "U")' in inspect.getsource(R.classify)
    assert set(R.CLASSES) == set(order)

    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    rep = _report(alice, bob)
    assert rep["class_order"] == order
    assert rep["class_names"] == {"C1": "invalidation", "C2": "startup", "C3": "race",
                                  "C4": "divergence", "C5": "lag", "U": "unclassified"}
    assert ("first match wins: C1 invalidation, C2 startup, C5 lag, C3 race, "
            "C4 divergence, U unclassified") in R.render(rep)


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_failures_before_the_first_rotation_after_a_start_are_c2(fmt):
    alice, bob = _pair(fmt)
    # the bootstrap PPK is refused before either node rotated
    alice.auth_failed_initiator(1.0)
    bob.mismatch_responder(0.9995)
    # alice has rotated, bob has not yet
    alice.primary_sends(3.0, _key(1))
    alice.rotated(3.002, ALICE_PREFIX, 1)
    bob.mismatch_responder(3.003)
    alice.auth_failed_initiator(3.0035)
    bob.backup_receives(6.0, _key(1))
    bob.responder_loaded(6.002, BOB_PREFIX, 1)
    rep = _report(alice, bob)
    assert [c for _, c in _classes(rep)] == ["C2", "C2"]


def test_startup_lasts_until_the_first_pqc_round_in_the_slog_format():
    """At f4cf9ba MODE=QkdAndPqcRequired cannot build a PSK before a PQC round
    is agreed, so a failure after the first rotation but before the first
    round on that node is still startup."""
    alice, bob = _pair("slog", first_round=False)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    bob.responder_loaded(6.002, BOB_PREFIX, 2)
    alice.rotated(6.003, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.004)
    alice.auth_failed_initiator(6.0045)
    bob.round_agreed(8.0, 100, "responder")
    alice.round_agreed(8.0, 100, "initiator")
    rep = _report(alice, bob)
    assert [c for _, c in _classes(rep)] == ["C2"]


def test_a_slog_node_without_any_round_is_warned_about_not_held_in_startup():
    """No `round agreed` line at all means the PQC half is off or filtered out
    (LOG_LEVEL above info); waiting for a round that never comes would call
    every failure a startup failure."""
    alice, bob = _pair("slog", first_round=False)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    bob.responder_loaded(6.004, BOB_PREFIX, 2)
    rep = _report(alice, bob)
    assert [c for _, c in _classes(rep)] == ["C3"]
    assert sum("round agreed a fresh PQC key" in w for w in rep["warnings"]) == 2


def _divergence(round_between: bool) -> dict:
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    if round_between:
        bob.round_agreed(6.001, 101, "responder")
        alice.round_agreed(6.001, 101, "initiator")
    bob.backup_receives(6.0015, _key(2))
    bob.responder_loaded(6.003, BOB_PREFIX, 2)
    alice.rotated(6.005, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.006)
    alice.auth_failed_initiator(6.0065)
    return _report(alice, bob)


def test_a_mismatch_after_bob_loaded_the_same_key_id_is_c4():
    rep = _divergence(round_between=False)
    assert _classes(rep) == [("alice PRIMARY", "C4")]
    assert rep["failures"][0]["read_gap_candidate"] is False


def test_c4_is_flagged_when_a_pqc_round_lands_between_send_and_load():
    rep = _divergence(round_between=True)
    assert _classes(rep) == [("alice PRIMARY", "C4")]
    assert rep["failures"][0]["read_gap_candidate"] is True
    assert rep["cells"]["all"]["read_gap_candidates"] == 1


def test_the_read_gap_flag_does_not_apply_to_the_pin_era_format():
    """The PQC half came from a Rosenpass file then; there were no rounds."""
    alice, bob = _pair("pin-era")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    bob.responder_loaded(6.003, BOB_PREFIX, 2)
    alice.rotated(6.005, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.006)
    alice.auth_failed_initiator(6.0065)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "C4")]
    assert rep["failures"][0]["read_gap_candidate"] is None


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_bob_never_loading_alices_key_is_c5(fmt):
    """The CI shape of 2026-08-27: alice rotates, bob logs nothing for the interval."""
    alice, bob = _pair(fmt)
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "C5")]


def test_a_failure_with_no_bob_mismatch_is_unclassified_and_said_so():
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    bob.responder_loaded(6.002, BOB_PREFIX, 2)
    alice.rotated(6.003, ALICE_PREFIX, 2)
    alice.auth_failed_initiator(6.004)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "U")]
    assert any("unclassified" in w for w in rep["warnings"])


def test_a_generation_without_its_rotated_line_keeps_its_role_and_key_id():
    """The adapter logs `PPK rotated` after the reauthentication is queued; a
    write that fails before that line still loaded the PPK, and a failure
    against it belongs to that interval's cell. It is not a rotation, so R
    does not count it."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    alice._raw(6.002, f"05[CFG] loaded PPK shared key with id '{ALICE_PREFIX}-2' for: '{PPK_ID}'")
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    bob.responder_loaded(6.004, BOB_PREFIX, 2)
    rep = _report(alice, bob)
    assert _classes(rep) == [("alice PRIMARY", "C3")]
    assert rep["failures"][0]["matched_by"] == "key_id"
    assert rep["cells"]["alice PRIMARY"]["R"] == 1


def test_nodes_are_matched_by_key_id_not_by_generation_number():
    """After a lag bob's numbers trail alice's. Matched by number, the failure
    below would be read against bob's generation 4, which bob loads only
    afterwards, and come out as the race; matched by key_id it is bob's
    generation 2, loaded before the mismatch, so it is a divergence."""
    alice, bob = _pair("pin-era")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    # two intervals bob never sees
    alice.primary_sends(6.0, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    alice.primary_sends(9.0, _key(3))
    alice.rotated(9.002, ALICE_PREFIX, 3)
    # bob catches up: its generation 2 carries alice's generation 4 key
    alice.primary_sends(12.0, _key(4))
    bob.backup_receives(12.001, _key(4))
    bob.responder_loaded(12.002, BOB_PREFIX, 2)
    alice.rotated(12.004, ALICE_PREFIX, 4)
    bob.mismatch_responder(12.005)
    alice.auth_failed_initiator(12.0055)
    # bob's generation 4, later, carries a different key
    alice.primary_sends(15.0, _key(5))
    bob.backup_receives(15.001, _key(5))
    bob.responder_loaded(15.002, BOB_PREFIX, 3)
    alice.rotated(15.004, ALICE_PREFIX, 5)
    alice.primary_sends(18.0, _key(6))
    bob.backup_receives(18.001, _key(6))
    bob.responder_loaded(18.002, BOB_PREFIX, 4)
    alice.rotated(18.004, ALICE_PREFIX, 6)
    rep = _report(alice, bob)
    assert rep["failures"] == [{
        "time": rep["failures"][0]["time"], "generation": 4, "cell": "alice PRIMARY",
        "class": "C4", "matched_by": "key_id", "read_gap_candidate": None,
    }]


# ------------------------------------------------------- interval boundaries --

INTERVAL_S = 30.0          # the IPsec lane's ARNIKA_INTERVAL default
KMS_FETCH_S = 0.0012       # a local bb84-kme fetch, as the local run logged it


def _boundaries(alice: Log, bob: Log, offsets: list[float], numbers=None, roles=None,
                start: float = 1.0) -> list[float]:
    """One boundary per node per tick, bob `offsets[i]` seconds after alice.

    `numbers` gives each tick's (alice, bob) interval numbers, equal by default;
    `roles` each tick's (alice, bob) roles, complementary by default. Returns
    alice's boundary times.
    """
    times = []
    for i, off in enumerate(offsets):
        t = start + INTERVAL_S * i
        n_a, n_b = numbers[i] if numbers else (i, i)
        r_a, r_b = roles[i] if roles else (("primary", "backup") if i % 2 == 0 else ("backup", "primary"))
        alice.boundary(t, n_a, r_a, KMS_FETCH_S)
        bob.boundary(t + off, n_b, r_b, KMS_FETCH_S)
        times.append(t)
    return times


# Shaped like the local run of 2026-09-26 (bob about 0.25 s behind alice,
# closing); the 5 ms step is chosen for round expected values, the run closed
# by about 3 ms per interval.
DRIFT_START_S, DRIFT_STEP_S, DRIFT_TICKS = 0.256, 0.005, 8
DRIFT_OFFSETS = [DRIFT_START_S - DRIFT_STEP_S * i for i in range(DRIFT_TICKS)]


@pytest.mark.parametrize("fmt", ["pin-era", "slog"])
def test_the_boundary_offset_is_measured_per_wall_clock_tick(fmt):
    """bob's boundary minus alice's, paired per tick: the size's median, 95th
    percentile and maximum, and its trend over the window. A PRIMARY's boundary
    is its KMS request, so the fetch time is not part of the offset; it is
    reported on its own."""
    alice, bob = _pair(fmt)
    _boundaries(alice, bob, DRIFT_OFFSETS)
    b = _report(alice, bob)["boundaries"]
    assert b["ticks"] == 8 and b["unpaired"] == {"alice": 0, "bob": 0}
    # bob's gaps are 5 ms short, so the pooled median sits 2.5 ms below 30 s
    assert b["spacing_s"] == pytest.approx(INTERVAL_S, abs=0.01)
    o = b["offset_ms"]
    assert o["abs_median_ms"] == pytest.approx(238.5, abs=0.01)     # (241 + 236) / 2
    assert o[f"abs_p{R.OFFSET_PERCENTILE}_ms"] == pytest.approx(256.0, abs=0.01)
    assert o["abs_max_ms"] == pytest.approx(256.0, abs=0.01)
    assert (o["first_ms"], o["last_ms"]) == (pytest.approx(256.0, abs=0.01), pytest.approx(221.0, abs=0.01))
    # 5 ms less every 30 s is 600 ms less per hour
    assert o["slope_ms_per_hour"] == pytest.approx(-600.0, abs=0.1)
    assert o["step_abs_median_ms"] == pytest.approx(5.0, abs=0.01)
    assert o["step_abs_max_ms"] == pytest.approx(5.0, abs=0.01)
    assert o["bob_later"] == 8
    for name in ("alice", "bob"):
        assert b["nodes"][name]["kms_fetch_ms"] == {"median": pytest.approx(1.2, abs=0.01),
                                                    "max": pytest.approx(1.2, abs=0.01)}
    assert b["interval_mismatch"] == {"ticks": 0, "first": None, "last": None, "bob_minus_alice": {}}
    assert b["same_role"] == {"both_primary": 0, "both_backup": 0}
    # d is the BACKUP's boundary minus the PRIMARY's: +offset while alice is
    # PRIMARY (even ticks here), -offset while bob is
    per_tick = b["per_tick"]
    assert [r["offset_ms"] for r in per_tick] == [pytest.approx(o * 1000, abs=0.01) for o in DRIFT_OFFSETS]
    assert [r["d_ms"] for r in per_tick] == [pytest.approx((1 if i % 2 == 0 else -1) * o * 1000, abs=0.01)
                                             for i, o in enumerate(DRIFT_OFFSETS)]
    assert all(r["primary_fetch_ms"] == pytest.approx(KMS_FETCH_S * 1000, abs=0.01) for r in per_tick)


def test_the_offset_over_the_window_is_printed_in_equal_segments():
    alice, bob = _pair("slog")
    _boundaries(alice, bob, DRIFT_OFFSETS)
    rep = _report(alice, bob)
    segments = rep["boundaries"]["segments"]
    assert len(segments) == R.OFFSET_TREND_SEGMENTS
    assert sum(s["ticks"] for s in segments) == 8
    medians = [s["median_ms"] for s in segments if s["ticks"]]
    assert medians == sorted(medians, reverse=True), "the drift should read as a falling offset"
    assert segments[0]["from"] == R.format_time(R.parse_time(_docker_stamp(1.0)))
    text = R.render(rep)
    assert "offset bob - alice: size median 238.5 ms, p95 256.0 ms, max 256.0 ms" in text
    assert "first +256.0 ms, last +221.0 ms, slope -600.0 ms/h" in text
    assert f"offset over the window, {R.OFFSET_TREND_SEGMENTS} equal segment(s); 'early' counts" in text
    assert "interval-number mismatch: none in 8 paired tick(s)" in text


@pytest.mark.parametrize("shift", [1, -4])
def test_an_interval_number_mismatch_is_counted_with_its_first_and_last_tick(shift):
    """+1: two starts on either side of a boundary, one tick apart in their
    counters. -4: bob restarted, so its counter began again from zero. Either
    way the roles are no longer complementary in some ticks."""
    alice, bob = _pair("slog")
    numbers = [(i, i) if i < 4 else (i, i + shift) for i in range(8)]
    roles = [("primary", "backup"), ("backup", "primary")] * 2 + [
        ("primary", "backup"), ("backup", "backup"), ("primary", "primary"), ("backup", "primary")]
    times = _boundaries(alice, bob, [0.03] * 8, numbers=numbers, roles=roles)
    rep = _report(alice, bob)
    m = rep["boundaries"]["interval_mismatch"]
    assert m == {"ticks": 4, "first": R.format_time(R.parse_time(_docker_stamp(times[4]))),
                 "last": R.format_time(R.parse_time(_docker_stamp(times[7]))),
                 "bob_minus_alice": {f"{shift:+d}": 4}}
    assert rep["boundaries"]["same_role"] == {"both_primary": 1, "both_backup": 1}
    assert any("interval numbers differ between the ends in 4 paired tick(s)" in w for w in rep["warnings"])
    assert f"bob - alice {shift:+d} in 4" in R.render(rep)
    # With one role on both ends there is no PRIMARY-to-BACKUP pair, so d,
    # the PRIMARY's fetch and the early flag are not defined for that tick.
    per_tick = rep["boundaries"]["per_tick"]
    for k in (5, 6):
        assert (per_tick[k]["d_ms"], per_tick[k]["primary_fetch_ms"], per_tick[k]["key_id_early"]) == (
            None, None, None)
    assert [per_tick[k]["alice"]["interval"] - per_tick[k]["bob"]["interval"] for k in range(8)] == (
        [0] * 4 + [-shift] * 4)


def test_a_start_gap_over_half_an_interval_is_a_mismatch_not_a_large_offset():
    """Unaligned starts 20 s apart: each counter starts at zero, so at any one
    wall-clock tick bob's counter is one behind alice's, and the offset is the
    rest of the gap, -10 s."""
    alice, bob = _pair("slog")
    gap, ticks = 20.0, 6
    for i in range(ticks):
        alice.boundary(1.0 + INTERVAL_S * (i + 1), i + 1, "primary" if i % 2 else "backup")
        bob.boundary(1.0 + gap + INTERVAL_S * i, i, "backup" if i % 2 else "primary")
    b = _report(alice, bob)["boundaries"]
    assert b["ticks"] == ticks
    assert b["offset_ms"]["first_ms"] == pytest.approx((gap - INTERVAL_S) * 1000, abs=0.01)
    assert b["offset_ms"]["abs_max_ms"] < INTERVAL_S * 1000 / 2
    assert b["interval_mismatch"]["ticks"] == ticks
    assert b["interval_mismatch"]["bob_minus_alice"] == {"-1": ticks}


def test_a_key_id_that_reaches_the_backup_before_its_own_boundary_is_counted_early():
    """alice PRIMARY sends at the next whole second after her fetch. bob, 0.256 s
    behind, receives it 0.13 s before his own boundary of that tick in the
    first interval; in the second he is only 0.05 s behind and receives it
    after his boundary. Order is taken in bob's own log."""
    alice, bob = _pair("slog")
    for i, off in enumerate((0.256, 0.05)):
        t = 1.874 + 2 * INTERVAL_S * i
        alice.boundary(t, 2 * i, "primary")
        bob.boundary(t + off, 2 * i, "backup")
        send = float(int(t + KMS_FETCH_S) + 1)
        alice.sends_key_id(send, _key(10 + i))
        bob.backup_receives(send + 0.001, _key(10 + i))
        # the next tick, roles swapped, with no key_id at all
        alice.boundary(t + INTERVAL_S, 2 * i + 1, "backup")
        bob.boundary(t + INTERVAL_S + off, 2 * i + 1, "primary")
    b = _report(alice, bob)["boundaries"]
    assert b["early_key_ids"] == {"alice": {"early": 0, "matched": 0}, "bob": {"early": 1, "matched": 2}}


# alice's role per tick in _role_change_run; bob holds the other one.
ROLE_CHANGE_ALICE_PRIMARY = (True, True, False, True, False, True, True)
BOB_LAG_S = 0.25            # bob's boundary after alice's, as in the local run
FIRST_BOUNDARY_S = 1.874    # alice's first boundary, a fraction of a second before a whole one
TRIGGER_LEAD_S = 0.004      # a `no key_id` line comes just before the node's next boundary
STRAY_AFTER_BOUNDARY_S = 0.5  # a stray trigger, well inside the interval it does not fit


def _role_change_run(stray_trigger: bool = False) -> tuple[Log, Log, list[float]]:
    """The shape of the local run of 2026-09-26, in f4cf9ba's slog format.

    bob's boundary lags alice's by BOB_LAG_S, so every key_id alice sends as
    PRIMARY, at the next whole second after her fetch, reaches bob before
    bob's own boundary of that tick: it is early and counts in bob's previous
    interval. bob's BACKUP interval before each change to bob-PRIMARY (ticks
    1 and 3) therefore ends with no key_id and fails closed; the others take
    the next tick's early key_id. Every key_id bob sends reaches alice after
    alice's boundary. With `stray_trigger`, bob also logs three `no key_id
    from the peer` invalidations that fit none of its boundaries: one before
    the window's first boundary, as one whose interval started before the
    window would; one after bob's PRIMARY boundary of tick 2 (wrong role);
    and one after bob's BACKUP boundary of tick 5 that names interval 4
    (wrong number). Returns alice's boundary times.
    """
    alice, bob = _pair("slog")
    if stray_trigger:
        bob.no_key_id(0.8, 41)
        bob.no_key_id(FIRST_BOUNDARY_S + INTERVAL_S * 2 + BOB_LAG_S + STRAY_AFTER_BOUNDARY_S, 2)
        bob.no_key_id(FIRST_BOUNDARY_S + INTERVAL_S * 5 + BOB_LAG_S + STRAY_AFTER_BOUNDARY_S, 4)
    times = []
    for i, alice_primary in enumerate(ROLE_CHANGE_ALICE_PRIMARY):
        t = FIRST_BOUNDARY_S + INTERVAL_S * i
        primary, backup = (alice, bob) if alice_primary else (bob, alice)
        p_t, b_t = (t, t + BOB_LAG_S) if alice_primary else (t + BOB_LAG_S, t)
        primary.boundary(p_t, i, "primary", KMS_FETCH_S)
        backup.boundary(b_t, i, "backup")
        send = float(int(p_t + KMS_FETCH_S) + 1)
        primary.sends_key_id(send, _key(20 + i))
        backup.backup_receives(send + 0.001, _key(20 + i))
        times.append(t)
    for i in (1, 3):
        bob.no_key_id(FIRST_BOUNDARY_S + INTERVAL_S * (i + 1) + BOB_LAG_S - TRIGGER_LEAD_S, i)
    return alice, bob, times


def test_each_paired_tick_is_listed_in_the_json_only():
    """One record per paired tick: the signed offset, d (the BACKUP's boundary
    minus the PRIMARY's), both ends' interval numbers and roles, the
    PRIMARY's fetch, whether its key_id was early, and how each BACKUP
    interval ended. The records carry no key_id and no address, and the text
    form does not list them."""
    alice, bob, times = _role_change_run()
    rep = _report(alice, bob)
    per_tick = rep["boundaries"]["per_tick"]
    lag_ms = BOB_LAG_S * 1000
    assert [r["time"] for r in per_tick] == [R.format_time(R.parse_time(_docker_stamp(t))) for t in times]
    assert all(r["offset_ms"] == pytest.approx(lag_ms, abs=0.01) for r in per_tick)
    assert [r["d_ms"] for r in per_tick] == [pytest.approx(lag_ms if p else -lag_ms, abs=0.01)
                                             for p in ROLE_CHANGE_ALICE_PRIMARY]
    assert all(r["primary_fetch_ms"] == pytest.approx(KMS_FETCH_S * 1000, abs=0.01) for r in per_tick)
    assert [r["key_id_early"] for r in per_tick] == list(ROLE_CHANGE_ALICE_PRIMARY)
    for i, (r, p) in enumerate(zip(per_tick, ROLE_CHANGE_ALICE_PRIMARY)):
        assert r["alice"]["interval"] == r["bob"]["interval"] == i
        assert (r["alice"]["role"], r["bob"]["role"]) == (("primary", "backup") if p else ("backup", "primary"))
    # bob as BACKUP: tick 0 is followed by the failing interval 1; ticks 1
    # and 3 end in the invalidation themselves; tick 5 took tick 6's early
    # key_id, but whether tick 6 ended cleanly lies past the window, and so
    # does the end of tick 6 itself. PRIMARY ticks are not applicable.
    assert [r["bob"]["no_key_id_invalidation"] for r in per_tick] == [
        R.NO_KEY_ID_NEXT, R.NO_KEY_ID_THIS, None, R.NO_KEY_ID_THIS, None, None, None]
    # alice as BACKUP took each key_id late, in its own interval
    assert [r["alice"]["no_key_id_invalidation"] for r in per_tick] == [
        None, None, R.NO_KEY_ID_NONE, None, R.NO_KEY_ID_NONE, None, None]
    text = R.render(rep)
    assert "per_tick" not in text and per_tick[3]["time"] not in text
    assert set(per_tick[0]) == {"time", "offset_ms", "d_ms", "primary_fetch_ms", "key_id_early", "alice", "bob"}


def test_segments_count_early_key_ids_and_no_key_id_invalidations():
    """Each segment counts its early key_ids, of the ticks where that could be
    told, and its BACKUP intervals that ended in a `no key_id from the peer`
    invalidation; the text prints both beside the segment's median offset.
    An invalidation that fits none of the node's boundaries is still in the
    node's total, and the text says how many of the total the ticks hold."""
    alice, bob, _ = _role_change_run(stray_trigger=True)
    rep = _report(alice, bob)
    b = rep["boundaries"]
    segments = b["segments"]
    # seven ticks spread over seven equal segments: one tick in each
    assert [s["ticks"] for s in segments] == [1] * R.OFFSET_TREND_SEGMENTS
    assert [s["early_key_ids"] for s in segments] == [int(p) for p in ROLE_CHANGE_ALICE_PRIMARY]
    assert [s["key_ids_told"] for s in segments] == [1] * R.OFFSET_TREND_SEGMENTS
    assert [s["no_key_id_invalidations"] for s in segments] == [0, 1, 0, 1, 0, 0, 0]
    # the three strays are in bob's total but in no tick
    assert b["nodes"]["bob"]["no_key_id_invalidations"] == 5
    assert b["no_key_id_invalidations_in_ticks"] == 2
    assert b["nodes"]["alice"]["no_key_id_invalidations"] == 0
    assert rep["invalidation_triggers"]["bob"]["no key_id from the peer"] == 0, (
        "no PPK was loaded after these invalidations, so no write carries them")
    text = R.render(rep)
    assert "median    +250.0 ms  max size 250.0 ms  early 1 of 1  no-key_id invalidations 1" in text
    assert "median    -250.0 ms" not in text
    assert "'no key_id from the peer' invalidations: alice 0, bob 5; 2 of them in the paired ticks above" in text


def test_early_key_ids_are_not_counted_for_a_pin_era_receiver():
    """At the previous pin a BACKUP logs no boundary once a key_id has reached
    it, so an early key_id leaves no boundary to compare with; the report says
    n/a rather than 0, and warns that the pin-era offsets are a biased sample."""
    alice, bob = _pair("pin-era")
    _boundaries(alice, bob, DRIFT_OFFSETS)
    rep = _report(alice, bob)
    assert rep["boundaries"]["early_key_ids"] == {"alice": None, "bob": None}
    assert "alice n/a (not slog), bob n/a (not slog)" in R.render(rep)
    assert sum("biased sample of the offset" in w for w in rep["warnings"]) == 2
    # Per tick the same holds, and the previous pin has no `no key_id from
    # the peer` path at all, so how a BACKUP interval ended is not told either.
    per_tick = rep["boundaries"]["per_tick"]
    assert len(per_tick) == DRIFT_TICKS
    assert all(r["key_id_early"] is None for r in per_tick)
    assert all(r[name]["no_key_id_invalidation"] is None for r in per_tick for name in ("alice", "bob"))
    assert all((s["early_key_ids"], s["key_ids_told"], s["no_key_id_invalidations"]) == (0, 0, 0)
               for s in rep["boundaries"]["segments"])


def test_sparse_boundary_lines_do_not_pair_across_ticks():
    """In the pin-era format a BACKUP that already holds the key_id logs no
    boundary. With roles alternating every tick, each node then logs only
    every other tick, so the gaps between its boundary lines are two intervals
    long. The interval is read per interval number, not from the raw gaps, so
    alice's tick N does not pair with bob's tick N+1 just under an interval
    away."""
    alice, bob = _pair("pin-era")
    for i in range(8):
        t = 1.0 + INTERVAL_S * i
        if i % 2 == 0:
            alice.boundary(t, i, "primary")
        else:
            bob.boundary(t - 0.2, i, "primary")
    b = _report(alice, bob)["boundaries"]
    assert b["spacing_s"] == pytest.approx(INTERVAL_S, abs=0.01)
    assert b["ticks"] == 0 and b["unpaired"] == {"alice": 4, "bob": 4}
    assert b["interval_mismatch"]["ticks"] == 0


def test_a_primary_interval_without_a_number_is_left_out_not_guessed():
    """A failed KMS request logs no interval number, and a `serving this
    interval` line whose request fell before the window has no boundary time.
    Neither is paired; both are counted."""
    alice, bob = _pair("slog")
    _boundaries(alice, bob, [0.1] * 4, start=10.0)
    bob.kms_request_fails(10.0 + 4 * INTERVAL_S + 0.1)
    alice.boundary(10.0 + 4 * INTERVAL_S, 4, "backup")
    # a request just before --since, its number just after
    alice.primary_boundary(8.9995, 99, KMS_FETCH_S)
    rep = _report(alice, bob, since=R.parse_time(_docker_stamp(9.0)))
    b = rep["boundaries"]
    # bob's failed request is still the last boundary-like line: at the end of
    # the window it may be a fetch in flight, so it is not counted yet
    assert b["nodes"]["bob"]["primary_unnumbered"] == 0
    assert b["nodes"]["alice"]["number_without_request"] == 1
    assert b["ticks"] == 4 and b["unpaired"] == {"alice": 1, "bob": 0}
    bob.backup_waits(10.0 + 5 * INTERVAL_S + 0.1, 5)
    alice.boundary(10.0 + 5 * INTERVAL_S, 5, "primary")
    b = _report(alice, bob, since=R.parse_time(_docker_stamp(9.0)))["boundaries"]
    assert b["nodes"]["bob"]["primary_unnumbered"] == 1
    assert b["ticks"] == 5


def test_a_node_without_boundary_lines_is_warned_about():
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    rep = _report(alice, bob)
    assert rep["boundaries"]["offset_ms"] is None and rep["boundaries"]["ticks"] == 0
    assert sum("no interval boundary line in the window" in w for w in rep["warnings"]) == 2
    assert "offset bob - alice: n/a, no tick paired" in R.render(rep)


# ----------------------------------------------------------- input handling --

def test_lines_are_ordered_by_their_docker_stamps():
    """stdout and stderr are captured separately; order comes from the stamps."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    bob.responder_loaded(6.004, BOB_PREFIX, 2)
    ordered = _report(alice, bob)
    bob.rows.reverse()
    alice.rows.reverse()
    assert _report(alice, bob)["failures"] == ordered["failures"]


def test_since_and_until_bound_the_window():
    alice, bob = _pair("slog")
    for n in range(1, 7):
        _healthy(alice, bob, 1.0 + 3 * n, n, n % 2 == 1, _key(n))
    since = R.parse_time(f"{BASE}09Z")
    until = R.parse_time(f"{BASE}15Z")
    rep = _report(alice, bob, since=since, until=until)
    assert rep["cells"]["all"]["R"] == 2
    assert any("no process start in the window" in w for w in rep["warnings"])


def test_a_restart_inside_the_window_is_reported():
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.started(5.0)
    rep = _report(alice, bob)
    assert rep["process_starts"] == {"alice": 2, "bob": 1}
    assert any("process starts in the window" in w for w in rep["warnings"])


def test_logs_without_docker_timestamps_are_refused(tmp_path, capsys):
    a, b = tmp_path / "a.log", tmp_path / "b.log"
    a.write_text("07[ENC] parsed IKE_AUTH response 2 [ N(AUTH_FAILED) ]\n")
    b.write_text("")
    assert R.main(["report", "--alice", str(a), "--bob", str(b)]) == 2
    assert "docker logs -t" in capsys.readouterr().err


# ------------------------------------------------------------------ privacy --

# At least 16 hex digits (64 bits), or 32 base64 characters: shorter than any
# PSK, PPK or key_id this lane handles, longer than any word or count the
# report prints.
KEY_SHAPED = re.compile(r"[0-9a-fA-F]{16,}|[A-Za-z0-9+/]{32,}")


def _strings(value) -> list[str]:
    """Every string in a JSON value, keys included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (k, *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_nothing_identifying_reaches_the_output(tmp_path, capsys):
    """The logs carry key_ids, credential ids, identities and addresses; the
    report is made to be shared and must carry none of them."""
    alice, bob = _pair("slog")
    _healthy(alice, bob, 3.0, 1, True, _key(1))
    alice.primary_sends(6.0, _key(2))
    bob.backup_receives(6.001, _key(2))
    alice.rotated(6.002, ALICE_PREFIX, 2)
    bob.mismatch_responder(6.003)
    alice.auth_failed_initiator(6.0035)
    bob.responder_loaded(6.004, BOB_PREFIX, 2)
    # both fail-closed paths, whose lines carry a key_id, a peer and an error
    bob.no_key_id(8.0, 3)
    bob.responder_loaded(8.001, BOB_PREFIX, 3)
    alice.primary_sends(9.0, _key(3))
    bob.backup_receives(9.001, _key(3))
    alice.not_confirmed(9.5, _key(3))
    alice.rotated(9.502, ALICE_PREFIX, 3)
    # boundary lines, which carry the KMS address and the interval numbers
    _boundaries(alice, bob, [0.25] * 3, start=20.0)
    a, b = tmp_path / "a.log", tmp_path / "b.log"
    a.write_text(alice.text())
    b.write_text(bob.text())
    for extra in ([], ["--json"]):
        assert R.main(["report", "--alice", str(a), "--bob", str(b), *extra]) == 0
        out = capsys.readouterr().out
        for secret in (_key(1), _key(2), _key(3), ALICE_PREFIX, BOB_PREFIX, PPK_ID, *IDENTITIES,
                       PEER_ADDRESS.split(":")[0], "bob-ipsec:9998", "no ACK by", "bb84-kme"):
            assert secret not in out, f"the report printed {secret!r}"
        assert re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", out) is None
        # Nothing shaped like key material either: no long hex or base64 run in
        # any text the report prints. In the JSON form only the strings are
        # text; its numbers are full-precision floats, digits by design.
        texts = _strings(json.loads(out)) if extra else [out]
        assert not [t for t in texts if KEY_SHAPED.search(t)]
        # what the report does name: the arnika messages that failed closed,
        # and the boundary offset
        assert "no key_id from the peer" in out and "the peer did not confirm the key_id" in out
        if extra:
            assert json.loads(out)["boundaries"]["ticks"] == 3
        else:
            assert "offset bob - alice" in out


# --------------------------------------------------------------- statistics --

def test_clopper_pearson_matches_the_textbook_value():
    lo, hi = R.clopper_pearson(5, 10)
    assert lo == pytest.approx(0.187086, abs=1e-6)
    assert hi == pytest.approx(0.812914, abs=1e-6)


@pytest.mark.parametrize("n", [1, 10, 25_249])
def test_clopper_pearson_edges_have_closed_forms(n):
    alpha = 1 - R.CONFIDENCE
    lo, hi = R.clopper_pearson(0, n)
    assert lo == 0.0 and hi == pytest.approx(1 - (alpha / 2) ** (1 / n), rel=1e-9)
    lo, hi = R.clopper_pearson(n, n)
    assert hi == 1.0 and lo == pytest.approx((alpha / 2) ** (1 / n), rel=1e-9)


@pytest.mark.parametrize("k,n", [(1, 45), (16, 25_249), (9, 20_155), (4, 9)])
def test_clopper_pearson_is_symmetric(k, n):
    lo, hi = R.clopper_pearson(k, n)
    lo2, hi2 = R.clopper_pearson(n - k, n)
    assert lo == pytest.approx(1 - hi2, abs=1e-12)
    assert hi == pytest.approx(1 - lo2, abs=1e-12)


def test_clopper_pearson_agrees_with_scipy_on_the_live_demo_count():
    """16 failures in 25,249 rotations, the 8.8-day figure of docs/vici-ppk.md."""
    stats = pytest.importorskip("scipy.stats")
    alpha = 1 - R.CONFIDENCE
    lo, hi = R.clopper_pearson(16, 25_249)
    assert lo == pytest.approx(stats.beta.ppf(alpha / 2, 16, 25_249 - 16 + 1), rel=1e-9)
    assert hi == pytest.approx(stats.beta.ppf(1 - alpha / 2, 17, 25_249 - 16), rel=1e-9)


def test_clopper_pearson_refuses_what_it_cannot_bound():
    assert R.clopper_pearson(0, 0) is None
    assert R.clopper_pearson(3, 2) is None


def test_the_conditional_test_gives_the_planned_power_figure():
    """Nine race failures before and none after, at equal rotation counts:
    p = 0.5^9 one-sided, the figure the measurement plan was sized on."""
    t = R.conditional_binomial(9, 20_000, 0, 20_000)
    assert t["p_one_sided_b_lower"] == pytest.approx(0.5 ** 9)
    assert t["p_two_sided"] == pytest.approx(2 * 0.5 ** 9)
    assert R.conditional_binomial(3, 1000, 3, 1000)["p_two_sided"] == pytest.approx(1.0)
    assert R.conditional_binomial(0, 1000, 0, 1000) is None
    assert R.conditional_binomial(2, 0, 1, 1000) is None


def test_compare_reads_two_json_reports(tmp_path, capsys):
    reports = []
    for fails in (2, 0):
        alice, bob = _pair("slog")
        for n in range(1, 7):
            _healthy(alice, bob, 1.0 + 3 * n, n, n % 2 == 1, _key(n))
        for i in range(fails):
            t = 30.0 + 3 * i
            alice.primary_sends(t, _key(100 + i))
            bob.backup_receives(t + 0.001, _key(100 + i))
            alice.rotated(t + 0.002, ALICE_PREFIX, 7 + i)
            bob.mismatch_responder(t + 0.003)
            alice.auth_failed_initiator(t + 0.0035)
            bob.responder_loaded(t + 0.004, BOB_PREFIX, 7 + i)
        path = tmp_path / f"arm{len(reports)}.json"
        path.write_text(json.dumps(_report(alice, bob)))
        reports.append(path)
    assert R.main(["compare", str(reports[0]), str(reports[1]), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    cell = result["cells"]["alice PRIMARY"]
    assert cell["A"] == [2, 5] and cell["B"] == [0, 3]
    assert cell["test"]["n"] == 2


# ---------------------------------------------- the strings the parser keys on --

def _go_sources(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(root.rglob("*.go")) if not p.name.endswith("_test.go"))


def test_the_adapter_still_writes_the_lines_the_report_counts():
    """Wherever the port moves the adapter, its log text stays byte-identical;
    the report, /api/vpn/ppk-rotations and the CI job all count these."""
    src = _go_sources(ROOT / "services" / "arnika-vici")
    assert src, "no adapter Go source under services/arnika-vici"
    for fragment in ('"[INFO] [VICI] PPK rotated (id=%s ppk_id=%s bytes=%d)"',
                     '"[INFO] [VICI] PPK %s loaded; not reauthenticating (the peer "',
                     '"[INFO] [VICI] connected to %v %v on %s"'):
        assert fragment in src, f"the adapter no longer logs {fragment}"


def test_the_pinned_arnika_still_writes_the_lines_the_report_keys_on():
    if not (ARNIKA / "main.go").is_file():
        pytest.skip("arnika submodule not checked out")
    src = _go_sources(ARNIKA)
    for msg in ("sending the key_id to the peer", "received a key_id from the peer",
                "requesting the QKD key for the peer's key_id",
                "configuring a random PSK to invalidate the WireGuard session",
                "failed to configure the random PSK",
                *R.INVALIDATION_TRIGGERS, *R.TRIGGER_TO_INVALIDATION,
                "round agreed a fresh PQC key",
                # interval boundaries
                "waiting for a key_id from the peer", "requesting a new QKD key", "serving this interval",
                # the fixtures' other fail-closed paths
                "failed to retrieve a QKD key", "failed to retrieve the QKD key for the peer's key_id",
                "failed to retrieve the PQC key"):
        assert f'"{msg}"' in src, f"the pinned arnika no longer logs {msg!r}"
    assert 'With("role", "primary")' in src and 'With("role", "backup")' in src
    assert '"key_id", key.ID' in src, "the PRIMARY no longer logs the key_id attribute"
    assert '"round", round' in src, "the PQC round is no longer logged as round=N"
    assert src.count('"interval", intervalCounter)') == 2, (
        "the boundary lines no longer carry interval=N as the report reads it")


# The line ranges of the pinned main.go that the report's text and the
# adapter README cite, and what each must still contain. A pin bump that moves
# the code fails here, so the explanation of the boundary offset and of the
# trigger bookkeeping cannot go stale silently. The 3a8cc13 range the report
# also cites is not checked: that tree is not checked out.
MAIN_GO_CITATIONS = {
    (86, 94): ('"no QKD key received"', '"no QKD key, falling back to the PQC key"'),
    (118, 120): ('"no key material available for a PSK"',),
    (143, 145): ("logger.Error(reason, attrs...)",
                 '"configuring a random PSK to invalidate the WireGuard session"'),
    (327, 333): ("time.NewTicker(interval)", "ticker.Reset(interval)", "cfg.IsPrimary(intervalCounter)"),
    (349, 349): ("now.Truncate(time.Second).Add(time.Second)",),
    (409, 418): ("peerSentKeyID.Swap(false)", "if backup && !sawKeyID", '"no key_id from the peer"',
                 "setPSK(keyWriter, pqc, nil, cfg, backupLog)"),
}
README = ROOT / "services" / "arnika-vici" / "README.md"


def test_the_main_go_lines_the_report_cites_still_say_that():
    main_go = ARNIKA / "main.go"
    if not main_go.is_file():
        pytest.skip("arnika submodule not checked out")
    main = main_go.read_text(encoding="utf-8").splitlines()
    report, readme = SCRIPT.read_text(encoding="utf-8"), README.read_text(encoding="utf-8")
    for (first, last), fragments in MAIN_GO_CITATIONS.items():
        cite = f":{first}" if first == last else f":{first}-{last}"
        assert cite in report or cite in readme, f"main.go{cite} is no longer cited; drop it here"
        span = "\n".join(main[first - 1:last])
        missing = [f for f in fragments if f not in span]
        assert not missing, (
            f"main.go{cite} no longer contains {missing}. The arnika pin moved: re-read the code and "
            "update the citations in scripts/ppk_race_report.py and services/arnika-vici/README.md.")


def test_the_pinned_strongswan_still_writes_the_lines_the_report_keys_on():
    charon = STRONGSWAN / "src" / "libcharon"
    if not charon.is_dir():
        pytest.skip("strongswan submodule not checked out")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (
        charon / "plugins" / "vici" / "vici_cred.c",
        charon / "sa" / "ikev2" / "authenticators" / "psk_authenticator.c",
        charon / "sa" / "ikev2" / "tasks" / "ike_auth.c",
    ))
    for fragment in ("loaded %N shared key with id '%s'", "but MAC mismatched",
                     "using PPK for PPK_ID"):
        assert fragment in text, f"charon no longer logs {fragment!r}"
