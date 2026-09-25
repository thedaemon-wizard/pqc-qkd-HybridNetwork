"""Two pure-function endpoints were recomputed on every page load.

Measured 2026-09-26 against the pqc-validator and bb84-kme images run on a
development workstation, uncached (a small hosted VM is slower):

    POST /api/pqc/agility     1.7 s   3 ML-KEM + 3 HQC keygen/encap/decap and
                                      3 ML-DSA + 4 SLH-DSA keygen/sign/verify/
                                      reject-tampered in liboqs
    GET  /api/verify/keyrate  1.0 s   closed form (microseconds) plus a scipy
                                      optimise inside the TNO engine; first
                                      call, then 0.2 s once it is imported

`/verify` fetches both on mount, so uncached, every visitor costs the sum of
the two in server CPU before seeing anything, and N concurrent viewers
multiply it.

CACHED RATHER THAN MOVED TO THE BROWSER, deliberately. `lib/sim/pqc.ts` exports
an `agilityMatrix()` computing the same matrix with @noble/post-quantum, and
/verify runs it only as an on-demand cross-check beside the liboqs rows. Using
it as a replacement would be the larger saving. It would also make the panel
title "Crypto-Agility Matrix (liboqs ...)" and the citable export line
"# Crypto-agility matrix (liboqs)" FALSE, because the numbers would then come
from a different library. Provenance is what that page is for. The cache buys
most of the time back and costs no honesty.

The key-rate cache is INVALIDATED rather than left on a TTL. A bare window
would make VERIFICATION_CHECKLIST.md row 4.7.10 racy: it instructs the reader
to POST a new link length and reload /verify, and inside the window they would
read the previous distance's verdict and reasonably conclude the endpoint is
broken.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
MAIN = REPO / "services" / "webui-backend" / "app" / "main.py"


def _src() -> str:
    return MAIN.read_text(encoding="utf-8")


def test_both_expensive_endpoints_consult_a_cache():
    src = _src()
    for route, key in (('@app.post("/api/pqc/agility")', '"agility"'),
                       ('@app.get("/api/verify/keyrate")', '"keyrate"')):
        i = src.index(route)
        body = src[i:src.index("\n@app.", i + 10)]
        assert "_cached(" in body, f"{route} does not consult the cache"
        assert key in body, f"{route} does not use the key {key}"


def test_a_cached_response_says_so():
    """A reader must be able to tell a fresh answer from a stored one."""
    src = _src()
    assert src.count('"cached": True') >= 2
    assert src.count('"cached": False') >= 2
    assert "cache_age_s" in src, (
        "a cached response that does not carry its age is indistinguishable "
        "from a fresh one, which is the shape this repository keeps removing")


def test_every_route_that_mutates_kme_state_invalidates_the_keyrate_cache():
    """Backend swap, parameter override and reset all change the answer."""
    src = _src()
    for fn in ("sim_backend_proxy", "sim_params_set_proxy",
               "sim_params_reset_proxy"):
        i = src.index(f"async def {fn}(")
        body = src[i:src.index("\n@app.", i + 10)]
        assert "_invalidate_keyrate_cache()" in body, (
            f"{fn} changes the KME's effective config without dropping the "
            f"key-rate cache, so /verify can serve the previous answer")


def test_the_invalidator_exists_and_clears_only_the_keyrate_entry():
    src = _src()
    i = src.index("def _invalidate_keyrate_cache(")
    body = src[i:i + 1200]
    assert '_pure_cache.pop("keyrate"' in body
    assert "clear()" not in body, (
        "it clears the whole cache; the agility matrix does not depend on KME "
        "config and would be needlessly recomputed at 4 s a time")


def test_the_agility_cache_is_not_invalidated_by_config_changes():
    """It runs a fixed algorithm list; KME parameters cannot change it."""
    src = _src()
    i = src.index("def _invalidate_keyrate_cache(")
    body = src[i:i + 1200]
    assert '"agility"' not in body


def test_a_caller_supplied_list_never_reaches_the_validator():
    """The validator is asked for its default matrix and nothing else.

    This used to read "a caller supplying an explicit list is not served the
    cache" -- and the list was forwarded verbatim, unbounded, to a validator
    that spends about 0.6 s per SLH-DSA entry. An explicit list is now answered
    by selecting rows of the cached default matrix
    (tests/test_pqc_agility_request_is_bounded.py pins the behaviour).
    """
    src = _src()
    i = src.index("async def _fetch_default_agility(")
    body = src[i:src.index("\n@app.", i + 10)]
    assert 'json={}' in body, "the default-matrix fetch no longer posts an empty body"
    i = src.index('@app.post("/api/pqc/agility")')
    handler = src[i:src.index("\n@app.", i + 10)]
    assert "json=req" not in handler and "json=req" not in body, (
        "a caller's body is forwarded to the validator again")


def test_the_ttls_are_env_overridable_and_have_defaults():
    src = _src()
    assert 'os.environ.get("PQC_AGILITY_TTL_S"' in src
    assert 'os.environ.get("KEYRATE_TTL_S"' in src


def test_the_keyrate_ttl_is_short_enough_to_be_a_backstop_not_the_mechanism():
    """Invalidation is the mechanism; the TTL only bounds anything missed."""
    src = _src()
    m = re.search(r'KEYRATE_TTL_S = float\(os\.environ\.get\("KEYRATE_TTL_S", "([\d.]+)"\)\)', src)
    assert m, "the key-rate TTL default is gone"
    assert float(m.group(1)) <= 30.0, (
        f"a {m.group(1)} s window is long enough for a reader following "
        f"checklist 4.7.10 to see a stale verdict even with invalidation in "
        f"place for the paths that have it")
