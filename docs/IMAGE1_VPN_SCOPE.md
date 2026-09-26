# Reference image 1 (VPN scope) → code mapping

The reference image is Figure 3 of the arnika README,
`submodules/arnika/img/QKD-PQC-functions_post-quantum-secure-VPN.png`
("QKD | PQC functions post-quantum secure VPN"): two sites inside the VPN
scope, three operational modes (A: QKD-only, B: PQC-only, C: hybrid QKD+PQC)
and the ETSI 014 interface (E). This file maps each labelled element to the
`/e2e` page, and separately to the running component it stands for.

## What `/e2e` is

A client-side simulation. `services/webui-frontend/src/lib/sim/e2eSim.ts`
runs four steps in the browser with real `@noble` HKDF-SHA3-256 and
ChaCha20-Poly1305, over **random surrogate keys**: the QKD key and the PQC
secret are each `randomBytes(32)`, and a run makes no HTTP request (exports
aside: the toolbar can post an optional copy to the shared gallery, see
[`deployment-economics.md`](deployment-economics.md)). It reads no KME, no
Rosenpass output and no arnika state. The running lanes -- arnika, Rosenpass
and WireGuard in the `alice`/`bob` containers -- are a separate thing,
observed on `/`, `/vpn` and `/console`. The backend orchestrator the page once
used is recorded in [`phases.md`](phases.md), Phase 10.

## Element-by-element mapping

The page numbers its scheme in **steps**, not phases; see the decision record
in [`roadmap.md`](roadmap.md) on the three "phase" schemes.

