"""Count PPK rotations, authentication failures and their causes on the IPsec lane.

Reads the `docker logs -t` text of the two IPsec nodes -- alice-ipsec, the IKE
initiator that drives every reauthentication, and bob-ipsec, the responder --
and applies counting rules that were written down BEFORE the before/after
measurement of the intermittent PPK mismatch, so the rules cannot be fitted to
the result.

Counts

  R   alice's key-driven rotations: its `PPK rotated (id=` lines, minus the
      writes an invalidation caused (a random PPK is not a rotation). An
      invalidation write is the first PPK load after arnika's `configuring a
      random PSK to invalidate` line (`configure random PSK to invalidate` at
      the previous pin), whatever made arnika fail closed: at f4cf9ba that
      includes a BACKUP interval that ended with `no key_id from the peer` and
      a PRIMARY whose peer never acknowledged (`the peer did not confirm the
      key_id`). Both triggers are counted by name in the report.
  F   alice's `N(AUTH_FAILED)` lines -- the same pattern /api/vpn/ppk-rotations
      counts. Bob's `MAC mismatched` lines corroborate and are used to classify.

Each failure belongs to the PPK generation alice held when it happened: the
last generation alice had loaded before it, in alice's own log order. The cell
is alice's arnika role in that generation's interval, PRIMARY (alice fetched
the QKD key and sent the key_id) or BACKUP (alice received the key_id).

Classes. Each failure takes exactly one, the first that matches, tried in
the order C1, C2, C5, C3, C4, and U when none matches (CLASS_ORDER below).
C5, C3 and C4 exclude each other -- bob either holds no generation carrying
alice's key_id, or holds one and the mismatch came before or after its load --
so their relative order changes no result; the report states it because it is
the order the code applies.

  C1 invalidation  arnika deliberately installed a random PPK: alice's
                   generation was written by an invalidation, or an
                   invalidation line on either node falls after the rotation
                   of the generation alice held BEFORE the current one and no
                   later than the failure. The window starts that early
                   because the invalidation that decides a failure can
                   precede the current generation's load: a BACKUP fails
                   closed at the end of its interval, and a PRIMARY either
                   before it sends the key_id (buildPSK failed) or after it
                   (no ACK came), in both cases before the peer's next load.
  C2 startup       the failure falls between a node's process start and that
                   node's first key-driven rotation (in the slog format, also
                   its first agreed PQC round).
  C3 race          in bob's OWN log, the mismatch comes before bob loaded the
                   generation carrying alice's key_id: bob answered with the
                   previous one.
  C4 divergence    bob had loaded that generation before the mismatch and
                   nothing invalidated it, so the two ends hold different bytes
                   under one key_id. Flagged as a read-gap candidate when a PQC
                   round was agreed on either node between the PRIMARY's
                   `sending the key_id` and the BACKUP's load (slog only).
  C5 lag           bob never loaded a generation carrying alice's key_id.
  U  unclassified  none of the above can be established from these logs, for
                   example because bob logged no mismatch near the failure.

Two choices the rules above leave open, fixed here:

  * Nodes are matched by key_id, not by generation number. Each node numbers
    its own writes, and after a lag the numbers drift apart: in the CI run of
    2026-08-27 bob's generation 3 carried the key alice installed as its
    generation 5. Generation numbers are used only when alice's generation
    carries no key_id, and the failure record says so.
  * Order WITHIN one container decides the class; time ACROSS containers only
    pairs a bob mismatch with an alice failure. Docker stamps a line when the
    daemon reads it, so two containers' stamps are milliseconds apart from the
    events, which is the scale of the race itself (docs/vici-ppk.md).

Both arnika log formats are read, so a before/after comparison applies one set
of rules to both arms:

  pin-era (3a8cc13)  Go `log` lines with bracketed tags and ANSI colour, e.g.
                     `PRIMARY[11] [SND] send key_id <id> to <peer>`
  slog (f4cf9ba)     log/slog key=value records, e.g.
                     `msg="sending the key_id to the peer" arnika_id=11
                     role=primary key_id=<id> peer=<peer>`

The VICI adapter's own lines (`PPK rotated (id=`, `PPK <id> loaded`) are the
same in both; under slog they arrive wrapped in msg="...".

Interval boundaries

Each arnika process counts its intervals from its own start, and its ticker
re-bases after its own processing (`ticker.Reset` at the top of the loop,
main.go:327-333 at f4cf9ba), so the two ends' boundaries can drift against
each other by milliseconds per interval whatever their start timing was. The
report pairs the two ends' boundaries per wall-clock tick and prints:

  * the offset, bob's boundary minus alice's: the median, 95th percentile and
    maximum of its size, the first and last offset, a least-squares slope,
    the change from one paired tick to the next, and the offset over the
    window in equal time segments. Beside each segment's median offset it
    prints how many of the segment's key_ids reached the BACKUP before the
    BACKUP's boundary of that tick (of the ticks where that could be told)
    and how many BACKUP intervals in it ended in a `no key_id from the peer`
    invalidation. Each node's total of those invalidations follows, with how
    many of them the paired ticks hold;
  * each PRIMARY's KMS fetch time, from its `requesting a new QKD key` line to
    its `serving this interval` line;
  * the paired ticks whose interval numbers differ (count, first and last
    time, and each difference), and the ticks in which both ends hold the same
    role. A restart of only one node, or two starts more than half an
    interval apart, leaves the counters apart, and the role elections, which
    hash the counter, then stop being complementary;
  * how many key_ids reached their receiver before the receiver's own boundary
    of the sender's tick (slog receivers only, see below).

The JSON form also lists every paired tick (`per_tick`): its time (alice's
boundary), the signed offset, d as defined below, both ends' interval numbers
and roles, the PRIMARY's KMS fetch time, whether that tick's key_id arrived
early, and, for each end that is BACKUP, whether its interval of that tick or
its next one (when it was BACKUP again) ended in a `no key_id from the peer`
invalidation. The text form leaves that list out: over a 168-hour window it
is about 20,000 records.

A boundary is the first line a role logs in an interval: a BACKUP's `waiting
for a key_id from the peer` and a PRIMARY's `requesting a new QKD key`. The
PRIMARY's interval number comes from the `serving this interval` line that
follows the KMS fetch; a PRIMARY interval whose KMS request failed logs no
number and is left out. The pin-era lines are `BACKUP for interval N, waiting
for key_id from peer`, `request QKD key from` and `PRIMARY for interval N`.
Ticks pair as mutual nearest neighbours closer than half an interval, the
interval being read from each node's boundaries and interval numbers, so an
offset is always under half an interval: a start gap of more
than half an interval shows as an interval-number mismatch, with the rest of
the gap as the offset. Docker stamps each line when the daemon reads it, so an
offset carries the millisecond jitter described above.

At the previous pin a BACKUP logs its boundary only when no key_id has reached
it since its previous boundary (the skip channel, main.go:155-160 at 3a8cc13).
The pin-era arm therefore pairs mainly the role changes at which the key_id
came after the BACKUP's boundary: its offsets are a biased sample, and early
arrivals are not counted for a pin-era receiver.

Why the offset matters is an inference from the code, not a measurement. Per
tick, let d be the BACKUP's boundary minus the PRIMARY's boundary: +offset
when alice is PRIMARY, -offset when bob is. The PRIMARY sends its key_id at
the next whole second after its KMS fetch (main.go:349), and the send also
waits for the PSK build. For d below about a second, the chance that the
PRIMARY's key_id arrives before the BACKUP's boundary ("early") is then
roughly min(1, max(0, d - t_KMS) / 1 s), with t_KMS the PRIMARY's KMS fetch
time, if over a long run the fraction of a second at which the fetch ends is
spread evenly. An early key_id is counted in the BACKUP's previous interval
(main.go:409-418). The BACKUP fails closed at the end of the current interval
only if the next interval's key_id is not early too, which in practice means
at its BACKUP-to-PRIMARY transitions. In the one unaligned local run of
2026-09-26 (13 paired ticks, about 6 minutes) the offset went from about
255 ms to about 217 ms over 12 intervals; bob received early key_ids in
intervals 2-8, 10 and 11 and invalidated only at the ends of 8 and 11, each
followed by a bob-PRIMARY interval. That is one observation, not a
measurement.

Output is counts, generation numbers, cells, classes, the arnika messages that
triggered each invalidation, boundary offsets, interval numbers and roles, and
docker timestamps. It never prints a key_id, a credential id, an identity or
an address, because the logs carry all four and a report is made to be
shared; key_ids are described by shape only (UUID or not). It prints no log
line, so key material a log might carry cannot reach it.

Usage
  python scripts/ppk_race_report.py report --alice A.log --bob B.log
  python scripts/ppk_race_report.py report --docker
      [--since 2026-09-26T00:00:00Z] [--until ...] [--json]
  python scripts/ppk_race_report.py compare ARM_A.json ARM_B.json [--class C3]

`compare` reads two `report --json` outputs and tests whether the class rate
differs between the arms with an exact conditional binomial test: given
k_A + k_B failures, k_A ~ Binomial(k_A + k_B, R_A / (R_A + R_B)) under equal
rates.

Standard library only, so the CI runner's own python3 runs it. Exit status: 0
done, 2 usage or input error.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# The container_name values in docker-compose.strongswan.yml. alice-ipsec is the
# initiator (VICI_IKE_ROLE: initiator), which is why failures are counted there.
ALICE_CONTAINER = "alice-ipsec"
BOB_CONTAINER = "bob-ipsec"

# Two-sided coverage of every interval printed: the conventional 95 %.
CONFIDENCE = 0.95

# Largest gap allowed between a bob mismatch and the alice failure it is paired
# with, in the cross-container (docker timestamp) clock. The gaps measured
# between the two nodes on the live demo are milliseconds: alice's key_id send
# to bob's receipt about 1.5 ms (12.7 ms at worst), bob's MAC failure to bob's
# load a median of 1.7 ms (15.3 ms at worst) -- docs/vici-ppk.md, 8.8 days.
# One second is nearly two orders of magnitude above the worst of them and
# still 1/30 of the 30 s rotation interval, so a mismatch from a neighbouring
# interval cannot be paired by accident. It only pairs; the class is decided
# in bob's own log order.
PAIRING_TOLERANCE_NS = 1_000_000_000

NS_PER_S = 1_000_000_000
NS_PER_MS = 1_000_000
NS_PER_HOUR = 3600 * NS_PER_S

# Two boundaries pair as one wall-clock tick only when they are closer than
# this fraction of the interval as the logs show it (boundary_spacing_ns).
# Past half an interval a boundary lies nearer to the other node's previous or
# next tick than to its own, so half is the widest value that still means "the
# same tick".
TICK_PAIRING_FRACTION = 0.5
# The percentile of the offset's size the report prints beside its median and
# maximum, by the nearest-rank method.
OFFSET_PERCENTILE = 95
# The offset over the window is printed in this many equal time segments. The
# planned measurement window is 168 h, so each segment is one day of it.
OFFSET_TREND_SEGMENTS = 7

# Precision of the incomplete-beta evaluation and of the bisection that inverts
# it. 1e-15 is at the resolution of an IEEE double near 1, so iterating further
# changes nothing; the iteration cap only stops a pathological input.
_EPS = 1e-15
_MAX_CF_ITERATIONS = 10_000
_BISECTION_STEPS = 200

# Relative slack when collecting "at most as likely as observed" outcomes for the
# two-sided binomial p-value, so ties that differ only by rounding are kept. The
# same device, with the same size, as scipy.stats.binomtest.
_TIE_SLACK = 1e-7

# ------------------------------------------------------------------ parsing --

_DOCKER_TS = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})\s(.*)$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# VICI adapter and charon; identical in both arnika formats.
_ROTATED = re.compile(r"PPK rotated \(id=(\S+?)-(\d+) ")
_ADAPTER_LOADED = re.compile(r"PPK (\S+?)-(\d+) loaded")
_CHARON_LOADED = re.compile(r"loaded PPK shared key with id '(\S+?)-(\d+)'")
_AUTH_FAILED = re.compile(r"N\(AUTH_FAILED\)")
_MAC_MISMATCH = re.compile(r"but MAC mismatched")
_PPK_APPLIED = re.compile(r"using PPK for PPK_ID")
# The adapter logs this once per process, from its constructor.
_PROCESS_START = re.compile(r"\[VICI\] connected to ")

# arnika. Invalidation: pin main.go `[STOP] configure random PSK to invalidate`,
# the pin-era adapter's own `[VICI] invalidating tunnel`, and f4cf9ba main.go
# `configuring a random PSK to invalidate`.
_INVALIDATION = re.compile(
    r"configure random PSK to invalidate|configuring a random PSK to invalidate"
    r"|\[VICI\] invalidating tunnel")
# The invalidation's own write failed, so no random PPK follows: pin main.go
# `failed to configure random PSK`, f4cf9ba main.go `failed to configure the
# random PSK`.
_INVALIDATION_WRITE_FAILED = re.compile(r"failed to configure (?:the )?random PSK")
# What made arnika fail closed, when it is one of the two f4cf9ba paths this
# report names: main.go logs the trigger, then the reason buildPSK gives for
# the missing key, then the invalidation line. Any other path (a KMS or PQC
# failure, a failed write) is counted as "other".
TRIGGER_NO_KEY_ID = "no key_id from the peer"
INVALIDATION_TRIGGERS = (TRIGGER_NO_KEY_ID, "the peer did not confirm the key_id")
TRIGGER_OTHER = "other"
_TRIGGER = re.compile(r'msg="(' + "|".join(map(re.escape, INVALIDATION_TRIGGERS)) + r')"')
# The BACKUP interval a `no key_id from the peer` line names: main.go logs the
# counter of the interval that just ended (main.go:409-418 at f4cf9ba).
_SLOG_INTERVAL = re.compile(r"\binterval=(\d+)")
# The only lines main.go logs between a trigger and the invalidation it causes.
# Both triggers call setPSK with no QKD key; buildPSK then records why it has
# no PSK, and invalidate() logs that reason just before the invalidation line
# (main.go:86-94, :118-120 and :143-145 at f4cf9ba). Under a QKD-required MODE
# the reason is `no QKD key received`; otherwise PQC is off, and the fallback
# warning and `no key material available for a PSK` come instead. A trigger
# stays pending across these and across lines that are not arnika's
# (charon's), and ends at any other arnika line: `the peer did not confirm the
# key_id` is also logged when buildPSK had already failed and invalidated
# before the send, and then no invalidation follows it.
TRIGGER_TO_INVALIDATION = ("no QKD key received", "no QKD key, falling back to the PQC key",
                           "no key material available for a PSK")
_TRIGGER_TO_INVALIDATION = re.compile(
    r'msg="(?:' + "|".join(map(re.escape, TRIGGER_TO_INVALIDATION)) + r')"')
_SLOG = re.compile(r"\blevel=[A-Z]+ msg=")
_SLOG_ROLE = re.compile(r"\brole=(primary|backup)\b")
_SLOG_KEY_ID = re.compile(r'\bkey_id="?([^\s"]+)')
_SLOG_SENT = re.compile(r'msg="sending the key_id to the peer"')
_SLOG_ROUND = re.compile(r'msg="round agreed a fresh PQC key".*?\bround=(\d+)')
_PIN_ROLE = re.compile(r"\b(PRIMARY|BACKUP)\[\d+\]")
_PIN_KEY_ID = re.compile(r"\bkey_id (\S+)")
_PIN_SENT = re.compile(r"\[SND\] send key_id ")
# A key_id as the receiving end logs it (transport/server.go at f4cf9ba,
# udpserver.go at the previous pin).
_SLOG_RECEIVED = re.compile(r'msg="received a key_id from the peer"')
_PIN_RECEIVED = re.compile(r"\[RCV\] received key_id ")

# Interval boundaries (see "Interval boundaries" above). A BACKUP's first line
# carries the interval number; a PRIMARY's first line is its KMS request, and
# the number follows after the fetch.
_SLOG_BACKUP_BOUNDARY = re.compile(r'msg="waiting for a key_id from the peer".*?\binterval=(\d+)')
_SLOG_PRIMARY_REQUEST = re.compile(r'msg="requesting a new QKD key"')
_SLOG_PRIMARY_NUMBER = re.compile(r'msg="serving this interval".*?\binterval=(\d+)')
_PIN_BACKUP_BOUNDARY = re.compile(r"\[REQ\] BACKUP for interval (\d+), waiting for key_id from peer")
_PIN_PRIMARY_REQUEST = re.compile(r"\[REQ\] request QKD key from ")
_PIN_PRIMARY_NUMBER = re.compile(r"\[REQ\] PRIMARY for interval (\d+)")

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

CELLS = ("alice PRIMARY", "alice BACKUP", "role unknown")
# Column order of the report.
CLASSES = ("C1", "C2", "C3", "C4", "C5", "U")
# The order classify() tries them in; the first match wins.
CLASS_ORDER = ("C1", "C2", "C5", "C3", "C4", "U")
CLASS_NAMES = {"C1": "invalidation", "C2": "startup", "C3": "race", "C4": "divergence",
               "C5": "lag", "U": "unclassified"}


class InputError(Exception):
    """The logs cannot be read under these rules."""


@dataclass
class Line:
    t: int      # docker timestamp, ns since the epoch
    idx: int    # position in this node's own log order
    text: str   # message, ANSI colour removed


@dataclass
class Generation:
    number: int
    first_idx: int              # first evidence of the load, own log order
    first_t: int
    rot_idx: int | None = None  # the adapter's `PPK rotated` line
    rot_t: int | None = None
    key_id: str | None = None
    role: str | None = None     # "primary" / "backup"
    invalidation: bool = False
    trigger: str | None = None  # for an invalidation write: what failed closed
    key_sent_t: int | None = None


@dataclass
class Boundary:
    """The start of one arnika interval on one node."""
    line: Line                  # the first line the role logs in the interval
    interval: int               # arnika's per-process interval counter
    role: str                   # "primary" / "backup"
    fetch_ns: int | None = None  # PRIMARY: KMS request to `serving this interval`


@dataclass
class Node:
    name: str
    lines: list[Line]
    generations: list[Generation] = field(default_factory=list)
    auth_failed: list[Line] = field(default_factory=list)
    mismatches: list[Line] = field(default_factory=list)
    invalidations: list[Line] = field(default_factory=list)
    rounds: list[Line] = field(default_factory=list)
    starts: list[Line] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)
    # A KMS request that the next interval superseded before any `serving
    # this interval` line: the fetch failed, and the interval has no number.
    unnumbered_primary: int = 0
    # A `serving this interval` line with no KMS request before it in the
    # window, so its boundary time is unknown.
    number_without_request: int = 0
    # Each `no key_id from the peer` line that the invalidation it causes
    # followed, with the interval number the line names (None if it names
    # none).
    no_key_id_invalidations: list[tuple[Line, int | None]] = field(default_factory=list)
    sends: list[tuple[Line, str]] = field(default_factory=list)      # key_ids this node sent
    receipts: list[tuple[Line, str]] = field(default_factory=list)   # key_ids it received
    ppk_applied: int = 0
    slog_lines: int = 0
    pin_lines: int = 0
    key_ids: set[str] = field(default_factory=set)
    untimestamped: int = 0

    @property
    def format(self) -> str:
        if self.slog_lines and self.pin_lines:
            return "mixed"
        if self.slog_lines:
            return "slog"
        if self.pin_lines:
            return "pin-era"
        return "none"


def _parse_ts(stamp: str, frac: str | None, zone: str) -> int:
    base = datetime.fromisoformat(stamp + ("+00:00" if zone == "Z" else zone))
    return int(base.timestamp()) * NS_PER_S + int((frac or "").ljust(9, "0"))


def parse_time(value: str) -> int:
    """An RFC 3339 instant, as the --since/--until options take it."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$",
                 value.strip())
    if not m:
        raise InputError(f"not an RFC 3339 instant with a zone: {value!r}")
    return _parse_ts(m.group(1), m.group(2), m.group(3))


