# Reference image 2 (multi-hop trusted node) → code mapping

The user-supplied multi-hop diagram from
`Veriqloud/arnika-vq` (End Node Alice | Trusted Node | End Node Bob with
four numbered phases) is the canonical reference for the `/paper-flow`
WebUI page introduced in Phase 14. It complements image 1 (the
single-tunnel `/e2e` page) by adding hop-wise QKD-secured tunnels, an
end-to-end PQC handshake, and a final WireGuard data tunnel.

## Element-by-element mapping

| Image element | Code | File / line |
|---|---|---|
| Three vertical columns (Alice / Trusted Node / Bob) | dashed-rect background per column | `services/webui-frontend/src/components/MultiHopTopologySvg.tsx` |
| Configurable trusted-node count (1-8) | `hopCount` prop + `<input type="range">` on the page | `services/webui-frontend/src/pages/PaperDataExchange.tsx::configHopCount` |
| `QKD Device` box (top of every column) | `<rect>` 70..120 + glow on Phase 1 | `MultiHopTopologySvg.tsx` |
| `KMS Keystore (ETSI014)` box | `<rect>` 140..200 + glow on Phase 2 | same |
| `Arnika` box (orange) | `<rect>` 230..280 + glow on Phase 2 | same |
| `VPN WireGuard` box (purple) per column | `<rect>` 320..370 + glow on Phase 3/4 | same |
| `PQC Rosenpass` (end-node columns only) | conditional `<rect>` 410..460 + glow on Phase 3 | same |
| `Final WG tunnel + ChaCha20-Poly1305` (end-node columns) | `<rect>` 490..540 + glow on Phase 4/5 | same |
| `DATA IPv4 / IPv6` box (end-node columns) | `<rect>` 570..610 | same |
| ① Quantum Plane (purple dashed arrows across QKD Devices) | inter-column `<line>` at y=95 | same |
| ② QKD Key IDs (orange dashed arrows across Arnika) | inter-column `<line>` at y=255 | same |
| ③ PQC Handshake (pink arc across end-node Rosenpass) | `<path>` from Alice Rosenpass to Bob Rosenpass | same |
| ④ Data Exchange (red horizontal line across final WG tunnels) | `<line>` at y=515 | same |
| Numbered phase markers ① ② ③ ④ | top-left dial pad of 4 circles, active phase glows | same |
| Failure layer banner ("⚠ Failure injected on layer: ...") | optional bottom `<rect>` driven by `failureLayer` prop | same |

## Per-phase backend semantics

`services/webui-backend/app/paper_flow.py::PHASE_BUDGETS` quotes the paper:

| Phase | Name | Packets | Bytes | Period | Grace |
|---|---|---|---|---|---|
| 1 | Quantum Plane | 0 | 0 | — | 0 s |
| 2 | Arnika QKD key_ID exchange | **2** | **78** | 120 s | 180 s |
| 3 | WireGuard hop handshake | **3** | **398** | 120 s | 60 s |
| 4 | Rosenpass PQC handshake (Classic McEliece + Kyber) | **4** | **4772** | 120 s | 180 s |
| 5 | Final data tunnel + Data Exchange | variable | variable | 120 s | 60 s |
| **Total handshake** | | **9** | **5248** | | |

## 7-stage failure cascade (`CASCADE_STAGES`)

Triggered by `POST /api/paper-flow/inject-failure {layer}`:

| t (s) | Layer | Description |
|---|---|---|
| 0 | qkd | QKD plane outage injected |
| 180 | arnika | Arnika fails over to random key |
| 240 | wireguard | WireGuard hop tunnel grace expires |
| 360 | rosenpass | Rosenpass handshake blocked |
| 420 | rosenpass | Rosenpass falls over to random PSK |
| 540 | data | Final data tunnel handshake fails (early cascade) |
| 720 | data | Full data-path interruption (worst case) |

## How to run

```bash
# Backend (already wired into webui-backend lifespan)
docker compose up -d webui-backend webui-frontend

# Open http://localhost:5173/paper-flow
# Move the "Trusted Nodes" slider to 1-8
# Click "▶ Run" → 5-phase cycle starts; KPI cards count up
# Click "qkd" failure → 7-stage cascade timeline animates
# Click "clear" to restore healthy operation
# Use the export toolbar at the top to save:
#   - PNG (Topology SVG only — pngTargetSelector="#paper-flow-topology-svg")
#   - JSON of the live state
#   - CSV of the phase history
#   - GIF animation
#   - Logs (webui-backend.log)
```

## Browser verification (Phase 14 release)

| Check | Result |
|---|---|
| Sidebar has 12 entries incl. "Paper Data Exchange ◆" | ✓ |
| `#paper-flow-topology-svg` viewBox 1060 × 720, 160 elements | ✓ |
| `#paper-flow-sequence-svg` 91 elements | ✓ |
| Hop slider 1 → 8 renders 3 → 10 columns | ✓ |
| `inject-failure qkd` → 7 cascade events scheduled | ✓ |
| Live cycles ≥ 300 after ~1 s of orchestrator | ✓ |
| Paper KPIs show 9 packets / 5248 bytes | ✓ |
| 0 console errors | ✓ |