| Image element | On `/e2e` (`e2eSim.ts`, `QuantumSecureE2E.tsx`) | Running counterpart, outside `/e2e` |
|---|---|---|
| Site A / Site B boundary | `ArchSvg`, centre divider line | Two containers on one host; see [`LIMITATIONS.md`](LIMITATIONS.md) |
| **KEY-CONTROL function** "ARNIKA" | Step 2 draws the QKD surrogate; step 3 runs the HKDF | `submodules/arnika` (Go, not modified here; pinned to the head of the open upstream PR #51) in `alice`/`bob` |
| **PQC function** "ROSENPASS" | Step 3: `pqcSecret = randomBytes(32)` in modes B and C; nothing is exchanged | No single component since 2026-09-26. The PQC key arnika mixes in (label B) now comes from arnika itself, a PQC-HPKE round with its peer (HPKE, MLKEM1024-P384). Rosenpass still runs in `alice`/`bob` (Classic McEliece 460896 + Kyber512), but it keys the separate `wg1` data tunnel, which is the reference paper's layering rather than this figure's |
| **VPN function** "WIREGUARD" | Step 4: ChaCha20-Poly1305 over 64 ping-sized payloads keyed by the derived value | Kernel WireGuard in `alice`/`bob`, or `wireguard-go` when the kernel module is absent: `wg0`, keyed by arnika, and `wg1` inside it, keyed by Rosenpass |
| **KMS Keystore [ETSI 014]** | A key-pool counter: step 1 adds one key, step 2 draws one in modes A and C | `services/bb84-kme/app/etsi014.py` |
| **QKD KEY** (label A) | Step 2: `qkdKey = randomBytes(32)` and `keyId = crypto.randomUUID()`, modes A and C | ETSI 014 `enc_keys` / `dec_keys` between arnika and `bb84-kme` |
| **PQC KEY** (label B) | Step 3: `pqcSecret = randomBytes(32)`, modes B and C | The 32-byte export of arnika's PQC-HPKE round, held in memory; no file (`PQC_PSK_FILE` was removed by the unmerged arnika#51 that the pin follows) |
| **QKD+PQC KEY** (label C) | Step 3: `deriveHkdfSha3(qkdKey, pqcSecret, mode)` in `lib/sim/crypto.ts`, 32 bytes | arnika `DeriveKey`, `submodules/arnika/kdf/kdf.go:17-39` |
| **HKDF (SHA3)** (circle inside ARNIKA) | HKDF-SHA3-256 over `qkd ‖ pqc`, salt `pqcqkd-e2e`, info `mode-A`/`mode-B`/`mode-C` | Same hash, different parameters: arnika passes a nil salt and nil info, so the page's value is **not** the PSK arnika would derive from the same inputs |
| **QKD key_ID exchange** (green dashed line) | SVG animation during step 2 only; no `dec_keys` request is made | arnika peers send the `key_ID` over UDP and the BACKUP resolves it with `dec_keys` |
| **PQC KEY exchange** (pink curve) | SVG animation during step 3, modes B and C only | The PQC-HPKE round between the two arnika peers, over arnika's own UDP socket |
| **Quantum channel** (purple dashed arc) | SVG animation during step 1 only | The BB84 simulation inside `bb84-kme`, which depends on the selected backend |
| **Mode A / B / C** labels | `setMode(...)` calls `simRef.current.setMode(...)`, no HTTP. A omits the PQC secret, B omits the QKD key, C uses both | arnika's `MODE` is a fallback policy, not a fixed key set; compose defaults `ARNIKA_MODE` to `QkdAndPqcRequired`, with `PQC_ENABLED` true on every arnika instance |
| **ETSI interface E** | Badge animation during step 2 | `etsi014.py` serves `/api/v1/keys/{SAE}/{enc,dec}_keys`; wire format below |
| **Secure Application Entity** (purple dashed box) | SVG only | arnika's README defines the SAE as WireGuard + PQC + arnika, i.e. each node container |

**The ETSI 014 wire format** is the part that can be checked. A byte-for-byte
comparison of `kms.go` against `etsi014.py` is not well-formed -- the first is
an HTTP *client*, the second a FastAPI *server*, and no code path compares
them. What arnika depends on is the field names: its `kmsKey` and
`kmsResponse` structs (`submodules/arnika/repositories/kms/kms.go:43-50`) read
`key_ID`, `key` and `keys`, `etsi014.py` (`KeyDTO`, `KeysResponse`) emits
exactly those, and the CI job `live-stack` drives the real endpoints with
`tests/test_etsi014_contract.py`.

## Active-element highlighting rules

The glow on each element follows these rules (`QuantumSecureE2E.tsx::ArchSvg`):

```
step 1 → Quantum-channel lane glows
step 2 → KMS keystores, the "E" badges, both KMS↔ARNIKA arrows and the
         QKD key_ID exchange lane glow; ARNIKA boxes glow
step 3 → ARNIKA boxes stay lit; ROSENPASS boxes and the PQC KEY exchange
         lane glow when mode ∈ {B, C}; the HKDF (SHA3) badges glow when
         mode === "C"
step 4 → WIREGUARD boxes, the VPN lock and the tunnel line across the
         divider glow
```

## Live verification

Open `/e2e` in the WebUI. The Mode buttons map to the image's A / B / C labels,
and Run / Pause / Resume / Step / Reset drive the four steps; each step dwells
500 ms nominally (`NOMINAL_STEP_DWELL_MS` in `e2eSim.ts`, five ticks of the
100 ms loop in `lib/sim/pacing.ts`), so a full cycle is about 2 s unless the
tab is in the background and the browser throttles timers.

Idle, running and paused states were reviewed on screen. **No capture was committed.**

## Layout

The SVG is geometry-driven (`GEO` in `QuantumSecureE2E.tsx`), with a
`1240×600` viewBox, and Site B mirrors Site A about the divider. The A/B/C/E
legend is an HTML strip (`ArchLegend`) below the SVG rather than part of it.
The earlier 880×280 layout and its Phase 11 and Phase 14 revisions are
recorded in [`phases.md`](phases.md).

## Alternative PSK injection implementations

`submodules/arnika` is not the only maintained OSS that feeds post-quantum
secrets into the WireGuard PSK channel. The closest alternative is
**`mullvad/wgephemeralpeer`**, vendored as a submodule in Phase 11.

| | `arnika` (this PoC) | `mullvad/wgephemeralpeer` |
|---|---|---|
| Origin | Originally CANCOM Converged Services GmbH (v1.x under EU EUROQCI / QCI-CAT); maintained at XBC Digital GmbH since Q2 2026. The pin is the head of the open PR #51, built on `main`, which has diverged from `v1.x` | Mullvad VPN |
| Language | Go | Go |
| License | Apache-2.0 | GPL-3.0 |
| Pinned revision | `f4cf9ba` (2026-09-24) | `0080bf8` (2026-05-08) |
| Key sources | QKD (ETSI 014) ‖ PQC (its own HPKE round with the peer, MLKEM1024-P384) | PQC handshake: Classic McEliece 460896 Round3 + ML-KEM-1024 (default `-kem cme-mlkem`; the Kyber1024 variants are listed as obsolete) |
| KDF | HKDF-SHA3-256 (`submodules/arnika/kdf/kdf.go:17-39`) | embedded in `mullvad-upgrade-tunnel` |
| WireGuard hook | `wgctrl` netlink, write `preshared-key` | `PostUp = mullvad-upgrade-tunnel -wg-interface %i` |
| QKD support | Yes (ETSI 014 native) | No (PQC-only) |
| Production deployment | research / PoC | live commercial VPN at Mullvad |
| Multi-hop trusted node | Yes | No (single tunnel) |

Both are architectural cousins (PSK injection) but solve different problem shapes:
arnika targets **QKD + PQC hybrid for regulated infrastructure**, while
wgephemeralpeer targets **commercial consumer VPN with PQC-only PSK rotation**.
In this repository `wgephemeralpeer` is vendored as a reference for comparison
only: no Dockerfile, compose file or script builds or runs it.
