# Third-Party Notices

This repository incorporates the following open-source software as git submodules.
Each retains its original copyright notice and license terms.

| Submodule | License | Project | Phase | Activity (verified 2026-08-20) |
|---|---|---|---|---|
| `arnika` | Apache-2.0 | [arnika-project/arnika](https://github.com/arnika-project/arnika) — prototype developed at CANCOM Converged Services GmbH under EU EUROQCI / QCI-CAT (DIGITAL-2021-QCI-01, No. 101091642) | 0–7, 9 | pinned to `9d44332` (2026-08-24), which is `main` HEAD. That commit is upstream's merge of arnika-project/arnika#42, the multi-peer `SetPSK` lookup fix reported from this project: it was carried under `nodes/alice/` as a local patch until the merge, and the patch plus the `patch(1)` step in `nodes/alice/Dockerfile` have been deleted. A `grep -q "found := false"` remains in that stage so a future bump to a revision lacking the fix fails the build rather than shipping silently. NOT post-v1.0.1: `v1.0.1` (`ef5a5c6`) lives only on the `v1.x` branch and the two have **diverged** (`main` carries 36 commits v1.0.1 lacks; v1.0.1 carries 4 that `main` lacks), so the pin does not contain what GitHub labels the latest release, and neither ref is a superset of the other. Upstream `arnika` remains preferred over the `Veriqloud/arnika-vq` fork, which has no releases or tags, is 43 commits behind, and whose only original commit adds a Dockerfile this project does not use. |
| `liboqs` | MIT (LICENSE text; GitHub auto-detector shows NOASSERTION) | Open Quantum Safe project | 0–7 | pinned to `5a1a854b`. active. Pinned to tag **0.16.0** (2026-07-09) and built from the submodule into the `pqc-validator` image. Must stay in lockstep with `liboqs-python==0.16.0`: the bindings do no version check on a library they find, so a mismatch appears as a missing ctypes symbol rather than a clear error. Bump both together. |
| `oqs-provider` | **MIT** | Open Quantum Safe project | 0–7 | pinned to `5fd81fb4`. active. Verified against `submodules/oqs-provider/LICENSE.txt`, which is the MIT text; this table previously said Apache-2.0. **The pin is not a release.** `git describe --tags` resolves it to `0.10.0-37-g5fd81fb`, a `main` commit 37 past the 0.10.0 tag. Tag `0.11.0` is **not an ancestor**: `git rev-list --left-right --count 0.11.0...HEAD` gives `2 23`, so the pin lacks two commits the 0.11.0 release carries while holding 23 it does not. The rest of this row previously reasoned as though the pin *were* 0.11.0. It is not, and the upstream compatibility note cited below is published against 0.11.0, so it has to be read with that offset in mind. **Version pairing to watch:** both `pqc-tls-demo` and `pqc-validator` build liboqs and oqs-provider from the vendored submodules, and upstream documents oqs-provider 0.11.0 against **liboqs 0.15.0** while this repository pins liboqs **0.16.0**. That span includes the removal of SPHINCS+ and a rename in which `KEM_frodokem_*` came to mean the salted variant -- the same identifier for a different algorithm. `sphincs` appears nowhere outside the submodules, but **`frodo` does**: `services/pqc-tls-demo/Dockerfile.oqs-provider` puts `frodo640aes` in `TLS_GROUPS` and passes it to `openssl s_server -groups`. This row previously read "Neither is used here ... so the skew is currently harmless", and that conclusion rested on a false premise -- the FrodoKEM rename is exactly the part of the skew that could bite. The blast radius is small but not zero: no compose service builds that image, so it is reached only by `make pqc-tls-demo-both`. Anyone running that target should confirm which FrodoKEM variant the pinned pair agrees on. |
| `rosenpass` | MIT / Apache-2.0 (dual) | Rosenpass project contributors | 0–7 | pinned to `512fe426`. pinned submodule **v0.2.3** (2026-08-03); real PQ key exchange in `nodes/alice`. Re-auditing this row: `git submodule status` prints `(v0.2.2-43-g512fe426)`, a 2024 tag, because it runs `git describe` without `--tags` and v0.2.3 is a *lightweight* tag where v0.2.2 was annotated. The pin is v0.2.3 -- confirm with `git -C submodules/rosenpass describe --tags --exact-match`, not with `git submodule status`. Requires Rust >= 1.85 because a dependency (`clap_lex` 1.1.0) declares edition 2024, so `nodes/alice/Dockerfile` pins `rust:1.90` -- bump the two together. |
| `SimQN` | GPLv3 | independent (Cui et al.) | 8 | pinned to `29a94689` (2026-05-25); upstream released v0.2.3 on 2026-06-09 and the pin trails `master`. |
| `SeQUeNCe` | custom Argonne "OPEN SOURCE LICENSE" (BSD-3-Clause-equivalent terms; GitHub shows NOASSERTION) — commercial use permitted with attribution | Argonne National Laboratory | 8 | pinned to `ffd7c837`, the tag **v1.0.0** (2026-06-17). Bumped from `d135e9f8`, which was v0.8.5 plus 10 commits and 276 behind master while this row claimed the release outright. The bump is behaviour-neutral for the `sequence` backend, and the reason is worth recording: that backend read `Noise().depolarizing_rate`, an attribute absent from both versions, so it silently used a fallback. See `tests/test_sequence_backend_actually_uses_sequence.py`. |
| `qkdnetsim` | GPL v2 | QKDNetSim project (Mehic et al.) | 8 | pinned to `1cda34cb` (2026-05-03), which is upstream HEAD; the project publishes no releases or tags. No upstream commits since, so "active" here means current rather than moving. |
| `openQKDsecurity` | MIT | Lütkenhaus group / U. Waterloo | 8 (offline) | pinned to `f952c355`. active; pinned submodule **v2.2.0** (2026-06-17). This row previously claimed the pin was "3 commits ahead of v2.2.0, so it already includes that release" -- the comparison was inverted. `git describe` read `v2.1.0-2-g6ffeed8`, i.e. 3 commits BEHIND, and v2.2.0 was not an ancestor. Bumped, and `tests/test_notices_match_the_pins.py` now checks every row: the backticked pin against `git ls-tree HEAD` (the index, which is correct even for the submodules not checked out), and a bolded tag against `git ls-remote --tags`. It deliberately does NOT use `git submodule status`, which reports the working tree. |
| `strawberryfields` | Apache-2.0 | Xanadu | 8 | pinned to `162125d8`. **ARCHIVED on GitHub** (read-only; last push 2026-01-16) and the Xanadu cloud is decommissioned. Local simulation still runs and backs the `cvqkd` backend. |
| `tno-qkd-key-rate` | Apache-2.0 | TNO (Netherlands Org. for Applied Scientific Research) | 8 | pinned to `4cac9df0`. pinned submodule **v2.0.4**, 2026-02 (active); `tno` backend + key-rate cross-check |
| `strongswan` | **GPL-2.0-or-later** (+ OpenSSL/LGPL linking exception; blowfish/des/md4/md5 plugins differ) | strongSwan project | 9 | pinned to `5973ff8e`, the annotated tag **6.0.7** (tagged 2026-06-07, released 2026-06-08). The date previously given here, 2026-05-28, matched neither the tag nor the release. |
| `PQClean` | per-algorithm (mostly Public Domain / MIT) | PQClean consortium | 8 | pinned to `202a8f96`. **ARCHIVED on GitHub** (read-only; last push 2026-08-04). Previously listed here as "active", which was wrong. Reference implementations only; nothing is built from it today. |
| `qkd-pqc-paper-supplementary` | **NONE — no licence file of any kind** | aparcar / Spooren et al. | 9 | pinned to `712e4b36`. Reference only: not redistributed, not built into any image, and not to be vendored into a derived work without the authors' permission. Absent from this table until now, which is the omission that matters most here. |
| `cryptography` (PyPI) | Apache-2.0 / BSD-3-Clause dual | Python Cryptographic Authority | 10 | v44.0.0. Was used by the deleted `e2e_orchestrator`; the shipped HKDF-SHA3-256 and ChaCha20-Poly1305 now run in the browser via `@noble/hashes` and `@noble/ciphers` (rows below). Retained for other backend uses. |
| `wgephemeralpeer` | GPL-3.0 | Mullvad VPN | 11 | pinned to `0080bf8d` (2026-05-08); latest release is v1.0.6 (2025-02-03) and upstream has moved on since the pin. Alternative PSK-injection (benchmark reference, no live integration). |
| `html-to-image` (npm) | MIT | bubkoo et al. | 12 | v1.11.13; capture DOM to PNG for ExportToolbar PNG / Animation |
| `modern-gif` (npm) | MIT | qq15725 | 12 | v2.1.0 (2026-04-16); encodes animated GIF exports in a worker. Replaced `gifshot`, which had not been released since 2017-12-18. |
| `@noble/post-quantum` (npm) | MIT | Paul Miller | 12 | v0.7.0 (2026-08-09); in-browser ML-KEM / ML-DSA for the client-side PQC validator. Self-audited; makes no constant-time claim. |
| `@noble/hashes` (npm) | MIT | Paul Miller | 12 | v2.2.0; SHA-3 and HKDF. This is the package that actually performs the HKDF-SHA3-256 the README headlines for the client-side lane. |
| `@noble/ciphers` (npm) | MIT | Paul Miller | 12 | v2.2.0; ChaCha20-Poly1305 for the in-browser AEAD. |
| `react` / `react-dom` (npm) | MIT | Meta and contributors | 12 | v18.3.1; WebUI runtime. |
| `react-router-dom` (npm) | MIT | Remix / React Training | 12 | v6.28.0; client-side routing for the 13 pages. |
| `plotly.js-dist-min` (npm) | MIT | Plotly | 12 | v2.35.3; charting. Note the *library* is MIT; Plotly's commercial offerings are separate and not used. |
| `react-plotly.js` (npm) | MIT | Plotly | 12 | v2.6.0; React bindings for the above. |
| `d3-force` (npm) | ISC | Mike Bostock | 12 | v3.0.0; force-directed layout for the topology graph. |
| `vite` (npm) | MIT | Evan You and contributors | 12 | v6.0.3; build tool (dev dependency, not shipped in the bundle). |
| `typescript` (npm) | Apache-2.0 | Microsoft | 12 | v5.7.2; type checker (dev dependency, not shipped in the bundle). |
| `qkd_kme_server` | MIT (`LICENSE`: "MIT License, Copyright (c) 2025 Thomas Prévost") | Thomas Prévost (`thomasarmel`) | 14 | pinned to `4d53a3dc` (2026-04-01), which is upstream HEAD. There have been no upstream commits since, so this is current rather than actively developed; the row previously read "active", and the licence column read "(see repo LICENSE)" without saying what it was. Rust ETSI GS QKD 014 v1.1.1 KME — third reference implementation alongside Python `bb84-kme` + NS-3 `qkdnetsim-kme` |
| `pq-wireguard` (Kudelski Security) | — | — | rejected | **archived 2024-09-03** ("not actively maintained anymore"); kept only as historical reference, NOT integrated |
| `qkd-kem-provider` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2025-06; oqs-provider fork hybridising PQ KEMs with QKD — listed for the crypto-agility roadmap |
| `qkd-etsi-api-c-wrapper` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2024-11; C wrapper for ETSI 004/014 — listed for the crypto-agility roadmap |

## License compatibility considerations

- **SimQN (GPLv3)** is used as a Python-importable library inside `services/bb84-kme`.
  Per the standard library-vs-binary distinction we treat this service as a GPLv3
  sub-component of the otherwise Apache-2.0 repository; the GPL only extends to
  derivative works of SimQN itself.
- **qkdnetsim (GPL v2)** is vendored as a submodule and its source is
  unmodified. This entry previously said it "runs in an isolated Docker
  container (`services/qkdnetsim-kme/`) ... we only invoke its binaries over
  the network". That service is `kme_facade.py`, a Flask app of our own; no
  qkdnetsim binary is invoked by anything in this repository. The conclusion --
  no GPL obligation on the calling code -- still holds, and now for a simpler
  reason: nothing links to it or executes it at all. Restore the
  invoke-over-the-network argument if the real NS-3 KMS is ever wired in.
- **openQKDsecurity (MIT)** is *not* shipped in the runtime image, and is not
  currently used to produce anything. This entry previously read "We use it
  off-line to pre-compute `config/qkd_keyrate_table.json`; the resulting table
  is data, not derivative MATLAB code, and may be redistributed freely." The
  conclusion happens to be right and the premise is wrong, which is worse than
  either alone: that table's own `provenance` field names
  `tools/precompute_keyrate_table_fallback.py`, its `formulas` field names only
  Lo-Ma-Chen and arXiv:2511.21253, and `tools/precompute_keyrate_table.m` has
  never existed in this repository. No MATLAB ran, so there was no
  derivative-work question to answer. The submodule is vendored for the
  roadmap; if it is ever used to generate a shipped artefact, restore the
  data-not-code argument then, on a real premise.
- **Strawberry Fields (Apache-2.0)** and **PQClean (per-file MIT / Public
  Domain)** are fully compatible with this repository's Apache-2.0 baseline.
- **strongSwan (GPL-2.0-or-later, with an OpenSSL/LGPL linking exception)** runs
  in a dedicated Docker container built from `nodes/strongswan/`.
  Its source is unmodified and we invoke its binaries over the network; our
  wrapper `entrypoint.sh` and the Go VICI key-writer in
  `services/arnika-vici/` are our own work and
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
- **rosenpass (MIT / Apache-2.0 dual)** is a pinned submodule (**v0.2.3**) built
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
fine), which avoids **invoking** the GPL-3.0 SimQN and the custom-Argonne
SeQUeNCe. Note the word: this reads "avoids shipping" no longer, because
`SIMULATOR_BACKEND` is a runtime variable and cannot un-ship a baked layer.
`services/bb84-kme/Dockerfile` line 40 `pip install -e /opt/SimQN` regardless of
backend, so the image you hand over contains GPL-3.0 code whichever backend it
is configured to run. To actually avoid shipping it, build without that line.
The privileged WireGuard nodes link strongSwan only when the optional IPsec
profile is enabled; the default WireGuard+arnika+rosenpass path does not.

For the exact license text of each submodule, see the `LICENSE` file inside the
respective `submodules/<name>/` directory.
