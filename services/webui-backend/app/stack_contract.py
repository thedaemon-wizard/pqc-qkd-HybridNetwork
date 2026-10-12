"""The fixed contract between webui-backend and stack-status.

stack-status is the only container that mounts the Docker socket. It serves
webui-backend a fixed, GET-only API, and this module is that API's one
definition: which containers each route may read, which commands it may run in
them, the bounds of its parameters, its paths, and the redaction applied to
what it relays. Both services import THIS file.

webui-backend's image builds from its own directory, so the file lives here,
in that service's package. services/stack-status/Dockerfile builds from the
repository root and copies it into its own `app` package under the same name,
so a table edited for one service is the table of the other: there is no
second copy in the tree to fall out of step
(tests/test_stack_status_serves_a_fixed_api.py checks the Dockerfile's copy
line and that no second copy exists).

Standard library only: two images with different dependencies import it.
"""
from __future__ import annotations

import re

# ----------------------- Containers -----------------------
# The containers a route may reach through the Docker socket, and the only
# ones. ONE table for every route that takes a container name from the URL, so
# they cannot drift apart.
#
# `/api/logs/{name}` used to call `cli.containers.get(name)` for ANY name. On
# the public demo that served the log of every container on the host --
# measured 2026-09-25: `/api/logs/caddy` answered 200 with the reverse proxy's
# access log, visitor IPs and User-Agents included. `/api/wg/{node}` ran
# `docker exec wg show wg0` in any container named in the path, including
# webui-frontend.

# The containers /api/stack reports on, in display order. stack-status itself
# is listed: it is a container of the default stack like the others, and a
# missing row would leave the one service every other row depends on unseen.
STACK_SERVICES: tuple[str, ...] = (
    "alice", "bob", "bb84-kme-a", "bb84-kme-b", "webui-backend",
    "stack-status", "webui-frontend", "pqc-validator", "alice-ipsec",
    "bob-ipsec", "qkdnetsim-kme",
)

# The two containers that own the WireGuard lane's interfaces (wg0 and wg1).
WG_NODES: tuple[str, ...] = ("alice", "bob")

# The two strongSwan nodes of the IPsec lane.
IPSEC_NODES: tuple[str, ...] = ("alice-ipsec", "bob-ipsec")

# What /console tails (Console.tsx NAMES, same order).
LOG_CONTAINERS: tuple[str, ...] = WG_NODES + ("bb84-kme-a", "bb84-kme-b") + IPSEC_NODES

# Whose log may be read over a time window rather than as a tail: the IPsec
# nodes, whose `PPK rotated` lines /api/vpn/ppk-rotations counts. Nothing else
# reads a window, so nothing else may.
LOG_WINDOW_CONTAINERS: tuple[str, ...] = IPSEC_NODES

# ----------------------- Commands -----------------------
# The only commands stack-status runs, each in the nodes of one table above.
# docker-py splits a command string with shlex and runs it without a shell.
#
# `wg show <if> dump` PRINTS SECRETS. From wg(8): the first line is
# "private-key, public-key, listen-port, fwmark" tab-separated, and each peer
# line is "public-key, preshared-key, endpoint, allowed-ips, latest-handshake,
# rx, tx, keepalive". Fields 1 and 2 respectively are the interface private key
# and the preshared key, both in plaintext base64.
#
# `GET /api/wg/{node}` served that verbatim, unauthenticated, with no
# DEMO_MODE gate. A 2026-08-27 GET of the public demo's /api/wg/alice returned
# alice's wg0 private key and the live preshared key -- and on this stack the
# wg0 preshared key is the arnika HKDF(QKD || PQC) output, i.e. the entire
# product of the key path the project exists to demonstrate.
#
# The non-dump form is what wireguard-tools redacts for you: it prints
# "private key: (hidden)" and "preshared key: (hidden)". Use it. Then redact
# again on the way out (redact_wg), so that editing one word of the command
# back is not by itself sufficient to leak; see
# tests/test_wg_endpoint_redacts_secrets.py.
#
# Two interfaces per node since release 0.2.0, the layering of arXiv:2604.05599:
#   wg0  the hop tunnel. arnika writes its preshared key: HKDF-SHA3-256 over
#        the QKD key and a PQC-HPKE key that arnika agrees with its peer.
#   wg1  the end-to-end data tunnel, inside wg0. Rosenpass writes its
#        preshared key, which is as secret as wg0's.
WG_SHOW_CMD = "wg show wg0"
WG_DATA_SHOW_CMD = "wg show wg1"
# Interface -> the command that shows it, in the order they are run.
WG_SHOW_CMDS: dict[str, str] = {"wg0": WG_SHOW_CMD, "wg1": WG_DATA_SHOW_CMD}

# The two strongSwan views /api/vpn/protocols parses, keyed as the reply
# carries them. Neither prints key material: `--list-conns` names the PPK by
# its id (`ppk: ppk-qkd@pqcqkd.local, required`), never by its value.
SWANCTL_CMDS: dict[str, str] = {
    "list_sas": "swanctl --list-sas",
    "list_conns": "swanctl --list-conns",
}

# ----------------------- Bounds -----------------------
# The most lines one tail may ask for. A missing cap let one request make the
# backend serialise alice-ipsec's 3.4 million log lines, and reach back past
# the 129,319 lines alice had logged to arnika's start-up banner (2026-09-25).
LOGS_MAX_TAIL = 2000

