"""`GET /api/wg/{node}` must never emit WireGuard key material.

It did. Until 2026-08-27 the handler ran `wg show wg0 dump` and returned the
output verbatim, unauthenticated, with no DEMO_MODE gate. From wg(8) the dump
format is positional and tab-separated:

    line 1:  private-key  public-key  listen-port  fwmark
    peers:   public-key   preshared-key  endpoint  allowed-ips  handshake  rx  tx  keepalive

Field 1 of line 1 is the interface PRIVATE key. Field 2 of each peer line is the
PRESHARED key -- and on this stack that is the arnika HKDF(QKD || PQC) output,
which is the entire product of the key path the project exists to demonstrate.
A GET of the public demo's /api/wg/alice returned both.

Nothing in the frontend has ever called the route, so there was no consumer
whose behaviour could have flagged it, and no page whose rendering would have
looked wrong. A claim nothing in the build could contradict, again -- except
this one was not a claim, it was the keys.

Three separate things are pinned below, because fixing only one leaves the
others free to drift back:

  1. the command string contains no `dump`;
  2. the redactor is a no-op on correct (non-dump) input, so it cannot be
     "simplified away" on the grounds that it never does anything;
  3. the redactor withholds dump-shaped input entirely rather than trying to
     edit specific columns.

The fixtures are verbatim output captured from the running demo containers on
2026-08-27, with the key material replaced by same-shape placeholders -- real
base64 lengths, so a length-based check cannot pass on a shorter stand-in.
"""

from __future__ import annotations

import importlib

from conftest import load_service_app

load_service_app("webui-backend", "webui_backend_app")
_main = importlib.import_module("webui_backend_app.main")

# ---- fixtures ------------------------------------------------------------
# Placeholder keys, real shape: 43 base64 chars + '='.
_PRIV = "PRIVpvtKEYplaceholder0000000000000000000000="
_PSK = "PSKpskKEYplaceholder00000000000000000000000="
_PUB_A = "PUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUBaPUB="
_PUB_B = "PUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUBbPUB="

# What `wg show wg0` prints. Captured from `docker exec alice wg show wg0`.
WG_SHOW = f"""\
interface: wg0
  public key: {_PUB_A}
  private key: (hidden)
  listening port: 51820

peer: {_PUB_B}
  preshared key: (hidden)
  endpoint: 10.30.0.11:51821
  allowed ips: 10.0.0.2/32
  latest handshake: 1 minute, 32 seconds ago
  transfer: 726.21 KiB received, 980.89 KiB sent
  persistent keepalive: every 25 seconds
"""

# What `wg show wg0 dump` prints -- the form that leaked.
WG_DUMP = (
    f"{_PRIV}\t{_PUB_A}\t51820\toff\n"
    f"{_PUB_B}\t{_PSK}\t10.30.0.11:51821\t10.0.0.2/32\t1787829729\t743676\t1004460\t25\n"
)

# A hypothetical the redactor must also survive: the readable form, but with a
# wireguard-tools that printed the values instead of "(hidden)". Nothing does
# this today; the point is that the redactor does not depend on upstream.
WG_SHOW_UNREDACTED = WG_SHOW.replace(
    "private key: (hidden)", f"private key: {_PRIV}"
).replace("preshared key: (hidden)", f"preshared key: {_PSK}")


def test_the_endpoint_does_not_ask_for_the_dump_format():
    """The one-word difference that caused the leak."""
    assert "dump" not in _main.WG_SHOW_CMD, (
        f"WG_SHOW_CMD is {_main.WG_SHOW_CMD!r}. `wg show <if> dump` emits the "
        "interface private key as field 1 and the preshared key as field 2 of "
        "each peer line. This endpoint is public and unauthenticated."
    )
    assert _main.WG_SHOW_CMD.split() == ["wg", "show", "wg0"]


def test_redaction_is_a_no_op_on_the_readable_form():
    """So it cannot be deleted as dead code -- it is a second layer, not a first."""
    assert _main._redact_wg(WG_SHOW) == WG_SHOW


def test_public_keys_survive_redaction():
    """Over-redaction would make the endpoint useless and invite reverting it."""
    out = _main._redact_wg(WG_SHOW)
    assert _PUB_A in out and _PUB_B in out
    assert "latest handshake: 1 minute, 32 seconds ago" in out


def test_secrets_are_stripped_even_if_upstream_stops_hiding_them():
    out = _main._redact_wg(WG_SHOW_UNREDACTED)
    assert _PRIV not in out, "interface private key survived redaction"
    assert _PSK not in out, "preshared key survived redaction"
    assert "private key: (hidden)" in out
    assert "preshared key: (hidden)" in out


def test_dump_shaped_output_is_withheld_whole():
    """Positional formats are refused, not column-edited.

    A redactor that blanks "field 2" is one off-by-one from emitting the key it
    meant to remove. Withholding is the only response that cannot be subtly
    wrong.
    """
    out = _main._redact_wg(WG_DUMP)
    assert _PRIV not in out
    assert _PSK not in out
    assert "[withheld]" in out
    # It should say why, so an operator who hits it knows it is deliberate.
    assert "private key" in out


def test_the_route_returns_redacted_output():
    """End to end through the handler, with a fake docker client.

    The unit tests above could all pass while the handler returned `text`
    instead of `_redact_wg(text)` -- which is exactly the bug that shipped.
    """

    class _FakeExec:
        def __init__(self, payload: bytes):
            self.payload = payload

        def exec_run(self, cmd):
            # Answer with the DUMP even though the handler asked for `show`, so
            # this fails unless the response actually goes through the redactor.
            assert "dump" not in cmd
            return 0, self.payload

    class _FakeContainers:
        def get(self, name):
            return _FakeExec(WG_DUMP.encode())

    class _FakeDocker:
        containers = _FakeContainers()

    from fastapi.testclient import TestClient

    prev = getattr(_main.app.state, "docker", None)
    _main.app.state.docker = _FakeDocker()
    try:
        with TestClient(_main.app) as client:
            # TestClient's lifespan re-runs startup, which may reset the client.
            _main.app.state.docker = _FakeDocker()
            body = client.get("/api/wg/alice").json()
    finally:
        _main.app.state.docker = prev

    assert _PRIV not in body["output"], "the route emitted the interface private key"
    assert _PSK not in body["output"], "the route emitted the preshared key"
