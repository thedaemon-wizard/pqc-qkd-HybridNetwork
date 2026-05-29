"""qkdnetsim proxy backend — fetches keys from the NS-3 reference KME container.

Used for ETSI 014 cross-validation: when SIMULATOR_BACKEND=qkdnetsim_proxy,
this backend pulls /enc_keys from the qkdnetsim-kme service (running its
C++ ETSI 014 implementation) instead of producing keys itself.

This lets the same arnika integration test prove the Python KME matches the
NS-3 reference implementation byte-for-byte.
"""
from __future__ import annotations

import asyncio
import logging
import time
from base64 import b64decode

import httpx

from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)


class QKDNetSimProxyBackend(KeyProducer):
    backend_name = "qkdnetsim_proxy"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        self._url = cfg.qkdnetsim_proxy_url or "http://qkdnetsim-kme:80"

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
        return RoundOutcome(
            accepted=True,
            qber=0.0,
            key_bytes=key,
            n_photons=self.cfg.bb84_batch_size,
            n_sifted=self.cfg.bb84_batch_size // 2,
            intercepted=0,
            elapsed_ms=elapsed_ms,
            skr_bps=self.cfg.pulse_rate_hz / 2,
            backend_meta={"backend": "qkdnetsim_proxy", "source": self._url},
        )

    async def _sleep_a_bit(self) -> None:
        await asyncio.sleep(0.01)