def format_time(t_ns: int) -> str:
    secs, ns = divmod(t_ns, NS_PER_S)
    return datetime.fromtimestamp(secs, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ns // 1000:06d}Z"


def read_lines(text: str, since: int | None = None, until: int | None = None
               ) -> tuple[list[Line], int]:
    """Timestamped lines in time order, and how many carried no stamp.

    A line with no docker stamp (a wrapped continuation) takes the stamp of the
    line before it. Sorting is stable, so lines of one stream keep their order;
    it matters when stdout and stderr were captured separately.
    """
    raw: list[tuple[int, str]] = []
    last: int | None = None
    bare = 0
    for line in text.splitlines():
        m = _DOCKER_TS.match(line)
        if m:
            last = _parse_ts(m.group(1), m.group(2), m.group(3))
            raw.append((last, m.group(4)))
        elif line.strip():
            bare += 1
            if last is not None:
                raw.append((last, line))
    if text.strip() and not raw:
        raise InputError("no line carries a docker timestamp; export the logs with `docker logs -t`")
    raw.sort(key=lambda r: r[0])
    kept = [(t, s) for t, s in raw
            if (since is None or t >= since) and (until is None or t < until)]
    return [Line(t, i, _ANSI.sub("", s)) for i, (t, s) in enumerate(kept)], bare


def parse_node(name: str, text: str, since: int | None = None, until: int | None = None) -> Node:
    lines, bare = read_lines(text, since, until)
    node = Node(name, lines, untimestamped=bare)
    by_number: dict[int, Generation] = {}
    cur_key: str | None = None
    cur_role: str | None = None
    sent_t: int | None = None
    key_idx: int | None = None      # line of the last key_id taken into cur_key
    last_rotated_key: str | None = None
    # An invalidation line announces one random write. It stays pending until
    # the next PPK load, which is that write, or until arnika reports that the
    # write failed. A key_id line does not end it: a key_id that arrives while
    # the random write is in flight is written after it, because
    # KeyWriterService serialises writes and the key_id's own write waits for
    # a KMS request first.
    pending_invalidation = False
    inv_idx = -1
    inv_role: str | None = None
    inv_trigger: str | None = None
    last_trigger: str | None = None
    # The line of the last trigger and the interval number it names; read
    # only while last_trigger still says which trigger that was.
    trigger_at: tuple[Line, int | None] | None = None
    # A PRIMARY's KMS request line, until the `serving this interval` line
    # that numbers its interval.
    pending_request: Line | None = None

    for ln in lines:
        s = ln.text
        slog = bool(_SLOG.search(s))
        if slog:
            node.slog_lines += 1
        elif _PIN_ROLE.search(s):
            node.pin_lines += 1

        if _PROCESS_START.search(s):
            node.starts.append(ln)
        if _AUTH_FAILED.search(s):
            node.auth_failed.append(ln)
        if _MAC_MISMATCH.search(s):
            node.mismatches.append(ln)
        if _PPK_APPLIED.search(s):
            node.ppk_applied += 1
        if slog and _SLOG_ROUND.search(s):
            node.rounds.append(ln)

        # Role and key_id, in the vocabulary of the line's own format. A pin-era
        # pattern read against a slog line would take "dropped;" out of "QKD
        # queue full, key_id dropped", so the two are never mixed on one line.
        if slog:
            role_m, key_m, sent = _SLOG_ROLE.search(s), _SLOG_KEY_ID.search(s), _SLOG_SENT.search(s)
            received = _SLOG_RECEIVED.search(s)
            role = role_m.group(1) if role_m else None
        else:
            role_m, key_m, sent = _PIN_ROLE.search(s), _PIN_KEY_ID.search(s), _PIN_SENT.search(s)
            received = _PIN_RECEIVED.search(s)
            role = role_m.group(1).lower() if role_m else None
        if role:
            cur_role = role
            # A key id contains a digit; "from" in "waiting for key_id from
            # peer" does not, and is prose rather than an identifier.
            key = key_m.group(1).rstrip(".,;") if key_m else None
            if key and any(c.isdigit() for c in key):
                if sent:
                    node.sends.append((ln, key))
                elif received:
                    node.receipts.append((ln, key))
                if key != last_rotated_key:
                    cur_key, key_idx = key, ln.idx
                    node.key_ids.add(key)
                    if sent:
                        sent_t = ln.t

        # Interval boundaries: see "Interval boundaries" in the module text.
        backup_m = (_SLOG_BACKUP_BOUNDARY if slog else _PIN_BACKUP_BOUNDARY).search(s)
        number_m = (_SLOG_PRIMARY_NUMBER if slog else _PIN_PRIMARY_NUMBER).search(s)
        if backup_m:
            node.unnumbered_primary += pending_request is not None
            node.boundaries.append(Boundary(ln, int(backup_m.group(1)), "backup"))
            pending_request = None
        elif (_SLOG_PRIMARY_REQUEST if slog else _PIN_PRIMARY_REQUEST).search(s):
            node.unnumbered_primary += pending_request is not None
            pending_request = ln
        elif number_m:
            if pending_request is None:
                node.number_without_request += 1
            else:
                node.boundaries.append(Boundary(pending_request, int(number_m.group(1)), "primary",
                                                ln.t - pending_request.t))
            pending_request = None

        # A trigger is credited only to the invalidation it causes; see
        # TRIGGER_TO_INVALIDATION for the lines that may come between them.
        if slog:
            trigger_m = _TRIGGER.search(s)
            if trigger_m:
                last_trigger = trigger_m.group(1)
                interval_m = _SLOG_INTERVAL.search(s)
                trigger_at = (ln, int(interval_m.group(1)) if interval_m else None)
            elif not (_TRIGGER_TO_INVALIDATION.search(s) or _INVALIDATION.search(s)):
                last_trigger = None

        if _INVALIDATION.search(s):
            node.invalidations.append(ln)
            if last_trigger == TRIGGER_NO_KEY_ID and trigger_at is not None:
                node.no_key_id_invalidations.append(trigger_at)
                trigger_at = None
            # The previous pin logs two lines for one invalidation, arnika's
            # and then the adapter's; the second must not reset the first.
            if not pending_invalidation:
                inv_role, inv_trigger = role or cur_role, last_trigger or TRIGGER_OTHER
                last_trigger = None
            pending_invalidation, inv_idx = True, ln.idx
        if _INVALIDATION_WRITE_FAILED.search(s):
            pending_invalidation = False

        # The first sign of a generation -- usually charon's load, then the
        # adapter's lines -- takes the interval's state, because every line
        # that decides it (role, key_id, invalidation) comes before the load.
        # Taking it at the adapter's `PPK rotated` line instead would leave a
        # generation whose reauthentication failed before that line with no
        # role and no key_id.
        for pattern in (_CHARON_LOADED, _ADAPTER_LOADED, _ROTATED):
            m = pattern.search(s)
            if m and int(m.group(2)) not in by_number:
                g = Generation(int(m.group(2)), ln.idx, ln.t)
                by_number[g.number] = g
                # A trigger seen before this write is spent: it either made
                # this write or made none.
                last_trigger = None
                if pending_invalidation:
                    g.invalidation, g.role, g.trigger = True, inv_role, inv_trigger
                    pending_invalidation = False
                    # A key_id taken before the invalidation line belonged to
                    # the attempt that failed closed and is never written. One
                    # taken after it belongs to the next write, so it stays.
                    if key_idx is None or key_idx < inv_idx:
                        cur_key, cur_role, sent_t, key_idx = None, None, None, None
                    last_rotated_key = None
                else:
                    g.key_id, g.role = cur_key, cur_role
                    g.key_sent_t = sent_t if cur_role == "primary" else None
                    last_rotated_key = g.key_id
                    cur_key, cur_role, sent_t, key_idx = None, None, None, None
        m = _ROTATED.search(s)
        if m:
            g = by_number[int(m.group(2))]
            g.rot_idx, g.rot_t = ln.idx, ln.t

    node.generations = sorted(by_number.values(), key=lambda g: g.first_idx)
    node.boundaries.sort(key=lambda b: b.line.idx)
    return node


# ------------------------------------------------------------ classification --

@dataclass
class Failure:
    line: Line
    generation: Generation | None
    cell: str
    klass: str
    matched_by: str | None = None
    read_gap_candidate: bool | None = None


def _generation_at(node: Node, idx: int) -> tuple[Generation | None, Generation | None]:
    """The generation loaded before `idx` in the node's own order, and the one before it."""
    current = previous = None
    for g in node.generations:
        if g.first_idx < idx:
            previous, current = current, g
        else:
            break
    return current, previous


def _cell(g: Generation | None) -> str:
    if g is None or g.role is None:
        return "role unknown"
    return "alice PRIMARY" if g.role == "primary" else "alice BACKUP"


def _startup_windows(node: Node) -> list[tuple[int, int]]:
    """[start, end) for each process start: until the first key-driven rotation,
    and in the slog format also until the first agreed PQC round."""
    windows = []
    for st in node.starts:
        rot = next((g.rot_t for g in node.generations
                    if g.rot_t is not None and not g.invalidation and g.rot_t >= st.t), None)
        end = rot if rot is not None else math.inf
        # A node that logs no round at all cannot be waited on for one; the
        # report warns about that separately rather than calling every
        # failure a startup failure.
        if node.format in ("slog", "mixed") and node.rounds:
            rnd = next((r.t for r in node.rounds if r.t >= st.t), None)
            end = max(end, rnd if rnd is not None else math.inf)
        windows.append((st.t, end))
    return windows


def classify(alice: Node, bob: Node) -> list[Failure]:
    windows = _startup_windows(alice) + _startup_windows(bob)
    invalidations = alice.invalidations + bob.invalidations
    bob_by_key = {g.key_id: g for g in bob.generations if g.key_id and not g.invalidation}
    bob_by_number = {g.number: g for g in bob.generations if not g.invalidation}
    consumed: set[int] = set()
    out: list[Failure] = []

    for f in alice.auth_failed:
        g, prev = _generation_at(alice, f.idx)
        fail = Failure(f, g, _cell(g), "U")
        out.append(fail)

        since = -math.inf
        if prev is not None:
            since = prev.rot_t if prev.rot_t is not None else prev.first_t
        if (g is not None and g.invalidation) or any(since < i.t <= f.t for i in invalidations):
            fail.klass = "C1"
            continue
        if any(a <= f.t < b for a, b in windows):
            fail.klass = "C2"
            continue
        if g is None:
            # Before the first load in the window but outside every startup
            # window: the window was cut, and which PPK alice held is unknown.
            continue

        if g.key_id is not None:
            peer, fail.matched_by = bob_by_key.get(g.key_id), "key_id"
        else:
            peer, fail.matched_by = bob_by_number.get(g.number), "generation number"
        if peer is None:
            fail.klass = "C5"
            continue

        # Pair with the nearest unconsumed bob mismatch in the tolerance window,
        # by the cross-container clock; classify by bob's own order.
        lo, hi = g.first_t - PAIRING_TOLERANCE_NS, f.t + PAIRING_TOLERANCE_NS
        candidates = [m for m in bob.mismatches if lo <= m.t <= hi and m.idx not in consumed]
        if not candidates:
            continue
        mismatch = min(candidates, key=lambda m: abs(m.t - f.t))
        consumed.add(mismatch.idx)
        if mismatch.idx < peer.first_idx:
            fail.klass = "C3"
            continue
        fail.klass = "C4"
        if {alice.format, bob.format} & {"slog", "mixed"}:
            primary, backup = (g, peer) if g.role == "primary" else (peer, g)
            sent = primary.key_sent_t
            if sent is None:
                fail.read_gap_candidate = None
            else:
                a, b = sorted((sent, backup.first_t))
                fail.read_gap_candidate = any(a < r.t < b for r in alice.rounds + bob.rounds)
    return out


# ------------------------------------------------------- interval boundaries --

# Offsets are reported in milliseconds to this many decimals: microseconds,
# finer than the docker stamps' millisecond jitter, coarser than their digits.
_MS_DECIMALS = 3


@dataclass
class Tick:
    """One wall-clock tick: a boundary of each node, paired."""
    alice: Boundary
    bob: Boundary

    @property
    def t(self) -> int:
        """The tick's time: alice's boundary."""
        return self.alice.line.t

    @property
    def offset_ns(self) -> int:
        """bob's boundary minus alice's."""
        return self.bob.line.t - self.alice.line.t

    @property
    def primary(self) -> Boundary | None:
        """The PRIMARY's boundary, when exactly one end is PRIMARY."""
        roles = (self.alice.role, self.bob.role)
        if roles == ("primary", "backup"):
            return self.alice
        if roles == ("backup", "primary"):
            return self.bob
        return None

    @property
    def d_ns(self) -> int | None:
        """The BACKUP's boundary minus the PRIMARY's: +offset when alice is
        PRIMARY, -offset when bob is, None when both ends hold one role."""
        primary = self.primary
        if primary is None:
            return None
        return self.offset_ns if primary is self.alice else -self.offset_ns


def _ms(ns: float) -> float:
    return round(ns / NS_PER_MS, _MS_DECIMALS)


def boundary_spacing_ns(*nodes: Node) -> float | None:
    """The interval as the logs show it: the median time per interval number
    between one node's consecutive boundaries, over all the nodes.

    Each gap is divided by the difference of the two interval numbers, so a
    boundary missing from the log (a pin-era BACKUP, a PRIMARY whose KMS
    request failed) does not stretch it; a counter that went back (a restart)
    gives no value. A KMS retry shortens single values, which the median
    ignores.
    """
    per_interval = [(b.line.t - a.line.t) / (b.interval - a.interval) for node in nodes
                    for a, b in zip(node.boundaries, node.boundaries[1:]) if b.interval > a.interval]
    return statistics.median(per_interval) if per_interval else None


def _nearest(times: list[int], t: int) -> int | None:
    """Index of the entry of the sorted `times` nearest to `t`."""
    k = bisect.bisect_left(times, t)
    candidates = [i for i in (k - 1, k) if 0 <= i < len(times)]
    return min(candidates, key=lambda i: abs(times[i] - t)) if candidates else None


def pair_ticks(alice: Node, bob: Node, spacing_ns: float) -> list[Tick]:
    """Pair boundaries that are each other's nearest and in the same tick.

    Mutual nearest neighbours, so a node's extra boundary (a KMS retry) cannot
    take the other node's boundary from the one it belongs with.
    """
    a_times = [b.line.t for b in alice.boundaries]
    b_times = [b.line.t for b in bob.boundaries]
    limit = TICK_PAIRING_FRACTION * spacing_ns
    ticks = []
    for i, t in enumerate(a_times):
        j = _nearest(b_times, t)
        if j is None or abs(b_times[j] - t) >= limit or _nearest(a_times, b_times[j]) != i:
            continue
        ticks.append(Tick(alice.boundaries[i], bob.boundaries[j]))
    return ticks


def _nearest_rank(sorted_values: list[float], percentile: float) -> float:
    return sorted_values[max(1, math.ceil(percentile / 100 * len(sorted_values))) - 1]


def _least_squares_slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _offset_summary(ticks: list[Tick]) -> dict | None:
    if not ticks:
        return None
    offsets = [tk.offset_ns for tk in ticks]
    sizes = sorted(abs(o) for o in offsets)
    steps = sorted(abs(b - a) for a, b in zip(offsets, offsets[1:]))
    hours = [(tk.t - ticks[0].t) / NS_PER_HOUR for tk in ticks]
    slope = _least_squares_slope(hours, [o / NS_PER_MS for o in offsets])
    return {
        "abs_median_ms": _ms(statistics.median(sizes)),
        f"abs_p{OFFSET_PERCENTILE}_ms": _ms(_nearest_rank(sizes, OFFSET_PERCENTILE)),
        "abs_max_ms": _ms(sizes[-1]),
        "first_ms": _ms(offsets[0]),
        "last_ms": _ms(offsets[-1]),
        "slope_ms_per_hour": None if slope is None else round(slope, _MS_DECIMALS),
        "step_abs_median_ms": _ms(statistics.median(steps)) if steps else None,
        "step_abs_max_ms": _ms(steps[-1]) if steps else None,
        "bob_later": sum(1 for o in offsets if o > 0),
    }


def _key_id_arrivals(sender: Node, receiver: Node, partner: dict[int, Boundary]
                     ) -> list[tuple[int, bool]] | None:
    """For each key_id the sender sent and the receiver logged: the line index
    of the sender's boundary of that tick, and whether the receiver logged the
    key_id before its own boundary of the same tick.

    The sender's tick is its last boundary before the send, in its own log
    order; `partner` maps that boundary (by line index) to the receiver's
    boundary of the same tick. The comparison is in the receiver's own log
    order. None for a receiver in the pin-era format, which logs no BACKUP
    boundary once a key_id has arrived (see "Interval boundaries").
    """
    if receiver.format != "slog":
        return None
    first_receipt: dict[str, Line] = {}
    for ln, key in receiver.receipts:
        first_receipt.setdefault(key, ln)
    sender_idx = [b.line.idx for b in sender.boundaries]
    out = []
    for ln, key in sender.sends:
        k = bisect.bisect_left(sender_idx, ln.idx) - 1
        own = sender.boundaries[k].line.idx if k >= 0 else None
        peer = partner.get(own) if own is not None else None
        receipt = first_receipt.get(key)
        if peer is None or receipt is None:
            continue
        out.append((own, receipt.idx < peer.line.idx))
    return out


def early_key_ids(arrivals: list[tuple[int, bool]] | None) -> dict | None:
    """Of the key_ids _key_id_arrivals matched, how many were early."""
    if arrivals is None:
        return None
    return {"early": sum(early for _, early in arrivals), "matched": len(arrivals)}


# Values of a BACKUP's `no_key_id_invalidation` in the per-tick list: its
# interval of this tick ended in a `no key_id from the peer` invalidation, or
# its next interval did (it was BACKUP again), or neither did.
NO_KEY_ID_THIS, NO_KEY_ID_NEXT, NO_KEY_ID_NONE = "this interval", "next interval", "none"


def _no_key_id_ends(node: Node) -> set[int]:
    """Line indices of the node's BACKUP boundaries whose interval ended in a
    `no key_id from the peer` invalidation.

    Each invalidation belongs to the node's last boundary before its trigger
    line, in the node's own log order, when that boundary is a BACKUP's with
    the interval number the trigger names. One that fits no boundary (its
    interval started before the window, or a boundary line is missing) is
    left out of the per-tick list and the segments, and still counted in the
    node's total.
    """
    starts = [b.line.idx for b in node.boundaries]
    ends = set()
    for trigger, number in node.no_key_id_invalidations:
        k = bisect.bisect_left(starts, trigger.idx) - 1
        if k >= 0 and node.boundaries[k].role == "backup" and node.boundaries[k].interval == number:
            ends.add(node.boundaries[k].line.idx)
    return ends


def _no_key_id_outcome(node: Node, pos: int, ends: set[int]) -> str | None:
    """How the BACKUP interval that starts at node.boundaries[pos] ended.

    None when it cannot be told: the node is PRIMARY there, its log is not in
    the slog format (the previous pin has no such path), the interval's end
    is past the window, or this interval ended cleanly but the next one,
    BACKUP again, ends past the window.
    """
    b = node.boundaries[pos]
    if node.format != "slog" or b.role != "backup":
        return None
    if b.line.idx in ends:
        return NO_KEY_ID_THIS
    if pos + 1 >= len(node.boundaries):
        return None
    nxt = node.boundaries[pos + 1]
    if nxt.role != "backup" or nxt.interval != b.interval + 1:
        return NO_KEY_ID_NONE
    if nxt.line.idx in ends:
        return NO_KEY_ID_NEXT
    return NO_KEY_ID_NONE if pos + 2 < len(node.boundaries) else None


def _per_tick(alice: Node, bob: Node, ticks: list[Tick],
              arrivals: dict[str, list[tuple[int, bool]] | None]) -> list[dict]:
    """One record per paired tick, for the JSON form only.

    `time` is alice's boundary, `offset_ms` bob's boundary minus alice's, and
    `d_ms` the BACKUP's boundary minus the PRIMARY's (None when both ends hold
    one role). `key_id_early` says whether the PRIMARY's key_id reached the
    BACKUP before the BACKUP's boundary of this tick (None when it cannot be
    told), and each end's `no_key_id_invalidation` how its BACKUP interval of
    this tick ended (see _no_key_id_outcome). No key_id and no address.
    """
    early_at: dict[str, dict[int, bool]] = {}
    for sender, pairs in arrivals.items():
        early_at[sender] = {}
        for own, early in pairs or ():
            early_at[sender].setdefault(own, early)
    ends = {node.name: _no_key_id_ends(node) for node in (alice, bob)}
    position = {node.name: {b.line.idx: i for i, b in enumerate(node.boundaries)} for node in (alice, bob)}
    out = []
    for tk in ticks:
        primary = tk.primary
        sender = None if primary is None else ("alice" if primary is tk.alice else "bob")
        d = tk.d_ns
        record = {
            "time": format_time(tk.t),
            "offset_ms": _ms(tk.offset_ns),
            "d_ms": None if d is None else _ms(d),
            "primary_fetch_ms": None if primary is None or primary.fetch_ns is None else _ms(primary.fetch_ns),
            "key_id_early": None if sender is None else early_at[sender].get(primary.line.idx),
        }
        for node, b in ((alice, tk.alice), (bob, tk.bob)):
            record[node.name] = {
                "interval": b.interval, "role": b.role,
                "no_key_id_invalidation": _no_key_id_outcome(
                    node, position[node.name][b.line.idx], ends[node.name]),
            }
        out.append(record)
    return out


def _offset_segments(ticks: list[Tick], per_tick: list[dict]) -> list[dict]:
    """The offset over the window, in OFFSET_TREND_SEGMENTS equal time segments,
    with each segment's early key_ids (of the ticks where it could be told) and
    its BACKUP intervals that ended in a `no key_id from the peer`
    invalidation."""
    if not ticks:
        return []
    t0 = ticks[0].t
    width = (ticks[-1].t - t0) / OFFSET_TREND_SEGMENTS
    count = OFFSET_TREND_SEGMENTS if width > 0 else 1
    buckets: list[list[int]] = [[] for _ in range(count)]
    for k, tk in enumerate(ticks):
        buckets[min(count - 1, int((tk.t - t0) / width)) if width > 0 else 0].append(k)
    segments = []
    for i, members in enumerate(buckets):
        offsets = [ticks[k].offset_ns for k in members]
        records = [per_tick[k] for k in members]
        told = [r["key_id_early"] for r in records if r["key_id_early"] is not None]
        segments.append({
            "from": format_time(t0 + round(i * width)), "ticks": len(members),
            "median_ms": _ms(statistics.median(offsets)) if offsets else None,
            "abs_max_ms": _ms(max(abs(o) for o in offsets)) if offsets else None,
            "early_key_ids": sum(told), "key_ids_told": len(told),
            "no_key_id_invalidations": sum(1 for r in records for name in ("alice", "bob")
                                           if r[name]["no_key_id_invalidation"] == NO_KEY_ID_THIS),
        })
    return segments


def boundary_report(alice: Node, bob: Node) -> dict:
    nodes = {}
    for node in (alice, bob):
        fetch = sorted(b.fetch_ns for b in node.boundaries if b.fetch_ns is not None)
        nodes[node.name] = {
            "boundaries": len(node.boundaries),
            "primary": sum(1 for b in node.boundaries if b.role == "primary"),
            "backup": sum(1 for b in node.boundaries if b.role == "backup"),
            "primary_unnumbered": node.unnumbered_primary,
            "number_without_request": node.number_without_request,
            "kms_fetch_ms": ({"median": _ms(statistics.median(fetch)), "max": _ms(fetch[-1])}
                             if fetch else None),
            "no_key_id_invalidations": len(node.no_key_id_invalidations),
        }
    spacing = boundary_spacing_ns(alice, bob)
    ticks = pair_ticks(alice, bob, spacing) if spacing else []
    apart = [tk for tk in ticks if tk.alice.interval != tk.bob.interval]
    differences: dict[int, int] = {}
    for tk in apart:
        d = tk.bob.interval - tk.alice.interval
        differences[d] = differences.get(d, 0) + 1
    by_alice = {tk.alice.line.idx: tk.bob for tk in ticks}
    by_bob = {tk.bob.line.idx: tk.alice for tk in ticks}
    # Keyed by the sender: alice's key_ids reach bob, bob's reach alice.
    arrivals = {"alice": _key_id_arrivals(alice, bob, by_alice),
                "bob": _key_id_arrivals(bob, alice, by_bob)}
    per_tick = _per_tick(alice, bob, ticks, arrivals)
    segments = _offset_segments(ticks, per_tick)
    return {
        "nodes": nodes,
        "spacing_s": None if spacing is None else round(spacing / NS_PER_S, _MS_DECIMALS),
        "ticks": len(ticks),
        "unpaired": {"alice": len(alice.boundaries) - len(ticks), "bob": len(bob.boundaries) - len(ticks)},
        "offset_ms": _offset_summary(ticks),
        "segments": segments,
        "no_key_id_invalidations_in_ticks": sum(s["no_key_id_invalidations"] for s in segments),
        "interval_mismatch": {
            "ticks": len(apart),
            "first": format_time(apart[0].t) if apart else None,
            "last": format_time(apart[-1].t) if apart else None,
            "bob_minus_alice": {f"{d:+d}": n for d, n in sorted(differences.items())},
        },
        "same_role": {
            "both_primary": sum(1 for tk in ticks if tk.alice.role == tk.bob.role == "primary"),
            "both_backup": sum(1 for tk in ticks if tk.alice.role == tk.bob.role == "backup"),
        },
        # Keyed by the receiver, as printed.
        "early_key_ids": {"alice": early_key_ids(arrivals["bob"]),
                          "bob": early_key_ids(arrivals["alice"])},
        "per_tick": per_tick,
    }


# --------------------------------------------------------------- statistics --

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, _MAX_CF_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            return h
    raise ArithmeticError(f"incomplete beta did not converge for a={a}, b={b}, x={x}")


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """Inverse of betainc in x, by bisection (monotone, so it cannot miss)."""
    lo, hi = 0.0, 1.0
    for _ in range(_BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < _EPS:
            break
    return (lo + hi) / 2.0


def clopper_pearson(k: int, n: int, confidence: float = CONFIDENCE) -> tuple[float, float] | None:
    """Exact binomial interval for k successes in n trials; None when n == 0."""
    if n <= 0 or k < 0 or k > n:
        return None
    alpha = 1.0 - confidence
    lo = 0.0 if k == 0 else beta_ppf(alpha / 2.0, k, n - k + 1)
    hi = 1.0 if k == n else beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
    return lo, hi


def _binom_pmf(i: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0 if i == 0 else 0.0
    if p >= 1.0:
        return 1.0 if i == n else 0.0
    return math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                    + i * math.log(p) + (n - i) * math.log1p(-p))


def conditional_binomial(k_a: int, r_a: int, k_b: int, r_b: int) -> dict[str, float] | None:
    """Exact test of equal rates k/r in two arms, conditional on k_a + k_b.

    Under equal rates k_a ~ Binomial(k_a + k_b, r_a / (r_a + r_b)). Returns the
    one-sided p-value for "arm B's rate is lower" (P(K_A >= k_a)) and the
    two-sided one (outcomes at most as likely as the observed one).
    """
    n = k_a + k_b
    if r_a <= 0 or r_b <= 0 or n == 0:
        return None
    p = r_a / (r_a + r_b)
    pmf = [_binom_pmf(i, n, p) for i in range(n + 1)]
    observed = pmf[k_a]
    return {
        "n": n,
        "p_null": p,
        "p_one_sided_b_lower": min(1.0, sum(pmf[k_a:])),
        "p_two_sided": min(1.0, sum(x for x in pmf if x <= observed * (1.0 + _TIE_SLACK))),
    }


# ------------------------------------------------------------------- report --

def build_report(alice: Node, bob: Node) -> dict:
    failures = classify(alice, bob)
    cells: dict[str, dict] = {c: {"R": 0, "F": 0, **dict.fromkeys(CLASSES, 0),
                                  "read_gap_candidates": 0} for c in (*CELLS, "all")}
    for g in alice.generations:
        if g.rot_idx is not None and not g.invalidation:
            cells[_cell(g)]["R"] += 1
            cells["all"]["R"] += 1
    for f in failures:
        for c in (f.cell, "all"):
            cells[c]["F"] += 1
            cells[c][f.klass] += 1
            if f.read_gap_candidate:
                cells[c]["read_gap_candidates"] += 1

    for row in cells.values():
        not_invalidation = row["F"] - row["C1"]
        row["intervals"] = {
            "F_not_C1_per_R": clopper_pearson(not_invalidation, row["R"]),
            **{f"{k}_per_R": clopper_pearson(row[k], row["R"]) for k in ("C3", "C4", "C5")},
        }

    all_ids = alice.key_ids | bob.key_ids
    warnings = []
    for node in (alice, bob):
        if len(node.starts) > 1:
            warnings.append(
                f"{node.name}: {len(node.starts)} process starts in the window; the counting rules "
                "exclude windows in which either node restarted, since each node numbers its own "
                "writes. Re-run with --since after the last start.")
        if not node.starts:
            warnings.append(f"{node.name}: no process start in the window, so no startup (C2) window "
                            "can be placed for it")
        if node.untimestamped:
            warnings.append(f"{node.name}: {node.untimestamped} line(s) without a docker timestamp "
                            "took the stamp of the line before them")
        if node.format == "none":
            warnings.append(f"{node.name}: no arnika line recognised in either format")
        if node.format in ("slog", "mixed") and not node.rounds:
            warnings.append(f"{node.name}: slog format but no 'round agreed a fresh PQC key' line; "
                            "PQC_ENABLED off or LOG_LEVEL above info? Startup (C2) then ends at the "
                            "first rotation alone")
    if cells["all"]["U"]:
        warnings.append(f"{cells['all']['U']} failure(s) unclassified: no bob mismatch within "
                        f"{PAIRING_TOLERANCE_NS / NS_PER_S:g} s of them")

    boundaries = boundary_report(alice, bob)
    for node in (alice, bob):
        if node.format != "none" and not node.boundaries:
            warnings.append(f"{node.name}: no interval boundary line in the window, so the boundary "
                            "offset cannot be measured (LOG_LEVEL above info?)")
        if node.format in ("pin-era", "mixed") and node.boundaries:
            warnings.append(f"{node.name}: pin-era format; a BACKUP there logs its boundary only when no "
                            "key_id reached it since its previous boundary, so the paired ticks are a "
                            "biased sample of the offset")
    apart = boundaries["interval_mismatch"]
    if apart["ticks"]:
        warnings.append(f"the interval numbers differ between the ends in {apart['ticks']} paired tick(s), "
                        f"{apart['first']} .. {apart['last']}: the counters are out of step, so the role "
                        "elections are not complementary there")

    times = [ln.t for ln in alice.lines + bob.lines]
    return {
        "format": {"alice": alice.format, "bob": bob.format},
        "window": {"first": format_time(min(times)) if times else None,
                   "last": format_time(max(times)) if times else None},
        "process_starts": {"alice": len(alice.starts), "bob": len(bob.starts)},
        "invalidation_writes": {"alice": sum(g.invalidation for g in alice.generations),
                                "bob": sum(g.invalidation for g in bob.generations)},
        "invalidation_triggers": {
            node.name: {t: sum(1 for g in node.generations if g.invalidation and g.trigger == t)
                        for t in (*INVALIDATION_TRIGGERS, TRIGGER_OTHER)}
            for node in (alice, bob)},
        "key_id_shapes": {"distinct": len(all_ids),
                          "uuid": sum(1 for k in all_ids if _UUID.match(k)),
                          "other": sum(1 for k in all_ids if not _UUID.match(k))},
        "corroboration": {
            "bob_mac_mismatched": len(bob.mismatches),
            "bob_auth_failed": len(bob.auth_failed),
            "bob_rotations": sum(1 for g in bob.generations
                                 if g.rot_idx is not None and not g.invalidation),
            "alice_ppk_applied": alice.ppk_applied,
        },
        "confidence": CONFIDENCE,
        "class_order": list(CLASS_ORDER),
        "class_names": dict(CLASS_NAMES),
        "boundaries": boundaries,
        "cells": cells,
        "failures": [
            {"time": format_time(f.line.t),
             "generation": f.generation.number if f.generation else None,
             "cell": f.cell, "class": f.klass, "matched_by": f.matched_by,
             "read_gap_candidate": f.read_gap_candidate}
            for f in failures
        ],
        "warnings": warnings,
    }


def _fmt_interval(iv) -> str:
    if iv is None:
        return "n/a"
    return f"[{iv[0]:.2e}, {iv[1]:.2e}]"


def _fmt_ms(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f} ms" if signed else f"{value:.1f} ms"


def _render_boundaries(b: dict) -> list[str]:
    out = ["  interval boundaries, paired per wall-clock tick (docker timestamps):"]
    nodes = b["nodes"]
    spacing = "n/a" if b["spacing_s"] is None else f"{b['spacing_s']:g} s"
    out.append("    " + ", ".join(f"{name} {n['boundaries']} ({n['primary']} PRIMARY, {n['backup']} BACKUP)"
                                  for name, n in nodes.items())
               + f"; interval {spacing}; {b['ticks']} tick(s) paired, "
               f"unpaired alice {b['unpaired']['alice']}, bob {b['unpaired']['bob']}")
    left_out = [f"{name}: {n['primary_unnumbered']} PRIMARY interval(s) without a number (KMS request "
                f"failed), {n['number_without_request']} number(s) without a request line"
                for name, n in nodes.items() if n["primary_unnumbered"] or n["number_without_request"]]
    if left_out:
        out.append("    left out: " + "; ".join(left_out))
    o = b["offset_ms"]
    if o is None:
        out.append("    offset bob - alice: n/a, no tick paired")
        return out
    pct = f"abs_p{OFFSET_PERCENTILE}_ms"
    slope = ("n/a" if o["slope_ms_per_hour"] is None
             else f"{o['slope_ms_per_hour']:+.1f} ms/h")
    out.append(f"    offset bob - alice: size median {_fmt_ms(o['abs_median_ms'])}, "
               f"p{OFFSET_PERCENTILE} {_fmt_ms(o[pct])}, max {_fmt_ms(o['abs_max_ms'])}; "
               f"first {_fmt_ms(o['first_ms'], True)}, last {_fmt_ms(o['last_ms'], True)}, "
               f"slope {slope}; change per paired tick median {_fmt_ms(o['step_abs_median_ms'])}, "
               f"max {_fmt_ms(o['step_abs_max_ms'])}; bob later in {o['bob_later']} of {b['ticks']}")
    out.append(f"    offset over the window, {len(b['segments'])} equal segment(s); 'early' counts the "
               "key_ids that reached the BACKUP before its boundary, of those where that could be told:")
    for seg in b["segments"]:
        out.append(f"      from {seg['from']}  {seg['ticks']:>6} tick(s)  median "
                   f"{_fmt_ms(seg['median_ms'], True):>12}  max size {_fmt_ms(seg['abs_max_ms'])}  "
                   f"early {seg['early_key_ids']} of {seg['key_ids_told']}  "
                   f"no-key_id invalidations {seg['no_key_id_invalidations']}")
    totals = ", ".join(f"{name} {n['no_key_id_invalidations']}" for name, n in nodes.items())
    out.append(f"    'no key_id from the peer' invalidations: {totals}; "
               f"{b['no_key_id_invalidations_in_ticks']} of them in the paired ticks above")
    out.append("    PRIMARY KMS fetch, request to 'serving this interval': " + "; ".join(
        f"{name} " + ("n/a" if n["kms_fetch_ms"] is None else
                      f"median {_fmt_ms(n['kms_fetch_ms']['median'])}, max {_fmt_ms(n['kms_fetch_ms']['max'])}")
        for name, n in nodes.items()))
    m = b["interval_mismatch"]
    if m["ticks"]:
        diffs = ", ".join(f"{d} in {n}" for d, n in m["bob_minus_alice"].items())
        out.append(f"    interval-number mismatch: {m['ticks']} of {b['ticks']} paired tick(s), bob - alice "
                   f"{diffs}; first {m['first']}, last {m['last']}")
    else:
        out.append(f"    interval-number mismatch: none in {b['ticks']} paired tick(s)")
    r = b["same_role"]
    out.append(f"    same role on both ends: both PRIMARY {r['both_primary']}, both BACKUP {r['both_backup']}")
    early = b["early_key_ids"]
    out.append("    key_ids received before the receiver's own boundary of the sender's tick: " + ", ".join(
        f"{name} {'n/a (not slog)' if e is None else str(e['early']) + ' of ' + str(e['matched'])}"
        for name, e in early.items()))
    return out


def render(report: dict) -> str:
    out = []
    fmt = report["format"]
    out.append("PPK rotation outcomes on the IPsec lane (alice initiates, bob responds)")
    out.append(f"  arnika log format: alice {fmt['alice']}, bob {fmt['bob']}")
    w = report["window"]
    out.append(f"  window (docker timestamps, UTC): {w['first']} .. {w['last']}")
    ps = report["process_starts"]
    out.append(f"  process starts: alice {ps['alice']}, bob {ps['bob']}")
    iw, it = report["invalidation_writes"], report["invalidation_triggers"]
    out.append("  invalidation writes (random PPK, not counted in R), by what failed closed:")
    for node in ("alice", "bob"):
        out.append(f"    {node}: {iw[node]} = "
                   + ", ".join(f"{n} {t!r}" if t != TRIGGER_OTHER else f"{n} {t}"
                               for t, n in it[node].items()))
    ks = report["key_id_shapes"]
    out.append(f"  key_ids: {ks['distinct']} distinct, {ks['uuid']} UUID-shaped, {ks['other']} other")
    out.append("  classes, tried in this order, first match wins: "
               + ", ".join(f"{k} {report['class_names'][k]}" for k in report["class_order"]))
    out.append("")
    head = f"  {'cell':<14}{'R':>8}{'F':>6}" + "".join(f"{k:>5}" for k in CLASSES)
    out.append(head + f"   {'(F-C1)/R ' + format(report['confidence'], '.0%') + ' CP':<28}{'C3/R CP':<26}")
    for cell in (*CELLS, "all"):
        row = report["cells"][cell]
        iv = row["intervals"]
        out.append(f"  {cell:<14}{row['R']:>8}{row['F']:>6}"
                   + "".join(f"{row[k]:>5}" for k in CLASSES)
                   + f"   {_fmt_interval(iv['F_not_C1_per_R']):<28}{_fmt_interval(iv['C3_per_R']):<26}")
    rg = report["cells"]["all"]["read_gap_candidates"]
    out.append(f"  read-gap candidates among C4: {rg}")
    c = report["corroboration"]
    out.append(f"  bob: {c['bob_mac_mismatched']} MAC mismatched, {c['bob_auth_failed']} N(AUTH_FAILED), "
               f"{c['bob_rotations']} key-driven rotations; alice: {c['alice_ppk_applied']} 'using PPK for PPK_ID'")
    out.append("")
    out.extend(_render_boundaries(report["boundaries"]))
    if report["failures"]:
        out.append("")
        out.append("  failures:")
        for f in report["failures"]:
            gen = "-" if f["generation"] is None else f["generation"]
            extra = f" matched by {f['matched_by']}" if f["matched_by"] else ""
            if f["read_gap_candidate"]:
                extra += ", read-gap candidate"
            out.append(f"    {f['time']}  generation {gen:<6}  {f['cell']:<14}  {f['class']}{extra}")
    for warning in report["warnings"]:
        out.append(f"  Note: {warning}")
    return "\n".join(line.rstrip() for line in out)


def render_compare(a: dict, b: dict, klass: str) -> tuple[str, dict]:
    result = {"class": klass, "cells": {}}
    lines = [f"{klass} per key-driven rotation, arm A vs arm B (exact conditional binomial test)"]
    lines.append(f"  {'cell':<14}{'A: k/R':>16}{'B: k/R':>16}{'p one-sided (B lower)':>24}{'p two-sided':>14}")
    for cell in (*CELLS, "all"):
        ra, rb = a["cells"][cell], b["cells"][cell]
        test = conditional_binomial(ra[klass], ra["R"], rb[klass], rb["R"])
        result["cells"][cell] = {"A": [ra[klass], ra["R"]], "B": [rb[klass], rb["R"]], "test": test}
        one = "n/a" if test is None else f"{test['p_one_sided_b_lower']:.3g}"
        two = "n/a" if test is None else f"{test['p_two_sided']:.3g}"
        lines.append(f"  {cell:<14}{ra[klass]:>8}/{ra['R']:<7}{rb[klass]:>8}/{rb['R']:<7}{one:>24}{two:>14}")
    return "\n".join(line.rstrip() for line in lines), result


# ---------------------------------------------------------------------- CLI --

def _docker_logs(container: str) -> str:
    try:
        proc = subprocess.run(["docker", "logs", "-t", container],
                              capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError:
        raise InputError("docker is not installed or not on PATH") from None
    if proc.returncode != 0:
        raise InputError(f"docker logs -t {container} failed: {proc.stderr.strip()[:200]}")
    # arnika and charon write stderr, the entrypoint stdout; read_lines sorts
    # the two by their docker timestamps.
    return proc.stdout + proc.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="count R, F and the failure classes")
    src = rep.add_mutually_exclusive_group(required=True)
    src.add_argument("--docker", action="store_true", help="read `docker logs -t` of both containers")
    src.add_argument("--alice", type=Path, help="alice's `docker logs -t` text")
    rep.add_argument("--bob", type=Path, help="bob's `docker logs -t` text (with --alice)")
    rep.add_argument("--alice-container", default=ALICE_CONTAINER)
    rep.add_argument("--bob-container", default=BOB_CONTAINER)
    rep.add_argument("--since", help="RFC 3339 instant; earlier lines are ignored")
    rep.add_argument("--until", help="RFC 3339 instant; this and later lines are ignored")
    rep.add_argument("--json", action="store_true", help="print the report as JSON")

    cmp_ = sub.add_parser("compare", help="compare two `report --json` outputs")
    cmp_.add_argument("arm_a", type=Path)
    cmp_.add_argument("arm_b", type=Path)
    cmp_.add_argument("--class", dest="klass", default="C3", choices=CLASSES)
    cmp_.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.command == "compare":
            a = json.loads(args.arm_a.read_text(encoding="utf-8"))
            b = json.loads(args.arm_b.read_text(encoding="utf-8"))
            text, result = render_compare(a, b, args.klass)
            print(json.dumps(result, indent=2) if args.json else text)
            return 0

        since = parse_time(args.since) if args.since else None
        until = parse_time(args.until) if args.until else None
        if args.docker:
            alice_text = _docker_logs(args.alice_container)
            bob_text = _docker_logs(args.bob_container)
        else:
            if args.bob is None:
                raise InputError("--alice needs --bob")
            alice_text = args.alice.read_text(encoding="utf-8", errors="replace")
            bob_text = args.bob.read_text(encoding="utf-8", errors="replace")
        alice = parse_node("alice", alice_text, since, until)
        bob = parse_node("bob", bob_text, since, until)
        report = build_report(alice, bob)
        print(json.dumps(report, indent=2) if args.json else render(report))
        return 0
    except (InputError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ppk_race_report: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
