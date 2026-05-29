# Reference Image 1 (VPN scope) → code mapping

The reference architecture image distributed with this PoC shows two sites (Site A,
Site B) inside the VPN scope with three operational modes (A: QKD-only, B: PQC-only,
C: Hybrid QKD+PQC) plus the ETSI 014 interface (E). This file documents how every
labelled element in that image is realised by the Phase 10 implementation.

## Element-by-element mapping

| Image element | Code | Notes |
|---|---|---|
| Site A / Site B boundary | `services/webui-frontend/src/pages/QuantumSecureE2E.tsx::ArchSvg` (vertical centre divider line) | Pure SVG, no per-site backend split |
| **KEY-CONTROL function** "ARNIKA" | `submodules/arnika-vq` (Go binary, unmodified) — modelled in `e2e_orchestrator.py::_run_one_cycle` Phase 2 | Real arnika container runs in WireGuard lane (Phase 0-7); orchestrator emulates the KEY-CONTROL semantics |
| **PQC function** "ROSENPASS" | `submodules/rosenpass` (Phase 0) — modelled in `e2e_orchestrator.py` Phase 3 (`secrets.token_bytes(32)` as Rosenpass surrogate) | Real Rosenpass sidecar runs in alice/bob node containers |
| **VPN function** "WIREGUARD" | `nodes/alice/entrypoint.sh` (Phase 0) — modelled in `e2e_orchestrator.py` Phase 4 (`ChaCha20Poly1305(derived_psk)`) | Real kernel wg0 runs in alice/bob; orchestrator uses the same AEAD that WireGuard uses internally |
| **KMS Keystore [ETSI 014]** | `services/bb84-kme/app/etsi014.py` (Phase 1) | Live ETSI 014 server; orchestrator phase 1 polls `/api/v1/keys/ALICE/status` |
| **QKD KEY** (yellow, label A) | `e2e_orchestrator.py` Phase 2 → `qkd_key_b` (base64-decoded from KME-A `/enc_keys`) | 256-bit material from SimQN backend |
| **PQC KEY** (pink, label B) | `e2e_orchestrator.py` Phase 3 → `pqc_secret` (random 32 B) | Mock Rosenpass output; mode B / C only |
| **QKD+PQC KEY** (red, label C) | `e2e_orchestrator.py` Phase 3 → `derived` (HKDF-SHA3-256 of qkd ‖ pqc) | 32 B WireGuard-style PSK |
| **HKDF (SHA3)** (red circle inside ARNIKA) | `e2e_orchestrator.py` → `HKDF(algorithm=hashes.SHA3_256(), ...)` from `cryptography==44.0.0` | Surrogates `submodules/arnika-vq/kdf/kdf.go:12-27` (same SHA-3-256 primitive) |
| **QKD key_ID exchange** (green dashed line) | Phase 2 internal step (`GET /dec_keys?key_ID=…` at KME-B) + SVG dashed arc on `phase===2` | Mirror of arnika's enc_keys → dec_keys handshake |
| **PQC KEY exchange** (pink curve) | Phase 3 active path + SVG curve with `mode B/C` highlight | Conceptual; orchestrator uses local random as Rosenpass surrogate |
| **Quantum channel** (purple dashed top arc) | Phase 1 active path + SVG curve with `phase===1` highlight | Implicit in SimQN's `QubitLossChannel` model |
| **Mode A** label | `QuantumSecureE2E.tsx` `setMode("A")` → POST `/api/e2e/mode {mode:"A"}` → `state.mode = "A"` (mode_label = "QKD-only") | Skips PQC in Phase 3 |
| **Mode B** label | Same flow with `mode="B"` (mode_label = "PQC-only") | Skips QKD in Phase 2 |
| **Mode C** label | Same flow with `mode="C"` (mode_label = "Hybrid (QKD ‖ PQC)") | Default; both Phase 2 and Phase 3 active |
| **ETSI interface E** | `services/bb84-kme/app/etsi014.py` (`/api/v1/keys/{SAE}/{enc,dec}_keys`) | Matches `submodules/arnika-vq/kms/kms.go:69-176` byte-for-byte |
| **Secure Application Entity** (purple dashed box) | The combination of bb84-kme + webui-backend orchestrator | The "application" boundary of the PoC |

## Active-element highlighting rules

The SVG glow on each element follows these rules (see `QuantumSecureE2E.tsx::ArchSvg`):

