"""stack-status: the one container that mounts the Docker socket.

webui-backend answers the internet. It used to mount /var/run/docker.sock
itself, read-only, to list containers, tail their logs and run `wg show` and
`swanctl` in the lane nodes. A read-only bind mount stops a container from
replacing or unlinking the socket FILE; it does not make the Docker API behind
it read-only. Whoever can connect to the socket can create a privileged
container with the host's root filesystem mounted, so code execution in the
backend, or in any of its dependencies, was root on the host. The backend now
holds no socket and installs no Docker SDK.

This service holds the socket instead. It listens on status-net, an internal
network that only webui-backend also joins (docker-compose.yml), publishes no
port, and serves a fixed API, GET only:

  GET /health                          200 when the Docker daemon answers a ping
  GET /v1/stack                        the status of STACK_SERVICES
  GET /v1/logs/{name}?tail=N           a tail of one of LOG_CONTAINERS
  GET /v1/log-window/{name}?seconds=N  the last N seconds of one of LOG_WINDOW_CONTAINERS
  GET /v1/wg/{node}                    `wg show wg0` and `wg show wg1` in one of WG_NODES
  GET /v1/ipsec/{node}                 `swanctl --list-sas` and `--list-conns` in one of IPSEC_NODES

Everything else is refused before Docker is asked anything: 405 for any method
but GET, 404 for any other path or for a name outside the route's table, 422
for a query parameter that is missing, repeated, unknown, not a decimal
integer or out of range. No route starts, stops, creates or removes a
container, and no route runs a command that is not one of the contract's
fixed strings. The tables, commands, bounds and paths are stack_contract.py:
webui-backend's file, which the Dockerfile copies into this package, so the two
services read one table.

A Docker failure (no such container, a daemon that does not answer, an exec
that fails) is reported in the reply body as `error`, with HTTP 200. Refusals
are the only HTTP errors, so the backend can tell "that container is not there"
from "stack-status refused the request". Log text and `wg show` output are
redacted here, and webui-backend redacts them again before they leave it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import docker

from . import stack_contract as contract

log = logging.getLogger("stack-status")

# The port this service listens on inside its container. No compose file
# publishes it. docker-compose.yml names it in webui-backend's STACK_STATUS_URL
# and in this service's healthcheck.
LISTEN_PORT = 8081

# Every interface of the container, which is status-net alone: compose attaches
# this service to that one internal network.
LISTEN_HOST = "0.0.0.0"

# The timeout of each Docker API call, in seconds. Below webui-backend's
# STACK_STATUS_TIMEOUT_S (10 s), so a daemon that hangs is reported here, in
# the body, before the backend stops waiting for the reply.
DOCKER_TIMEOUT_S = 8

# A client that connects and then sends nothing is dropped after this many
# seconds.
REQUEST_TIMEOUT_S = 10

# The most query fields one request may carry. No route takes more than one.
MAX_QUERY_FIELDS = 4

# The largest request body read and discarded before a reply. No route takes
# a body, but a refused POST with one must still get its 405: closing a
# socket with unread bytes in it makes the kernel send a reset, which can
# reach the client before the reply does. A longer body is left unread.
MAX_DISCARDED_BODY_BYTES = 65536

# What a query value must look like before it is compared with its route's
# bounds: a decimal integer of at most nine digits. No sign, no spaces, no
# exponent, so `+5`, ` 5` and `1e3`, which Python's int() or float() would
# take, are refused rather than interpreted.
_DECIMAL = re.compile(r"[0-9]{1,9}")


class Refused(Exception):
    """A request outside the fixed API: the HTTP status to answer, and why."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _pattern(template: str) -> re.Pattern[str]:
    """`/v1/logs/{name}` -> a pattern capturing one path segment as `name`."""
    parts = re.split(r"\{(\w+)\}", template)
    return re.compile("^" + "".join(
        re.escape(part) if i % 2 == 0 else f"(?P<{part}>[^/]+)"
        for i, part in enumerate(parts)) + "$")


