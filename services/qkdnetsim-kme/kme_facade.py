"""A second, independently written ETSI GS QKD 014 server. Not NS-3.

This Flask app is the runtime of the `qkdnetsim-kme` container. It mints keys
with `secrets.token_bytes` at a rate the `composite_sim_to_net` backend pushes
in, and serves them over the ETSI 014 GET routes. Nothing here runs NS-3 or
qkdnetsim: the image compiles both (see the Dockerfile), but no process started
by this file loads the result, and no key it serves came out of a simulation.

What it is useful for is the REST CONTRACT: `qkdnetsim_proxy` pulls enc_keys
from it, so the bb84-kme client code is exercised against a server it was not
written alongside. Key MATERIAL cannot be compared between the two, and nothing
tries to: two independent CSPRNG draws never agree.

An earlier docstring here described the keys as coming from qkdnetsim and the
server as indistinguishable from the NS-3 KMS. Neither held. The NS-3 KMS runs
on simulated sockets inside a simulation, so arnika could not have reached it
at all.

Routes:

  GET  /api/v1/keys/<sae>/status            ETSI 014 status object
  GET  /api/v1/keys/<sae>/enc_keys          number, size as query parameters
  GET  /api/v1/keys/<sae>/dec_keys?key_ID=  one-shot, for a key enc_keys issued
  POST /internal/set_rate                   composite_sim_to_net rate push
  GET  /health                              healthcheck

The ETSI 014 POST forms are not implemented; Flask answers them 405. Errors are
the ETSI 014 error object, `{"message": ...}`.
"""
from __future__ import annotations

import base64
import os
import secrets
import threading
import time
import uuid
from collections import OrderedDict, deque

from flask import Flask, jsonify, request

app = Flask(__name__)

SAE_ID = os.environ.get("SAE_ID", "ALICE")
PEER_SAE_ID = os.environ.get("PEER_SAE_ID", "BOB")
# KME identities are distinct from SAE identities in ETSI 014 (status reports
# both). They were reported as the SAE IDs, which conflated the two roles. No
# default: a status object naming an invented KME would be a fabricated value.
KME_ID = os.environ["KME_ID"]
PEER_KME_ID = os.environ["PEER_KME_ID"]
KEY_SIZE_BITS = int(os.environ.get("KEY_SIZE_BITS", "256"))
MAX_POOL = int(os.environ.get("MAX_POOL", "64"))
# The only consumer (qkdnetsim_proxy) asks for one key per call, and status has
# always advertised 1. It is now also enforced, so status and behaviour agree.
MAX_KEY_PER_REQUEST = int(os.environ.get("MAX_KEY_PER_REQUEST", "1"))
# Floor on the producer's sleep, so a very high pushed rate cannot turn the
# producer thread into a busy loop that starves the request threads.
MIN_PRODUCER_DELAY_S = 0.05
BITS_PER_BYTE = 8

_lock = threading.RLock()
# Keys not yet issued. Bounded by MAX_POOL; the oldest is dropped when full.
_pool: deque[dict] = deque()
# Keys issued through enc_keys and not yet collected through dec_keys. Also
# bounded by MAX_POOL. Before this, every key ever produced was also kept in a
# by-ID map that nothing pruned -- about 3.9 keys/s at the default rate, with no
# consumer needed -- and any caller could fetch any of them, any number of
# times. bb84-kme fixed the same leak in KeyPool._admit.
_issued: OrderedDict[str, dict] = OrderedDict()
_rate_bps = float(os.environ.get("INITIAL_KEY_RATE_BPS", "1000.0"))


def _error(status: int, message: str):
    return jsonify({"message": message}), status


def _int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    return int(raw)


def _producer():
    """Append a fresh key every KEY_SIZE_BITS / rate seconds."""
    while True:
        delay = max(KEY_SIZE_BITS / max(_rate_bps, 1.0), MIN_PRODUCER_DELAY_S)
        time.sleep(delay)
        key = secrets.token_bytes(KEY_SIZE_BITS // BITS_PER_BYTE)
        entry = {
            "key_ID": str(uuid.uuid4()),
            "key": base64.b64encode(key).decode("ascii"),
        }
        with _lock:
            if len(_pool) >= MAX_POOL:
                _pool.popleft()
            _pool.append(entry)


@app.route("/health")
def health():
    return "ok"


@app.route("/api/v1/keys/<sae>/status")
def status(sae):
    with _lock:
        return jsonify({
            "source_KME_ID": KME_ID,
            "target_KME_ID": PEER_KME_ID,
            "master_SAE_ID": SAE_ID,
            "slave_SAE_ID": sae,
            "key_size": KEY_SIZE_BITS,
            "stored_key_count": len(_pool),
            "max_key_count": MAX_POOL,
            "max_key_per_request": MAX_KEY_PER_REQUEST,
            # enc_keys serves exactly one size, so that is both bounds. It
            # advertised 64..1024 while rejecting every size but this one.
            "max_key_size": KEY_SIZE_BITS,
            "min_key_size": KEY_SIZE_BITS,
            "max_SAE_ID_count": 0,
        })


@app.route("/api/v1/keys/<sae>/enc_keys")
def enc_keys(sae):
    try:
        number = _int_arg("number", 1)
        size = _int_arg("size", KEY_SIZE_BITS)
    except ValueError:
        return _error(400, "number and size must be integers")
    if size != KEY_SIZE_BITS:
        return _error(400, f"only key size {KEY_SIZE_BITS} is supported")
    if not 1 <= number <= MAX_KEY_PER_REQUEST:
        return _error(400, f"number must be between 1 and {MAX_KEY_PER_REQUEST}")
    with _lock:
        # Check before popping. Popping first and then answering 503 on an
        # empty pool lost every key already taken for the request.
        if len(_pool) < number:
            return _error(503, "not enough keys in the pool")
        out = [_pool.popleft() for _ in range(number)]
        for entry in out:
            _issued[entry["key_ID"]] = entry
            while len(_issued) > MAX_POOL:
                _issued.popitem(last=False)
    return jsonify({"keys": out})


@app.route("/api/v1/keys/<sae>/dec_keys")
def dec_keys(sae):
    key_id = request.args.get("key_ID")
    if not key_id:
        return _error(400, "missing key_ID")
    with _lock:
        # One-shot: a key is handed to the slave SAE once and then forgotten.
        entry = _issued.pop(key_id, None)
    if entry is None:
        return _error(404, "unknown or already collected key_ID")
    return jsonify({"keys": [entry]})


@app.route("/internal/set_rate", methods=["POST"])
def set_rate():
    """Rate push from composite_sim_to_net.

    Unauthenticated, like bb84-kme's own /internal routes, and for the same
    reason acceptable only because nothing publishes this port: the overlay
    exposes the container on the Docker networks alone.

    A peer-sync route that used to sit beside this one accepted any key_ID and
    key into the pool that enc_keys serves. Nothing called it, so it is gone.
    """
    global _rate_bps
    body = request.get_json(force=True, silent=True) or {}
    try:
        rate = float(body.get("keyRate_bps", _rate_bps))
    except (TypeError, ValueError):
        return _error(400, "keyRate_bps must be a number")
    _rate_bps = max(1.0, rate)
    return jsonify({"ok": True, "rate_bps": _rate_bps})


if __name__ == "__main__":
    t = threading.Thread(target=_producer, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=80, threaded=True)