```
phase 1 → Quantum-channel curve glows (purple)
phase 2 → ARNIKA boxes glow (orange), KMS↔ARNIKA key-line glows (red),
          green dashed QKD key_ID exchange curve glows
phase 3 → ROSENPASS boxes glow (pink) when mode ∈ {B, C},
          HKDF (SHA3) circles glow inside ARNIKA when mode === "C"
phase 4 → WIREGUARD boxes glow (purple),
          VPN tunnel line across the divider glows (red)
```

## Live verification

Open `/e2e` in the WebUI. The Mode buttons map to the image's A / B / C labels;
the operation buttons drive the state machine through the 4 phases at ~12-20 Hz on
the reference Intel i5-13600K host.

Captured screenshots: `docs/images/screenshots/` (idle, running, paused).

## Layout v2 (Phase 11)

The Phase 10 SVG was 880×280 and missed three dashed boundary boxes, the top key-color
legend, the centre VPN lock icon, the ETSI Interface "E" badges, and the bottom-left
A/B/C/E legend. Phase 11 rewrites it to **1240×620** (145 SVG elements vs ~30 before)
with full 1:1 element parity to the reference image:

| Reference image element | v2 implementation |
|---|---|
| VPN scope (red dashed outer) | `<rect>` at 150,60 size 940×440, stroke-dasharray="6 4" |
| Secure Application Entity (purple dashed) | two `<rect>` per site at x=180/640, y=160, 420×220 |
| Quantum Key Distribution Infrastructure (blue dashed) | `<rect>` at x=10 and x=1100, 130×380 |
| Top key-colour legend (A/B/C with key icons) | `<KeyLegend>` per site, mirrored on Site B |
| KMS Keystore [ETSI 014] + QKD sub-box (green) | `<KmsKeystore>` at x=40 / x=1100 |
| ETSI Interface "E" badge (orange circle) | `<ETSIBadge>` at KMS↔ARNIKA boundary |
| Centre "VPN" lock icon (red) | `<g>` with circle + rect + shackle path |
| ARNIKA / ROSENPASS / WIREGUARD boxes | `<SiteBox>` 108×80 |
| HKDF (SHA3) red circle inside ARNIKA | `<HkdfBadge>` |
| PQC KEY exchange row (pink curve, y≈420) | independent SVG path |
| QKD key_ID exchange row (green dashed, y≈470) | independent SVG path, vertically separated |
| Quantum Channel row (purple dashed, y≈540) | independent SVG path at the very bottom |
| Bottom-left A/B/C/E legend | `<LegendItem>` ×4 stacked |

Verification: `docs/images/screenshots/e2e-v2-idle.png` and `e2e-v2-phase1.png`.

## Alternative PSK injection implementations (2026-active)

`submodules/arnika-vq` is not the only 2026-maintained OSS that wires post-quantum
secrets into the WireGuard PSK channel. The closest live alternative is
**`mullvad/wgephemeralpeer`** (added as a submodule in Phase 11).

| | `arnika-vq` (this PoC, default) | `mullvad/wgephemeralpeer` |
|---|---|---|
| Origin | CANCOM / EU EUROQCI / QCI-CAT | Mullvad VPN |
| Language | Go | Go |
| License | Apache-2.0 | GPL-3.0 |
| Last commit | 2026-04-07 | 2026-05-08 |
| Key sources | QKD (ETSI 014) ‖ PQC (Rosenpass file) | PQC handshake (Classic McEliece, ML-KEM-1024, Kyber1024) |
| KDF | HKDF-SHA3-256 (`submodules/arnika-vq/kdf/kdf.go:12-27`) | embedded in `mullvad-upgrade-tunnel` |
| WireGuard hook | `wgctrl` netlink, write `preshared-key` | `PostUp = mullvad-upgrade-tunnel -wg-interface %i` |
| QKD support | Yes (ETSI 014 native) | No (PQC-only) |
| Production deployment | research / PoC | live commercial VPN at Mullvad |
| Multi-hop trusted node | Yes | No (single tunnel) |

Both are architectural cousins (PSK injection) but solve different problem shapes:
arnika-vq targets **QKD + PQC hybrid for regulated infrastructure**, while
wgephemeralpeer targets **commercial consumer VPN with PQC-only PSK rotation**.
Having both available makes this PoC a credible benchmarking testbed for either
deployment mode.