def _known(name: str, table: tuple[str, ...]) -> None:
    """404 for a name outside `table`, before Docker is asked anything.

    404 rather than 403: from outside, a container this API will not serve and
    one that does not exist are the same answer.
    """
    if name not in table:
        raise Refused(404, f"unknown container {name!r}; allowed: {list(table)}")


def _query(raw: str, accepted: tuple[str, ...]) -> dict[str, list[str]]:
    """The parsed query string; 422 for a parameter the route does not take."""
    try:
        query = parse_qs(raw, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)
    except ValueError as e:
        raise Refused(422, f"query not accepted: {e}")
    unknown = sorted(set(query) - set(accepted))
    if unknown:
        raise Refused(422, f"unknown parameter(s) {unknown}; accepted: {list(accepted)}")
    return query


def _int_param(query: dict[str, list[str]], key: str, low: int, high: int) -> int:
    """One required integer parameter in [low, high], or 422 saying what is wrong.

    Refused, never clamped: a clamp would answer a different question from the
    one asked, with nothing in the reply to say so.
    """
    values = query.get(key)
    if not values:
        raise Refused(422, f"{key} is required: an integer from {low} to {high}")
    if len(values) > 1:
        raise Refused(422, f"{key} is given {len(values)} times; give it once")
    if not _DECIMAL.fullmatch(values[0]):
        raise Refused(422, f"{key} must be a decimal integer from {low} to {high}")
    value = int(values[0])
    if not low <= value <= high:
        raise Refused(422, f"{key}={value} is outside {low}..{high}")
    return value


def _stack_rows(cli: Any) -> list[dict[str, Any]]:
    """One row per STACK_SERVICES name: what Docker says about that container."""
    out: list[dict[str, Any]] = []
    for n in contract.STACK_SERVICES:
        try:
            c = cli.containers.get(n)
        except docker.errors.NotFound:
            # The container genuinely is not there: Docker answered 404 for
            # the name. This is the only path that may say "absent".
            out.append({"name": n, "status": "absent"})
            continue
        except Exception as e:
            # Anything else -- an APIError, a socket timeout, a daemon that is
            # restarting -- means we could not look, which is not the same
            # fact as "not there". This branch used to share the absent one
            # (`except Exception:`), so a transient Docker error painted
            # bb84-kme-a as missing, and qkdnetsim-kme as absent "not that
            # anything failed" when something had.
            log.warning("docker lookup of %s failed: %s", n, e)
            out.append({"name": n, "status": "unknown", "error": contract.bounded(e)})
            continue

        # Reading the image is a SEPARATE failure from the container being
        # absent, and it used to be inside the same try. `c.image` raises
        # ImageNotFound whenever the image the container runs has lost its
        # tag -- which happens routinely: rebuilding `pqcqkd/node-alice:local`
        # leaves every other container still running the previous, now
        # dangling, image ID.
        #
        # Measured on the deployed host: after rebuilding alice, `bob` was
        # `Up 4 days` and rotating keys normally, `containers.get("bob")`
        # returned status=running, and `bob.image` raised
        # `ImageNotFound: 404 ... /images/1a2e95e58251`. The Overview page
        # showed bob as ABSENT for a container that was working.
        #
        # A cosmetic field must not be able to erase an observed status.
        image = ""
        try:
            tags = c.image.tags
            image = tags[0] if tags else ""
        except Exception:
            # Untagged is a real, reportable state -- not an empty string,
            # which would read as "no image information available".
            image = "<untagged>"

        out.append({
            "name": n,
            "status": c.status,
            "image": image,
            "started_at": c.attrs.get("State", {}).get("StartedAt"),
        })
    return out