# The longest log window, in seconds: the hour /api/vpn/ppk-rotations caps its
# `window_s` at. An unbounded window would read two containers' whole log
# streams on every request.
LOG_WINDOW_MAX_S = 3600

# How much of an exception's text, a failed command's output or an upstream
# error body goes into a response field or a log line: enough to name the
# failure, not enough to relay a whole log or an upstream page to the caller.
ERROR_TEXT_MAX_CHARS = 200

# ----------------------- Paths -----------------------
# stack-status serves these and nothing else, GET only. `{name}` and `{node}`
# are one path segment each, and must be a member of the table the route reads.
PATH_HEALTH = "/health"
PATH_STACK = "/v1/stack"
PATH_LOGS = "/v1/logs/{name}"              # ?tail=1..LOGS_MAX_TAIL, LOG_CONTAINERS
PATH_LOG_WINDOW = "/v1/log-window/{name}"  # ?seconds=1..LOG_WINDOW_MAX_S, LOG_WINDOW_CONTAINERS
PATH_WG = "/v1/wg/{node}"                  # WG_NODES, runs WG_SHOW_CMDS
PATH_IPSEC = "/v1/ipsec/{node}"            # IPSEC_NODES, runs SWANCTL_CMDS


# ----------------------- Log redaction -----------------------
# `GET /api/logs/{name}` served ARNIKA_PSK to anyone who asked. The arnika pin
# before release 0.2.0 (3a8cc13) printed its whole configuration at startup,
# including `Arnika PSK: <value>` verbatim (its config/config.go:78), and the
# route had no tail cap, so a large enough `?tail=` reached back past the
# 129,319 lines alice had logged to the banner. Measured on the public demo on
# 2026-09-25 by value LENGTH only (44 characters, a base64 32-byte key); the
# value itself was never printed.
#
# The current pin (f4cf9ba, the head of the still-open arnika PR #51 as of
# 2026-09-24) prints the same label with redactSecret()'s `(set, N bytes)` instead of the value
# (config/config.go:119 and :168-173 there). The banner rule below still
# matches that line and replaces an already-redacted value, which costs only
# the byte count. It stays because the label is all this rule can see: a node
# rolled back to 3a8cc13 writes the same label with the key after it, and the
# pin is not yet a merge commit.
#
# Two rules, because they guard different things:
#   1. the arnika banner line is redacted whatever its value looks like -- a
#      short test PSK is still the PSK;
#   2. elsewhere, a key-ish label followed by something shaped like key material
#      (24+ base64/hex characters) is redacted. The length floor is what keeps
#      "failed to configure random PSK: <error text>" readable on /console.
# See tests/test_logs_endpoint_redacts_secrets.py.
_ARNIKA_PSK_LINE = re.compile(r"(?im)^(.*?\bArnika PSK:[ \t]*)(\S.*)$")
_KEYISH_VALUE = re.compile(
    r"(?i)(\b(?:preshared key|private key|psk|secret)[ \t]*[:=][ \t]*)"
    r"([A-Za-z0-9+/_-]{24,}={0,2})"
)
REDACTED = "(redacted)"


def redact_log(text: str) -> tuple[str, int]:
    """Remove key material from container or service logs.

    Returns the redacted text and how many values were withheld, so a caller
    can report that something was withheld rather than silently shortening it.

    A value that already reads `(redacted)` is not counted again. stack-status
    redacts what it serves and webui-backend redacts it once more on the way
    out; without this the banner line, which the first rule matches whatever
    its value, would be counted by both and the public count would double. On
    a log neither has touched the count is what it always was.
    """
    withheld = 0

    def _withhold(m: re.Match[str]) -> str:
        nonlocal withheld
        if m.group(2) != REDACTED:
            withheld += 1
        return m.group(1) + REDACTED

    text = _ARNIKA_PSK_LINE.sub(_withhold, text)
    text = _KEYISH_VALUE.sub(_withhold, text)
    return text, withheld


# ----------------------- WireGuard redaction -----------------------
_WG_SECRET_LINE = re.compile(r"^(\s*(?:private key|preshared key)\s*:).*$", re.M | re.I)


def redact_wg(text: str) -> str:
    """Remove key material from `wg show` output, failing closed.

    Two layers, because what is being guarded is a one-word edit:

      1. any `private key:` / `preshared key:` value becomes `(hidden)`, which
         is what the non-dump form prints anyway -- so this is a no-op on
         correct input and a rescue on incorrect input;
      2. if the text looks like `dump` output at all, the whole body is
         withheld rather than field-edited. The dump format is positional, and
         a redactor that miscounts columns leaks instead of over-redacting;
         refusing is the only safe response to a shape we did not ask for.

    Idempotent, so stack-status and webui-backend can both apply it.
    """
    if "\t" in text and "interface:" not in text:
        return (
            "[withheld] this looks like `wg show ... dump`, whose first field is "
            "the interface private key and whose second per-peer field is the "
            "preshared key. This endpoint serves only the redacted `wg show` "
            f"form; see WG_SHOW_CMD ({WG_SHOW_CMD!r})."
        )
    return _WG_SECRET_LINE.sub(r"\1 (hidden)", text)


def bounded(error: object) -> str:
    """An exception or error text cut at ERROR_TEXT_MAX_CHARS."""
    return str(error)[:ERROR_TEXT_MAX_CHARS]
