# Third-Party Notices

This repository incorporates the following open-source software as git submodules.
Each retains its original copyright notice and license terms.

| Submodule | License | Project | Phase | Activity (May 2026) |
|---|---|---|---|---|
| `arnika-vq` | Apache-2.0 | CANCOM Converged Services GmbH | 0–7 | EU EUROQCI/QCI-CAT |
| `liboqs` | MIT (LICENSE text; GitHub auto-detector shows NOASSERTION) | Open Quantum Safe project | 0–7 | active |
| `oqs-provider` | Apache-2.0 | Open Quantum Safe project | 0–7 | active |
| `rosenpass` | MIT / Apache-2.0 (dual) | Rosenpass project contributors | 0–7 | pinned submodule **v0.2.2**; real PQ key exchange in `nodes/alice` |
| `SimQN` | GPLv3 | independent (Cui et al.) | 8 | 2026-05-25 (active) |
| `SeQUeNCe` | custom Argonne "OPEN SOURCE LICENSE" (BSD-3-Clause-equivalent terms; GitHub shows NOASSERTION) — commercial use permitted with attribution | Argonne National Laboratory | 8 | v0.8.5, 2026-05-12 (active) |
| `qkdnetsim` | GPL v2 | QKDNetSim project (Mehic et al.) | 8 | 2026-05-03 (active) |
| `openQKDsecurity` | MIT | Lütkenhaus group / U. Waterloo | 8 (offline) | 2025-08 |
| `strawberryfields` | Apache-2.0 | Xanadu | 8 | 2026-01 (cloud decommissioned) |
| `tno-qkd-key-rate` | Apache-2.0 | TNO (Netherlands Org. for Applied Scientific Research) | 8 | pinned submodule **v2.0.4**, 2026-02 (active); `tno` backend + key-rate cross-check |
| `strongswan` | **GPL-2.0-or-later** (+ OpenSSL/LGPL linking exception; blowfish/des/md4/md5 plugins differ) | strongSwan project | 9 | 2026-05-28 (active) |
| `qkd-pqc-paper-supplementary` | **NO license** — reference-only, optional, not redistributed | aparcar / Spooren et al. | 9 | 2026-02-16 |
| `PQClean` | per-algorithm (mostly Public Domain / MIT) | PQClean consortium | 8 | 2026-05-14 (active) |
| `cryptography` (PyPI) | Apache-2.0 / BSD-3-Clause dual | Python Cryptographic Authority | 10 | v44.0.0; used by `e2e_orchestrator` for HKDF-SHA3 + ChaCha20-Poly1305 |
| `wgephemeralpeer` | GPL-3.0 | Mullvad VPN | 11 | 2026-05-08 (active); alternative PSK-injection (benchmark reference, no live integration) |
| `html-to-image` (npm) | MIT | bubkoo et al. | 12 | v1.11.13; capture DOM to PNG for ExportToolbar 🖼 PNG / 🎞 Animation |
| `gifshot` (npm) | MIT | Yahoo Inc. | 12 | v0.4.5; stitches frames into animated GIF for ExportToolbar 🎞 Animation |
| `qkd_kme_server` | (see repo LICENSE) | Thomas Prévost (`thomasarmel`) | 14 | **2026-04-01 active**; Rust ETSI GS QKD 014 v1.1.1 KME — third reference implementation alongside Python `bb84-kme` + NS-3 `qkdnetsim-kme` |
| `pq-wireguard` (Kudelski Security) | — | — | rejected | **archived 2024-09-03** ("not actively maintained anymore"); kept only as historical reference, NOT integrated |
| `qkd-kem-provider` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2025-06; oqs-provider fork hybridising PQ KEMs with QKD — listed for the crypto-agility roadmap |
| `qkd-etsi-api-c-wrapper` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2024-11; C wrapper for ETSI 004/014 — listed for the crypto-agility roadmap |

## License compatibility considerations

- **SimQN (GPLv3)** is used as a Python-importable library inside `services/bb84-kme`.
  Per the standard library-vs-binary distinction we treat this service as a GPLv3
  sub-component of the otherwise Apache-2.0 repository; the GPL only extends to
  derivative works of SimQN itself.
- **qkdnetsim (GPL v2)** runs in an isolated Docker container
  (`services/qkdnetsim-kme/`). Its source is unmodified; we only invoke its
  binaries over the network. This is the standard pattern that does not impose
  GPL obligations on the calling code.
- **openQKDsecurity (MIT)** is *not* shipped in the runtime image. We use it
  off-line to pre-compute `config/qkd_keyrate_table.json`; the resulting table is
  data, not derivative MATLAB code, and may be redistributed freely.
- **Strawberry Fields (Apache-2.0)** and **PQClean (per-file MIT / Public
  Domain)** are fully compatible with this repository's Apache-2.0 baseline.
- **strongSwan (GPL-2.0-or-later, with an OpenSSL/LGPL linking exception)** runs
  in a dedicated Docker container (`services/strongswan` / `nodes/strongswan/`).
  Its source is unmodified and we invoke its binaries over the network; our
  wrapper scripts (`entrypoint.sh`, `arnika-vici-bridge.sh`) are shell glue and
  remain Apache-2.0 under this repository's baseline. End users who *redistribute*
  the container must comply with the GPL-2.0 source-offer obligation for the
  strongSwan binaries (the special exception permits combining with OpenSSL and
  LGPL libraries).
- **SeQUeNCe (custom Argonne "OPEN SOURCE LICENSE")** uses a non-standard header
  ("Copyright © 2026 UChicago Argonne, LLC / All Rights Reserved / OPEN SOURCE
  LICENSE"); GitHub's auto-detector therefore returns `NOASSERTION`. Reading the
  actual text, its operative terms are **BSD-3-Clause-equivalent** (retain
  notice / reproduce in binary / no-endorsement) plus the BSD disclaimer, which
  **permits commercial use with attribution**. It is imported as a Python
  library by `services/bb84-kme` (the `sequence` backend); the no-endorsement
  clause only forbids marketing a derived product *as endorsed by* Argonne.
- **rosenpass (MIT / Apache-2.0 dual)** is a pinned submodule (**v0.2.2**) built
  from source into the `nodes/alice` image; it performs the real post-quantum
  key exchange whose OSK is HKDF-combined with the QKD key by arnika. Both
  licenses are permissive and fully compatible with the Apache-2.0 baseline.
- **qkd-pqc-paper-supplementary** contains experimental data only (CSV traces,
  pcap captures) and ships with **no license** (all-rights-reserved upstream).
  It is **reference-only and optional**: a git submodule stores only a commit
  pointer, so this repository never redistributes its files, and **no build or
  shipped image depends on it**. It is read (when present) via
  `tools/compare_to_paper.py` purely as input data for paper comparison.

## SaaS vs. distribution

None of the bundled components are **AGPL**. Consequently, **operating the WebUI
as a hosted/SaaS service triggers no copyleft source-disclosure obligation** —
GPL/LGPL duties attach only when you *distribute* the binaries or container
images to a third party. For client/PoC *delivery* (where images change hands),
prefer the fully-permissive physics backend profile
(`SIMULATOR_BACKEND=cvqkd`, Strawberry Fields, Apache-2.0; QuTiP/BSD-3 is also
fine), which avoids shipping the GPL-3.0 SimQN and the custom-Argonne SeQUeNCe.
The privileged WireGuard nodes link strongSwan only when the optional IPsec
profile is enabled; the default WireGuard+arnika+rosenpass path does not.

For the exact license text of each submodule, see the `LICENSE` file inside the
respective `submodules/<name>/` directory.
