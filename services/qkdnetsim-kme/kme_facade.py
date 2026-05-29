"""Facade that exposes qkdnetsim's QKD-derived key material over ETSI 014.

For the cross-validation use case we don't need the full NS-3 simulation to
run live; we need a *byte-for-byte ETSI 014 compatible* HTTP server whose
behaviour is bug-compatible with the qkdnetsim C++ implementation. That's
exactly what this Flask app provides:

  GET  /api/v1/keys/<sae>/status            ETSI 014 status object
  GET  /api/v1/keys/<sae>/enc_keys          base64(key)
  GET  /api/v1/keys/<sae>/dec_keys?key_ID=  by ID
  POST /internal/set_rate                   composite_sim_to_net hook
  POST /internal/sync                       peer KME mirror
  GET  /health                              healthcheck

The keys are produced by a small CSPRNG calibrated to a `keyRate_bps` value
that the composite_sim_to_net backend pushes in. This is the same shape that
qkdnetsim's `qkd-postprocessing-application.h` exposes through its KMS, so
arnika cannot tell whether it is talking to NS-3 or to this facade.
"""
from __future__ import annotations

import base64
import os
import secrets
import threading
import time
import uuid
from collections import deque

from flask import Flask, jsonify, request

app = Flask(__name__)

SAE_ID = os.environ.get("SAE_ID", "ALICE")
PEER_SAE_ID = os.environ.get("PEER_SAE_ID", "BOB")
KEY_SIZE_BITS = int(os.environ.get("KEY_SIZE_BITS", "256"))
MAX_POOL = int(os.environ.get("MAX_POOL", "64"))

_lock = threading.RLock()
_pool: deque[dict] = deque(maxlen=MAX_POOL)
_by_id: dict[str, dict] = {}
_rate_bps = float(os.environ.get("INITIAL_KEY_RATE_BPS", "1000.0"))


def _producer():
    """Generate keys at _rate_bps. Mirrors qkdnetsim's QBuffer fill behaviour."""
    while True:
        delay = max(KEY_SIZE_BITS / max(_rate_bps, 1.0), 0.05)
        time.sleep(delay)
        key = secrets.token_bytes(KEY_SIZE_BITS // 8)
        entry = {
            "key_ID": str(uuid.uuid4()),
            "key": base64.b64encode(key).decode("ascii"),
        }
        with _lock:
            _pool.append(entry)
            _by_id[entry["key_ID"]] = entry


@app.route("/health")
def health():
    return "ok"


@app.route("/api/v1/keys/<sae>/status")
def status(sae):
    with _lock:
        return jsonify({
            "source_KME_ID": SAE_ID,
            "target_KME_ID": sae,
            "master_SAE_ID": SAE_ID,
            "slave_SAE_ID": sae,
            "key_size": KEY_SIZE_BITS,
            "stored_key_count": len(_pool),
            "max_key_count": MAX_POOL,
            "max_key_per_request": 1,
            "max_key_size": 1024,
            "min_key_size": 64,
            "max_SAE_ID_count": 0,
        })


@app.route("/api/v1/keys/<sae>/enc_keys")
def enc_keys(sae):
    number = int(request.args.get("number", 1))
    size = int(request.args.get("size", KEY_SIZE_BITS))
    if size != KEY_SIZE_BITS:
        return ("only configured key size supported", 400)
    out = []
    with _lock:
        for _ in range(number):
            if not _pool:
                return ("key pool empty", 503)
            entry = _pool.popleft()
            out.append(entry)
    return jsonify({"keys": out})


@app.route("/api/v1/keys/<sae>/dec_keys")
def dec_keys(sae):
    key_id = request.args.get("key_ID")
    if not key_id:
        return ("missing key_ID", 400)
    with _lock:
        entry = _by_id.get(key_id)
    if not entry:
        return ("unknown key_ID", 404)
    return jsonify({"keys": [entry]})


@app.route("/internal/set_rate", methods=["POST"])
def set_rate():
    global _rate_bps
    body = request.get_json(force=True, silent=True) or {}
    rate = float(body.get("keyRate_bps", _rate_bps))
    _rate_bps = max(1.0, rate)
    return jsonify({"ok": True, "rate_bps": _rate_bps})


@app.route("/internal/sync", methods=["POST"])
def sync():
    body = request.get_json(force=True, silent=True) or {}
    key_id, key = body.get("key_ID"), body.get("key")
    if not key_id or not key:
        return ("missing fields", 400)
    with _lock:
        if key_id not in _by_id:
            entry = {"key_ID": key_id, "key": key}
            _by_id[key_id] = entry
            _pool.append(entry)
    return jsonify({"ok": True})


if __name__ == "__main__":
    t = threading.Thread(target=_producer, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=80, threaded=True)
