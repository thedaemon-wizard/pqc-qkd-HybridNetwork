"""The POST rate limiter must be active on the host that faces the internet.

Measured against the live public demo 2026-08-28:

    GET  /api/config          -> {"demo_mode": false,
                                  "container_control": false,
                                  "rate_limit": null}
    POST /api/sim/optimize    -> HTTP 200 in 14.598 s

14.6 seconds of server CPU (skopt `gp_minimize`, 50 evaluations), from one
unauthenticated request, with no throttle -- because the token bucket was
gated on `DEMO_MODE`, and the public host runs with `DEMO_MODE` unset.

That gating is backwards. `DEMO_MODE` exists to REMOVE capability (container
control, privileged nodes). It is not a declaration that a host is exposed.

Two changes, and this file pins both:

  * the limiter runs on every POST regardless of `DEMO_MODE`
  * `POST /api/sim/optimize` and `POST /sim/optimize` are gone -- the route,
    not the module: `optimize_from_yaml()` stays importable for offline use,
    exercised by tests/test_backend_cross_qber.py and documented in
    docs/phases.md

Nothing could have caught this. The limiter had tests, and they set
`DEMO_MODE=1` first -- so they verified the bucket arithmetic on a
configuration the public host does not run.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "services" / "webui-backend" / "app" / "main.py"
KME = REPO / "services" / "bb84-kme" / "app" / "main.py"


def _src(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The limiter is not gated on DEMO_MODE.
# --------------------------------------------------------------------------

def test_the_limiter_does_not_test_demo_mode():
    """The exact expression that made it inert in production."""
    src = _src(BACKEND)
    body = src[src.index("async def demo_rate_limit"):]
    body = body[:body.index("\nreturn await call_next") + 40] if \
        "\nreturn await call_next" in body else body[:2500]
    assert 'if DEMO_MODE and request.method == "POST"' not in body, (
        "the limiter is gated on DEMO_MODE again, so it is inert on the public "
        "host, which runs with DEMO_MODE unset")


def test_the_limiter_guard_is_the_method_alone():
    """The guard is the METHOD SET, and it must cover every mutating verb.

    This test previously asserted the literal `request.method == "POST"` with
    the message "the limiter must still apply to state-changing requests". It
    was green while the project's one non-POST mutating route --
    `DELETE /api/exports/{filename}` -- sat outside the limiter entirely.

    So the assertion did not merely fail to catch the gap. It pinned the exact
    scope that created it, while its own message asserted the property it was
    letting through. Measured on the public host before the fix: thirty
    consecutive unauthenticated deletes, thirty 200s, no throttle.
    """
    src = _src(BACKEND)
    i = src.index("async def demo_rate_limit")
    body = src[i:i + 2500]
    assert 'if request.method in ("POST", "PUT", "PATCH", "DELETE"):' in body, (
        "the limiter's method set is gone or reworded; it must cover every "
        "mutating verb, not POST alone")
    assert 'if request.method == "POST":' not in body, (
        "the limiter is POST-only again, which leaves DELETE unthrottled")


def test_every_mutating_route_served_is_covered_by_that_set():
    """Derived from the routes, so a new verb cannot slip past the set above.

    The old guard was a string check with no relationship to what the app
    actually serves, which is why adding a DELETE route never disturbed it.
    """
    src = _src(BACKEND)
    verbs = set(re.findall(r"@app\.(get|post|put|patch|delete)\(", src))
    mutating = sorted(verbs - {"get"})
    i = src.index("async def demo_rate_limit")
    guard = src[i:i + 2500]
    uncovered = [v for v in mutating if v.upper() not in guard]
    assert not uncovered, (
        f"these mutating verbs are served but not rate limited: {uncovered}. "
        f"Add them to the method set in demo_rate_limit.")
    assert "delete" in mutating, (
        "no DELETE route is served any more; if that is deliberate this "
        "assertion and the DELETE arm of the limiter can both go, but the "
        "removal should be noticed rather than assumed")


def test_the_limiter_still_has_its_bucket_arithmetic():
    """Turning it always-on must not have flattened it into a no-op."""
    src = _src(BACKEND)
    i = src.index("async def demo_rate_limit")
    body = src[i:i + 2500]
    for token in ("DEMO_RATE_MAX", "DEMO_RATE_WINDOW_S", "429", "_rate_state"):
        assert token in body, f"{token} is missing from the limiter"


def test_the_env_var_names_are_unchanged():
    """Renaming them would silently drop the limits on existing deployments."""
    src = _src(BACKEND)
    assert 'os.environ.get("DEMO_RATE_MAX"' in src or "DEMO_RATE_MAX" in src
    assert "DEMO_RATE_WINDOW_S" in src


# --------------------------------------------------------------------------
# The heavy route is gone from both services.
# --------------------------------------------------------------------------

def test_the_optimize_route_is_deleted_from_the_public_api():
    src = _src(BACKEND)
    assert not re.search(r'^@app\.(post|get)\("/api/sim/optimize"\)', src, re.M), (
        "POST /api/sim/optimize is back. It cost 14.6 s of unauthenticated "
        "server CPU per request and had no caller.")


def test_the_optimize_route_is_deleted_from_the_kme():
    src = _src(KME)
    assert not re.search(r'^@app\.(post|get)\("/sim/optimize"\)', src, re.M), (
        "POST /sim/optimize is back on the KME, which the backend proxy could "
        "reach again")


def test_no_frontend_code_calls_it():
    """It had no caller before the deletion; it must not gain one."""
    src_dir = REPO / "services" / "webui-frontend" / "src"
    hits = [str(f.relative_to(REPO)) for f in src_dir.rglob("*.ts*")
            if "sim/optimize" in f.read_text(encoding="utf-8")]
    assert hits == [], f"a caller appeared: {hits}"


# --------------------------------------------------------------------------
# The module survived. Deleting it would have been a different change.
# --------------------------------------------------------------------------

def test_the_optimizer_module_is_still_importable():
    """The exposure was the route. The maths is a legitimate offline tool."""
    mod = REPO / "services" / "bb84-kme" / "app" / "optimizer.py"
    assert mod.exists(), (
        "optimizer.py was deleted along with the route. It is exercised by "
        "tests/test_backend_cross_qber.py and documented in docs/phases.md; "
        "removing it deletes a working capability to fix an exposure that "
        "removing one route already fixes.")
    assert "def optimize_from_yaml" in mod.read_text(encoding="utf-8")


def test_the_kme_no_longer_imports_it_at_module_scope():
    """Nothing should pull skopt into the request path any more."""
    src = _src(KME)
    assert "from . import config_loader, etsi014, logging_setup\n" in src, (
        "the import line changed; check that `optimizer` is not being imported "
        "at module scope, which would load skopt into the serving process")


def test_architecture_no_longer_advertises_the_endpoint():
    txt = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "/api/sim/optimize" not in txt, (
        "ARCHITECTURE.md still shows the deleted endpoint in a diagram")


def test_api_config_does_not_report_null_while_the_limiter_runs():
    """The field and the middleware must agree.

    `rate_limit` was `... if DEMO_MODE else None`, which matched the old
    DEMO_MODE-gated middleware -- both off together, so the report was honest.
    Making the limiter always-on without this would have had /api/config
    announce "no rate limit" on a host that has one.
    """
    src = _src(BACKEND)
    # Scope to the /api/config handler. The limiter's own docstring quotes the
    # old `{"demo_mode": false, "rate_limit": null}` payload as the evidence
    # for why it changed, and a naive first-occurrence search finds that
    # instead of the field -- which is how this test first failed.
    i = src.index('@app.get("/api/config")')
    handler = src[i:src.index("\n@app.", i + 10)]
    j = handler.index('"rate_limit":')
    field = handler[j:j + 200]
    assert "if DEMO_MODE else None" not in field, (
        "/api/config reports rate_limit: null while the limiter is active")
    assert "DEMO_RATE_MAX" in field and "DEMO_RATE_WINDOW_S" in field
