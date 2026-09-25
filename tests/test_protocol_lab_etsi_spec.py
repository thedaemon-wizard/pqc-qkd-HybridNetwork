"""The shared ETSI GS QKD 004 V2.1.1 spec file, and the 014 shapes /protocol-lab draws.

`services/webui-frontend/src/lib/sim/etsi004SpecV211.json` is read by the
browser simulator and by the KME's real endpoint. These checks pin what it may
say, independently of either reader:

  * status codes are exactly 0-8 with V2.1.1's meanings at the two codes
    Edition 3 renumbers (1 = peer not connected, 6 = timeout);
  * every QoS field is a uint32 (the mimetype aside) with the unit Table 2
    gives -- Key_chunk_size in BYTES, Timeout in ms, TTL in s;
  * every inferred transition says why, and every entry cites a clause.

And `etsi014Shapes.ts` may only describe this repository's actual 014 API, so
each path, status code and the bits claim is checked against etsi014.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO / "services/webui-frontend/src/lib/sim/etsi004SpecV211.json"
SHAPES = REPO / "services/webui-frontend/src/lib/sim/protocolLab/etsi014Shapes.ts"
ETSI014 = REPO / "services/bb84-kme/app/etsi014.py"

SPEC = json.loads(SPEC_PATH.read_text())


def test_it_is_v2_1_1():
    assert SPEC["standard"] == "ETSI GS QKD 004"
    assert SPEC["version"] == "V2.1.1"
    assert SPEC["published"] == "2020-08"


def test_status_codes_are_zero_to_eight_with_v2_meanings():
    codes = {s["code"]: s["id"] for s in SPEC["status_codes"]}
    assert sorted(codes) == list(range(9))
    assert codes[1] == "PEER_NOT_CONNECTED"
    assert codes[6] == "TIMEOUT"
    assert len(set(codes.values())) == 9


def test_qos_units_follow_table_2():
    units = {f["name"]: f["unit"] for f in SPEC["qos_fields"]}
    assert units == {
        "Key_chunk_size": "bytes", "Max_bps": "bps", "Min_bps": "bps", "Jitter": "bps",
        "Priority": None, "Timeout": "ms", "TTL": "s", "Metadata_mimetype": None,
    }
    for f in SPEC["qos_fields"]:
        if f["name"] != "Metadata_mimetype":
            assert f["type"] == "uint32", f["name"]
    assert SPEC["uint32_max"] == 2**32 - 1
    assert SPEC["mimetype_max_bytes"] == 256


def test_functions_and_directions():
    fns = {f["name"]: {p["name"]: p["dir"] for p in f["params"]} for f in SPEC["functions"]}
    assert fns["OPEN_CONNECT"] == {"source": "in", "destination": "in", "QoS": "inout",
                                   "Key_stream_ID": "inout", "status": "out"}
    assert fns["GET_KEY"] == {"Key_stream_ID": "in", "index": "inout", "Key_buffer": "out",
                              "Metadata": "inout", "status": "out"}
    assert fns["CLOSE"] == {"Key_stream_ID": "in", "status": "out"}


def test_metadata_keys_follow_table_3():
    keys = {m["name"]: m["unit"] for m in SPEC["metadata_keys"]}
    assert keys == {"age": "ms", "hops": None}


def test_every_entry_cites_and_every_inference_explains():
    for group in ("functions", "qos_fields", "status_codes", "metadata_keys", "transitions"):
        for e in SPEC[group]:
            assert e["ref"], (group, e)
    for t in SPEC["transitions"]:
        assert t["basis"] in ("spec", "inference"), t["id"]
        assert set(t["scope"]) <= {"sim", "endpoint"} and t["scope"], t["id"]
        if t["basis"] == "inference":
            assert t["rationale"], t["id"]
        if t["status"] is not None:
            assert 0 <= t["status"] <= 8, t["id"]


def test_the_binding_is_labelled_as_this_projects_and_starts_at_zero():
    b = SPEC["binding"]
    assert "own" in b["note"]
    assert b["index_origin"] == 0
    assert b["index_origin_rationale"]
    assert b["unknown_ksid_http"] == 404
    assert b["preferred_metadata_mimetype"] == "application/json"


def test_no_etsi_wording_is_claimed():
    assert "paraphrase" in SPEC["wording"]
    # V2.1.1's own status text carries the typo "in returnhas occurred"; a copy
    # of it here would mean the text was lifted rather than paraphrased.
    assert "returnhas" not in SPEC_PATH.read_text()


# ---- the 014 shapes ---------------------------------------------------------
def _shape(name: str) -> str:
    m = re.search(rf'{name}:\s*"([^"]+)"', SHAPES.read_text())
    assert m, name
    return m.group(1)


def test_the_014_shapes_describe_this_repositorys_api():
    src = ETSI014.read_text()
    assert f'APIRouter(prefix="{_shape("prefix")}"' in src
    for route in ("status", "encKeys", "decKeys"):
        path = _shape(route)
        assert f'"{path}"' in src, path
    assert _shape("sizeUnit") == "bits"
    assert "Key size in BITS" in src
    codes = dict(re.findall(r"(\w+):\s*(\d{3}),", SHAPES.read_text()))
    assert f"status_code={codes['wrongSize']}" in src
    assert f'status_code={codes["poolEmpty"]}, detail="key pool empty"' in src
    assert f"status_code={codes['unknownKeyId']}" in src