class StackStatus:
    """The fixed API, as a function of one request's method and target.

    Kept apart from the HTTP server, so that a test can drive it with a fake
    Docker client, and so that the only state it holds is that client.
    """

    def __init__(self, client_factory: Callable[[], Any] | None = None):
        self._factory = client_factory or (lambda: docker.from_env(timeout=DOCKER_TIMEOUT_S))
        self._client: Any = None
        self._lock = threading.Lock()
        self._routes: tuple[tuple[re.Pattern[str], Callable[..., tuple[int, dict[str, Any]]]], ...] = (
            (_pattern(contract.PATH_HEALTH), self._health),
            (_pattern(contract.PATH_STACK), self._stack),
            (_pattern(contract.PATH_LOGS), self._logs),
            (_pattern(contract.PATH_LOG_WINDOW), self._log_window),
            (_pattern(contract.PATH_WG), self._wg),
            (_pattern(contract.PATH_IPSEC), self._ipsec),
        )

    PATHS: tuple[str, ...] = (
        contract.PATH_HEALTH, contract.PATH_STACK, contract.PATH_LOGS,
        contract.PATH_LOG_WINDOW, contract.PATH_WG, contract.PATH_IPSEC,
    )

    def handle(self, method: str, target: str) -> tuple[int, dict[str, Any], dict[str, str]]:
        """(status, JSON body, extra headers) for one request. Never raises.

        The method is checked first, for every path: nothing but GET reaches a
        route, a parameter parser or Docker.
        """
        try:
            if method != "GET":
                raise Refused(405, f"{method} is refused: this API serves GET only")
            url = urlsplit(target)
            for pattern, route in self._routes:
                m = pattern.match(url.path)
                if m:
                    status, body = route(url.query, **m.groupdict())
                    return status, body, {}
            raise Refused(404, f"no route {url.path!r}; this API serves {list(self.PATHS)}")
        except Refused as e:
            # Logged, because a refusal is something other than webui-backend
            # asking: the backend checks the same tables before it calls.
            log.warning("refused %s %s: %d %s", method,
                        target[:contract.ERROR_TEXT_MAX_CHARS], e.status, e.detail)
            return e.status, {"detail": e.detail}, ({"Allow": "GET"} if e.status == 405 else {})
        except Exception as e:
            log.exception("%s %s failed", method, target[:contract.ERROR_TEXT_MAX_CHARS])
            return 500, {"detail": contract.bounded(e)}, {}

    # ----------------------- Docker -----------------------
    def _docker(self) -> Any:
        """The Docker client, created on first use and kept.

        Created lazily, so that a daemon which is not up yet when this service
        starts costs failed requests rather than a crash loop. A creation that
        fails is tried again by the next request and, until it succeeds, is
        reported in each reply's `error`.
        """
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            return self._client

    def _read_log(self, name: str, **window: int) -> dict[str, Any]:
        """A container's stdout and stderr over `window`, redacted.

        `window` is docker-py's `tail` (lines) or `since` (a Unix time). Both
        streams, explicitly: the pinned arnika (f4cf9ba) writes every record to
        stderr through its slog handler (logging.go:42 and :63 there), so a
        stdout-only read would show no arnika line at all.
        """
        try:
            c = self._docker().containers.get(name)
            raw = c.logs(stdout=True, stderr=True, **window)
        except Exception as e:
            log.warning("could not read %s logs: %s", name, e)
            return {"name": name, "log": None, "redacted": None, "error": contract.bounded(e)}
        text, withheld = contract.redact_log(raw.decode("utf-8", errors="replace"))
        return {"name": name, "log": text, "redacted": withheld, "error": None}

    def _run_fixed(self, node: str, commands: dict[str, str],
                   redact: Callable[[str], str] | None) -> dict[str, Any]:
        """Run each of `commands` in `node`, recording each outcome.

        A failed lookup is reported once, for the node; a failed exec only for
        its own command, so one interface's failure does not hide the other's
        reading. A non-zero exit status is an answer, not a failure: its text
        is returned with its `rc`.
        """
        try:
            c = self._docker().containers.get(node)
        except Exception as e:
            log.warning("docker lookup of %s failed: %s", node, e)
            return {"node": node, "error": contract.bounded(e), "results": None}
        results: dict[str, dict[str, Any]] = {}
        for label, cmd in commands.items():
            try:
                rc, out = c.exec_run(cmd)
            except Exception as e:
                log.warning("%r in %s failed: %s", cmd, node, e)
                results[label] = {"rc": None, "output": None, "error": contract.bounded(e)}
                continue
            text = (out or b"").decode("utf-8", errors="replace")
            results[label] = {"rc": rc, "output": redact(text) if redact else text, "error": None}
        return {"node": node, "error": None, "results": results}

    # ----------------------- Routes -----------------------
    def _health(self, raw_query: str) -> tuple[int, dict[str, Any]]:
        _query(raw_query, ())
        try:
            self._docker().ping()
        except Exception as e:
            return 503, {"status": "error",
                         "detail": f"the Docker daemon did not answer: {contract.bounded(e)}"}
        return 200, {"status": "ok"}

    def _stack(self, raw_query: str) -> tuple[int, dict[str, Any]]:
        _query(raw_query, ())
        try:
            cli = self._docker()
        except Exception as e:
            # `unknown`, not `absent`: we could not look at any of them.
            err = contract.bounded(e)
            log.warning("docker client unavailable: %s", err)
            return 200, {"containers": [{"name": n, "status": "unknown", "error": err}
                                        for n in contract.STACK_SERVICES]}
        return 200, {"containers": _stack_rows(cli)}

    def _logs(self, raw_query: str, name: str) -> tuple[int, dict[str, Any]]:
        _known(name, contract.LOG_CONTAINERS)
        tail = _int_param(_query(raw_query, ("tail",)), "tail", 1, contract.LOGS_MAX_TAIL)
        return 200, self._read_log(name, tail=tail)

    def _log_window(self, raw_query: str, name: str) -> tuple[int, dict[str, Any]]:
        _known(name, contract.LOG_WINDOW_CONTAINERS)
        seconds = _int_param(_query(raw_query, ("seconds",)), "seconds",
                             1, contract.LOG_WINDOW_MAX_S)
        return 200, {**self._read_log(name, since=int(time.time()) - seconds),
                     "seconds": seconds}

    def _wg(self, raw_query: str, node: str) -> tuple[int, dict[str, Any]]:
        _known(node, contract.WG_NODES)
        _query(raw_query, ())
        return 200, self._run_fixed(node, contract.WG_SHOW_CMDS, contract.redact_wg)

    def _ipsec(self, raw_query: str, node: str) -> tuple[int, dict[str, Any]]:
        _known(node, contract.IPSEC_NODES)
        _query(raw_query, ())
        return 200, self._run_fixed(node, contract.SWANCTL_CMDS, None)


