# Reference image 2 (multi-hop trusted node) → code mapping

The reference image is Fig. 3 of Spooren et al., *PQC-Enhanced QKD Networks:
A Layered Approach* ([arXiv:2604.05599](https://arxiv.org/abs/2604.05599)),
"Multi-hop setup with Alice, Bob and a trusted node in-between", in the
redistributed PDF `references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf`:
End Node Alice | Trusted Node | End Node Bob, with four numbered stages (1
Quantum Plane, 2 QKD Key IDs, 3 PQC Handshake, 4 Data Exchange). It is the
reference for the `/paper-flow` WebUI page introduced in Phase 14, and
complements image 1 (the single-tunnel `/e2e` page) with hop-wise QKD-secured
tunnels, an end-to-end PQC handshake, and a final WireGuard data tunnel. The
figure is the paper's; the arnika README's figures show a single tunnel and no
trusted node.

`/paper-flow` is a client-side simulation: `services/webui-frontend/src/lib/sim/paperSim.ts`
runs the phases, the failure cascade and the ChaCha20-Poly1305 payload in the
browser, driven by the page's buttons. The page needs no backend; the only
requests it can make come from the export toolbar (the optional copy to the
shared gallery, and the Saved-exports list).

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
| Failure layer banner ("Note: Failure injected on layer: ...") | optional bottom `<rect>` driven by `failureLayer` prop | same |

## Per-phase handshake cost

`services/webui-backend/app/paper_budgets.py::PHASE_BUDGETS` quotes the
paper's Table 1 ("Packets and Traffic per Handshake or Key Negotiation"),
`paperSim.ts` carries the client-side copy, and
`tests/test_paper_constants_agree_across_ports.py` keeps the two equal. The
phases are this repository's layout of that table: the paper numbers four
stages, (1)-(4), and never uses the word "phase"; phases 3 and 4 split its
stage (3) so that each Table 1 row is its own phase. The packet and byte
figures:

| Phase | Name | Packets | Bytes |
|---|---|---|---|
| 1 | Quantum Plane | 0 | 0 |
| 2 | Arnika QKD key_ID exchange | **2** | **78** |
| 3 | WireGuard hop handshake | **3** | **398** |
| 4 | Rosenpass PQC handshake (Classic McEliece + Kyber) | **4** | **4772** |
| 5 | Final data tunnel + Data Exchange | variable | variable |
| **Total handshake** | | **9** | **5248** |

The timing the paper states in 4.3 Fail-Safe Mechanism: WireGuard, Arnika and
Rosenpass each refresh their key every 120 s, with a 60 s grace window before
terminating a connection (WireGuard) or injecting random keys (Arnika,
Rosenpass). The model's `period_s` and `grace_s` fields live in
`PHASE_BUDGETS` and are not copied here.

## Failure cascade

The page's cascade is `CASCADE_STAGES` in `paperSim.ts`, scheduled in the
browser when a layer-failure button is pressed. Its stage list is not copied
here, so this file cannot drift from it. What it models is the paper's own run
(5 Evaluation, Test 5 -- Simulated QKD malfunction), after the first QKD
container was terminated:

| t (s) | Reported in Test 5 |
|---|---|
| 180 | Arnika fails to negotiate a QKD key and disrupts the WireGuard tunnel between end node A and trusted node 01 |
| 240 | The WireGuard hop tries a new session key and fails on the random PSK Arnika injected |
| 300 | The WireGuard hop's grace period has passed; no further PQC handshakes can be exchanged |
| 360 | Rosenpass tries a new exchange, which fails |
| 420 | Rosenpass injects random keys |
| 480 | The WireGuard data tunnel starts a new session handshake, which fails |
| 540 | The data tunnel is disrupted |

Across 100 runs the paper reports a mean of 548.42 s from terminating the QKD
simulator to the disruption of the data tunnel. Its general bound, from 4.3, is
240 s to 720 s: each component stops no earlier than 60 s and no later than
180 s after the previous layer fails.

## How to run

```bash
# Any way of serving the frontend works; a run makes no backend call.
docker compose up -d webui-frontend

# Open http://localhost:5173/paper-flow
# Move the "Trusted Nodes" slider to 1-8
# Click "Run" -> the 5-phase cycle starts; the KPI cards count up
# Click a layer button, e.g. "qkd" -> the failure cascade timeline animates
# Click "clear" to restore healthy operation
# Use the export toolbar at the top to save:
#   - PNG (topology SVG only -- pngTargetSelector="#paper-flow-topology-svg")
#   - JSON of the live state
#   - CSV of the phase history
#   - WebM or GIF animation
#   - Logs: this run's log, built from the browser state
```

## Browser verification (Phase 14 release, historical)

A dated record of what was checked when the page was introduced, while
`/paper-flow` still ran on a backend orchestrator that has since been deleted.
It is not re-run as written: the app now has fourteen routes, and the
orchestrator row describes code that no longer exists. Current checks are in
`VERIFICATION_CHECKLIST.md`.

| Check | Result |
|---|---|
| Sidebar lists 13 routes, including "Paper Data Exchange" | Yes |
| `#paper-flow-topology-svg` viewBox 1060 × 720, 160 elements | Yes |
| `#paper-flow-sequence-svg` 91 elements | Yes |
| Hop slider 1 → 8 renders 3 → 10 columns | Yes |
| `inject-failure qkd` → 7 cascade events scheduled | Yes |
| Live cycles ≥ 300 after ~1 s of the (since deleted) backend orchestrator | Yes |
| Paper KPIs show 9 packets / 5248 bytes | Yes |
| 0 console errors | Yes |
