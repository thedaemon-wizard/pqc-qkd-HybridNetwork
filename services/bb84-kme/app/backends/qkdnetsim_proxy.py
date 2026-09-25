"""qkdnetsim proxy backend — fetches keys from the qkdnetsim-kme container.

With SIMULATOR_BACKEND=qkdnetsim_proxy this backend pulls /enc_keys from the
`qkdnetsim-kme` service instead of producing keys itself: the GET form of ETSI
GS QKD 014 `enc_keys`, answered by a second, independently written server.

That service exists only in the `crossvalidate` compose overlay. `preflight`
checks its /health before a live switch is accepted, because without it every
round fails and the key pool arnika draws from stops refilling.

Nothing automated runs the ETSI 014 contract suite against that server. This
docstring used to name `tests/test_etsi014_contract.py` as what does; CI points
that suite at bb84-kme-a/b, no CI job or Makefile target starts the overlay,
and the facade registers its key routes GET-only, so the suite's POST-form
cases would get 405 there.

What this docstring used to claim, and why it was wrong

    It said the peer was "running its C++ ETSI 014 implementation", and that
    this "lets the same arnika integration test prove the Python KME matches
    the NS-3 reference implementation byte-for-byte".

    `services/qkdnetsim-kme/kme_facade.py` is a Flask app that mints keys with
    `secrets.token_bytes`. No NS-3 binary is invoked in that service. The
    consumer named as the proof, `tests/test_etsi014_crossvalidate.py`, has
    never existed.

    The claim could not have been true even in principle: byte-for-byte
    equality between two independent CSPRNG draws is not an unverified
    property, it is an impossible one. Two KMEs agreeing on key MATERIAL would
    mean one of them was not generating any.

    What the facade does is in its code, not its prose: key routes that mint
    material with `secrets.token_bytes` and answer GET only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from base64 import b64decode

import httpx

from ._skr import skr_bps_from_config
from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)

# How long a live switch waits for qkdnetsim-kme's /health. It has to stay well
# under the 5 s the webui-backend fan-out allows each KME (sim_backend_proxy),
# or the refusal below would reach the page as a timeout rather than as a 503
# carrying its reason.
HEALTH_PROBE_TIMEOUT_S = 2.0
NOT_DEPLOYED_HINT = (
    "qkdnetsim-kme is not deployed on this host (it runs only with the "
    "`crossvalidate` compose profile, docker-compose.qkdnetsim.yml)"
)


class QKDNetSimProxyBackend(KeyProducer):
    backend_name = "qkdnetsim_proxy"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        self._url = cfg.qkdnetsim_proxy_url or "http://qkdnetsim-kme:80"

    async def preflight(self) -> None:
        """Refuse the switch unless qkdnetsim-kme answers /health.

        The switch used to be accepted unconditionally. On a host without the
        overlay, `qkdnetsim-kme` does not resolve, every round then failed and
        was recorded as aborted, the pool stopped refilling, and arnika's
        enc_keys eventually answered 503 -- while /physics reported the switch
        as requested.
        """
        try:
            async with httpx.AsyncClient(timeout=HEALTH_PROBE_TIMEOUT_S) as client:
                r = await client.get(f"{self._url}/health")
        except httpx.HTTPError as e:
            raise RuntimeError(f"{NOT_DEPLOYED_HINT}: {self._url}/health: {e}") from e
        if r.status_code != httpx.codes.OK:
            raise RuntimeError(
                f"{NOT_DEPLOYED_HINT}: {self._url}/health answered HTTP {r.status_code}")

    async def run_round(self) -> RoundOutcome:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{self._url}/api/v1/keys/ALICE/enc_keys",
                    params={"number": 1, "size": self.cfg.out_bits_per_key},
                )
                r.raise_for_status()
                body = r.json()
            key_b64 = body["keys"][0]["key"]
            key = b64decode(key_b64)
        except Exception as e:
            log.warning("qkdnetsim proxy failed: %s", e)
            return RoundOutcome(
                accepted=False, qber=1.0, key_bytes=b"",
                n_photons=0, n_sifted=0, intercepted=0,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                backend_meta={"backend": "qkdnetsim_proxy", "error": str(e)},
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        # NONE of the per-round physics below is measured, because the peer
        # reports none. `kme_facade.py`'s /enc_keys returns exactly
        # {"key_ID": uuid4(), "key": base64(secrets.token_bytes(...))} -- no
        # qber, no photon count, no sifted count, no error rate, anywhere in
        # that response or its /status object.
        #
        # qber=0.0 is not merely optimistic, it is impossible: the analytical
        # Lo-Ma E_mu for this configuration is 0.0150, and a real BB84 link
        # cannot have a zero error rate. It is a placeholder that reads as a
        # perfect channel.
        #
        # These stay as they are rather than becoming None -- RoundOutcome types
        # them int/float and every consumer assumes that -- but the round is now
        # MARKED, and `unmeasured` names each field so a reader does not have to
        # know which of them this backend can and cannot know.
        #
        # skr_bps is deliberately NOT in that list. Reporting
        # skr_bps_from_config(cfg) is a repository-wide contract asserted by
        # tests/test_skr_is_not_a_sifting_ratio.py::test_backend_reports_the_shared_rate
        # ("No backend may reintroduce its own derivation"). What is worth
        # saying about it here is narrower: the shared Lo-Ma fibre model
        # describes a link this backend never traverses, since the keys arrive
        # over HTTP from a CSPRNG. It is a model of the wrong channel, not an
        # invented constant.
        meta = {
            "backend": "qkdnetsim_proxy",
            "source": self._url,
            # The marker tests/test_skr_is_not_a_sifting_ratio.py already
            # demands of the simqn backend, and which this one omitted.
            "synthetic": True,
            "unmeasured": ["qber", "n_photons", "n_sifted", "intercepted"],
            "note": (
                "the peer serves key material only; no per-round physics is "
                "measured. skr_bps is the shared closed-form rate for the "
                "configured fibre, which this lane does not traverse."
            ),
        }
        if self.cfg.eve_enabled:
            # The Eve control is a no-op here and used to say nothing. Driven
            # with intercept_prob=1.0 the round still returned qber=0.0 and
            # intercepted=0 -- a knob that appears to work and changes nothing.
            meta["eve_ignored"] = True
            log.warning(
                "eve_enabled is set but has no effect on qkdnetsim_proxy: keys "
                "arrive over HTTP, there is no quantum channel to intercept",
            )
        return RoundOutcome(
            accepted=True,
            qber=0.0,
            key_bytes=key,
            n_photons=self.cfg.bb84_batch_size,
            n_sifted=self.cfg.bb84_batch_size // 2,
            intercepted=0,
            elapsed_ms=elapsed_ms,
            # Was pulse_rate_hz / 2 -- a constant with no physics in it at all,
            # reported in a field named skr_bps.
            skr_bps=skr_bps_from_config(self.cfg),
            backend_meta=meta,
        )

    async def _sleep_a_bit(self) -> None:
        await asyncio.sleep(0.01)