# ----------------------- HTTP -----------------------
class _Handler(BaseHTTPRequestHandler):
    """Hands every request, whatever its method, to StackStatus.handle."""

    server_version = "stack-status"
    sys_version = ""
    timeout = REQUEST_TIMEOUT_S

    def _serve(self) -> None:
        status, body, headers = self.server.api.handle(self.command, self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= MAX_DISCARDED_BODY_BYTES:
            self.rfile.read(length)
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Every request, at DEBUG: webui-backend polls several routes every few
        # seconds. Refusals are logged at WARNING by StackStatus.handle.
        log.debug("%s %s", self.address_string(), fmt % args)


# Every method BaseHTTPRequestHandler dispatches reaches StackStatus.handle,
# which answers 405 to all but GET. Without these the library would answer
# 501 itself: also a refusal, but not one this service states.
for _method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
    setattr(_Handler, f"do_{_method}", _Handler._serve)


class Server(ThreadingHTTPServer):
    """The HTTP server for one StackStatus. A thread per request."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: StackStatus):
        super().__init__(address, _Handler)
        self.api = api


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )
    server = Server((LISTEN_HOST, LISTEN_PORT), StackStatus())

    # PID 1 in its container: without a handler of its own, SIGTERM from
    # `docker stop` would be ignored, and the stop would wait for SIGKILL.
    def _stop(signum: int, frame: Any) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    log.info("serving %s on port %d, GET only", ", ".join(StackStatus.PATHS), LISTEN_PORT)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
