# Third-Party Notices

This repository incorporates the following open-source software: its git
submodules first, then the packages and images its services and WebUI are
built from. Each retains its original copyright notice and licence terms. Rows
are kept short; the longer history of a pin is under
[Notes per dependency](#notes-per-dependency).

| Submodule | License | Project | Phase | Activity (verified 2026-09-25) |
|---|---|---|---|---|
| `arnika` | Apache-2.0 | [arnika-project/arnika](https://github.com/arnika-project/arnika) — initial prototype and v1.x developed at CANCOM Converged Services GmbH under EU EUROQCI / QCI-CAT (DIGITAL-2021-QCI-01, No. 101091642, co-funded by Austria's National Foundation for Research, Technology and Development; the project ran from 2023-01-01 to 2026-03-31); maintained at XBC Digital GmbH since Q2 2026 | 0–7, 9 | pinned to `f4cf9ba` (2026-09-24), the head of the **open, unmerged** PR #51 (`pqc-hpke`), not a `main` commit: post-v1.x work, not the `v1.x` branch. It contains all of `main` except its two newest commits, which touch only the README (`164ee4e`, and `3a8cc13`, the previous pin). To be re-pinned to the merge commit once #51 merges. Three fixes reported from this project are in it (#42, #44, #49). Checked 2026-09-26. See [arnika](#arnika). |
| `liboqs` | MIT (LICENSE text; GitHub auto-detector shows NOASSERTION) | Open Quantum Safe project | 0–7 | pinned to `5a1a854b`, the tag **0.16.0** (2026-07-09), built into the `pqc-validator` and `pqc-tls-demo` images. It is not the liboqs in the Rosenpass exchange (see `oqs-sys` below), and arnika uses none. Inside the affected range of GHSA-wh5q-mpc8-67wf, whose code is not compiled here. See [liboqs](#liboqs). |
| `oqs-provider` | **MIT** | Open Quantum Safe project | 0–7 | pinned to `5fd81fb4`, a `main` commit 37 past the 0.10.0 tag, not a release. 22 commits behind 0.12.0-rc2 and missing four memory-safety fixes made there; reached only through `make pqc-tls-demo-both`. See [oqs-provider](#oqs-provider). |
| `rosenpass` | MIT / Apache-2.0 (dual) | Rosenpass project contributors | 0–7 | pinned to `512fe426`, the tag **v0.2.3** (2026-08-03); built from source into the `node-alice` image, where it performs the real post-quantum key exchange that keys the `wg1` data tunnel (since 2026-09-26; it no longer feeds arnika). Its KEM code is liboqs 0.8.0, statically linked through `oqs-sys` 0.8.0, not the liboqs pin. See [rosenpass](#rosenpass). |
| `SimQN` | GPL-3.0 (upstream: "GPLv3") | QNLab, USTC (Cui et al.) | 8 | pinned to `29a94689`, the tag **v0.2.3**, the latest release. `main` is 42 commits ahead, with changes to modules this project does not import. The installed distribution reports version 0.2.1, from upstream's own `setup.py`. Imported in-process by `bb84-kme`; see the licence notes below. |
| `SeQUeNCe` | custom Argonne "OPEN SOURCE LICENSE" (BSD-3-Clause-equivalent terms; GitHub shows NOASSERTION) — commercial use permitted with attribution | Argonne National Laboratory | 8 | pinned to `ffd7c837`, the tag **v1.0.0** (2026-06-17). v1.2.0 is out (`344c3997`, 2026-09-12, 64 commits past the pin) and deferred to its own change. Brings the LGPL `gmpy2` into the `bb84-kme` process. See [SeQUeNCe](#sequence). |
| `qkdnetsim` | GPL-2.0-only (SPDX headers; `LICENSE` is the GPL v2 text) | QKDNetSim project (Mehic et al.) | 8 | pinned to `1cda34cb` (2026-05-03), 4 commits behind `v3.1.4` (`e6330fe6`, 2026-09-21). Not bumped: no qkdnetsim binary is executed here. Compiled together with ns-3 (below) by `services/qkdnetsim-kme/Dockerfile`. See [qkdnetsim](#qkdnetsim). |
| `openQKDsecurity` | MIT | Lütkenhaus group / U. Waterloo | 8 (offline) | pinned to `f952c355`, the tag **v2.2.0** (2026-06-17). Vendored for the roadmap; nothing shipped is produced from it. |
| `strawberryfields` | Apache-2.0 | Xanadu | 8 | pinned to `162125d8`, the final `master` commit, 8 commits past the last tag `v0.23.0-post1`. **Archived on GitHub** (read-only; last push 2026-01-16) and the Xanadu cloud is decommissioned. Local simulation still runs and backs the `cvqkd` backend. |
| `tno-qkd-key-rate` | Apache-2.0 | TNO (Netherlands Org. for Applied Scientific Research) | 8 | pinned to `4cac9df0`, the tag **v2.0.4** (2026-02); `tno` backend and key-rate cross-check. |
| `strongswan` | **GPL-2.0-or-later** (+ OpenSSL/LGPL linking exception; des/md4/md5 plugins differ) | strongSwan project | 9 | pinned to `b43f6bfe`, the annotated tag **6.1.0** (tagged 2026-09-06, released 2026-09-07), moved up from 6.0.7 for [`50177b40`](https://github.com/strongswan/strongswan/commit/50177b4004d1fec4299cd7bed4a3c7fb0f4208d7), which enforces `ppk_required` on the initiator (see [`vici-ppk.md`](vici-ppk.md)). 6.1.0 is also this lane's **security floor**: it fixes CVE-2026-78133 (6.0.0 and later, reachable here because the lane accepts multiple key exchanges) and CVE-2026-78127 (4.1.2 and later). Built into the `alice-ipsec` / `bob-ipsec` image only. See [strongswan](#strongswan). |
| `qkd-pqc-paper-supplementary` | **NONE — no licence file of any kind** | aparcar / Spooren et al. | 9 | pinned to `712e4b36`. Reference only: not redistributed, not built into any image, and not to be vendored into a derived work without the authors' permission. |
| `wgephemeralpeer` | GPL-3.0 | Mullvad VPN | 11 | pinned to `0080bf8d` (2026-05-08), 45 commits past the latest release v1.0.6 (2025-02-03), which is an ancestor of the pin rather than a newer release. Vendored as a benchmark reference; not built or integrated. |
| `qkd_kme_server` | MIT (`LICENSE`: "MIT License, Copyright (c) 2025 Thomas Prévost") | Thomas Prévost (`thomasarmel`) | 14 | pinned to `4d53a3dc` (2026-04-01), upstream HEAD, 80 commits past its only tag, the pre-release `v0.0.1-alpha`. No upstream commits since, so current rather than actively developed. Rust ETSI GS QKD 014 v1.1.1 KME, **vendored for reference and not built**: no Dockerfile, compose file or Makefile target compiles or runs it (checked 2026-09-25). |
| `oqs-sys` (crate) | MIT OR Apache-2.0; the liboqs 0.8.0 it bundles is MIT with per-component terms (see [rosenpass](#rosenpass)) | Open Quantum Safe project | 0–7 | 0.8.0, from Rosenpass's `Cargo.lock`. Vendors liboqs **0.8.0** (2023) and compiles it statically into `rosenpass` in the `node-alice` image; that image redistributes it. |
| `govici` (Go module) | MIT | strongSwan project | 9 | v0.8.2 (the latest, 2026-02-27), the official VICI client; compiled into the `arnika` binary of the strongSwan node image by `services/arnika-vici/build.sh`. |
| arnika's Go dependencies | BSD-3-Clause, MIT or Apache-2.0, per module | various | 0–7, 9 | every `arnika` binary statically links the modules it imports from `submodules/arnika/go.mod`: `golang.org/x/*`, `wgctrl` and `wireguard`, `google/uuid`, `mdlayher/*`, `containernetworking/plugins`, and `josharian/native` (MIT), which `mdlayher/netlink` imports and so comes with it. Most of these are `// indirect` in that `go.mod`, reached through its five direct requirements (`containernetworking/plugins`, `google/uuid`, `golang.org/x/crypto`, `golang.org/x/sys` and `wgctrl`); `golang.org/x/sys` became direct with #51, at the same v0.45.0, for its process hardening. The PQC-HPKE key agreement adds no module: it is the Go standard library's `crypto/hpke` and `crypto/mlkem` (BSD-3-Clause, like the rest of the standard library every Go binary links). |
| `ns-3` (ns-3-dev, tag `ns-3.46`) | GPL-2.0-only | nsnam | 8 | not vendored: cloned at build time by `services/qkdnetsim-kme/Dockerfile` and compiled with qkdnetsim; the build output ships in the image that carries it and is never executed here. See [qkdnetsim](#qkdnetsim). |
| `gmpy2` (PyPI) | **LGPL-3.0-or-later** | gmpy2 developers; GMP, MPFR and MPC projects | 8 | 2.3.1 in the `bb84-kme` image, required by SeQUeNCe and imported into the service process. Its wheel bundles GMP (LGPL-3.0-or-later or GPL-2.0-or-later), MPFR and MPC (both LGPL-3.0-or-later) as shared objects. |
| `certifi`, `tqdm`, `fqdn` (PyPI) | MPL-2.0 (`tqdm`: MPL-2.0 AND MIT) | respective authors | 0–12 | certifi 2026.7.22 in `bb84-kme` and `webui-backend`; tqdm 4.70.1 and fqdn 1.5.1 in `bb84-kme`. Transitive and unmodified. |
| `caddy` (container image) | Apache-2.0 | Caddy project | deploy | `caddy:2-alpine`, pulled at deploy time by `deploy/docker-compose.cloud.yml` as the public TLS front end; not built or redistributed by this repository. A check on 2026-09-25 found it negotiating the hybrid TLS group X25519MLKEM768. |
| `fastapi` (PyPI) | MIT | Sebastián Ramírez and contributors | 0–12 | v0.141.1 in `bb84-kme`, `pqc-validator` and `webui-backend`. Moved from 0.115.6 on 2026-09-25 because that release capped Starlette below 0.42 (next row). |
| `starlette` (PyPI) | BSD-3-Clause | Encode OSS and contributors | 0–12 | v1.7.0, pinned next to fastapi in all three services. 0.41.3 carried seven published advisories on 2026-09-25, three HIGH, one of them an O(n^2) Range-header DoS in `FileResponse` that the public demo exposed through `/api/exports/download`. |
| `liboqs-python` (PyPI) | MIT | Open Quantum Safe project | 0–7 | v0.16.0.1; see the `liboqs` row for the version coupling. |
| `html-to-image` (npm) | MIT | bubkoo et al. | 12 | v1.11.13; capture DOM to PNG for ExportToolbar PNG / Animation |
| `modern-gif` (npm) | MIT | qq15725 | 12 | v2.1.0 (2026-04-16); encodes animated GIF exports in a worker. Replaced `gifshot`, which had not been released since 2017-12-18. |
| `@noble/post-quantum` (npm) | MIT | Paul Miller | 12 | v0.7.1 (2026-08-27; enforces the digest lengths that pre-hash XOF OIDs promise and hardens WebCrypto input validation); in-browser ML-KEM, ML-DSA and SLH-DSA for the client-side PQC validator. Self-audited; makes no constant-time claim. |
| `@noble/hashes` (npm) | MIT | Paul Miller | 12 | v2.4.0; SHA-3 and HKDF. This is the package that actually performs the HKDF-SHA3-256 the README headlines for the client-side lane. |
| `@noble/ciphers` (npm) | MIT | Paul Miller | 12 | v2.4.0; ChaCha20-Poly1305 for the in-browser AEAD. |
| `react` / `react-dom` (npm) | MIT | Meta and contributors | 12 | v18.3.1; WebUI runtime. |
| `react-router-dom` (npm) | MIT | Remix Software Inc. | 12 | v7.18.4, with the `react-router` 7.18.4 (MIT) it re-exports; client-side routing in declarative mode (`<BrowserRouter>` in `main.tsx`). 7.18.0 fixed two moderate advisories that no 6.x release fixes: GHSA-wrjc-x8rr-h8h6, an open redirect through a backslash in a path passed to `<Link>` or `useNavigate` (`react-router` >= 6.0.0, < 7.18.0; a bypass of the earlier CVE-2025-68470 fix), and GHSA-337j-9hxr-rhxg, constructor injection through `deserializeErrors()` during SSR hydration (>= 6.4.0, < 7.18.0; framework and data modes only). Neither was reachable here: every navigation target is a string literal (the `nav` list in `App.tsx` and five `<Link to="...">` constants), nothing calls `useNavigate`, and there is no SSR. The upgrade retires both rather than relying on that reading. The older open-redirect advisories GHSA-jjmj-jmhj-qwj2 and GHSA-2j2x-hqr9-3h42 are fixed in earlier 7.x releases too. |
| `plotly.js` (npm) | MIT | Plotly | 12 | v4.1.1; charting. **This row named `plotly.js-dist-min` 2.35.3 until 2026-09-25, which the site never shipped**: nothing imported it, and `react-plotly.js` loads `plotly.js/dist/plotly`, so npm resolved the undeclared peer to plotly.js 3.5.1 -- whose bundle embedded maplibre-gl 4.7.1 (GHSA-jrc7-96c5-q579, CRITICAL, fixed 6.4.1). plotly.js is now declared directly and the unused package removed; 4.1.1 bundles maplibre-gl 6.9.0 (BSD-3-Clause). **4.0.0 turned on a "send to cloud" modebar button by default** that uploads chart data to cloud.plotly.com; every chart here passes `PLOT_CONFIG` (`src/lib/plotConfig.ts`), which turns it off, and a test fails if one does not. The *library* is MIT; Plotly's commercial offerings are separate and not used. |
| `react-plotly.js` (npm) | MIT | Plotly | 12 | v4.1.0; React bindings for the above, with its own TypeScript types (the local `declare module` stub was removed). |
| `d3-force` (npm) | ISC | Mike Bostock | 12 | v3.0.0; force-directed layout for the topology graph. |
| `vite` (npm) | MIT | Evan You and contributors | 12 | v6.4.3; build tool (dev dependency, not shipped in the bundle). |
| `typescript` (npm) | Apache-2.0 | Microsoft | 12 | v5.9.3; type checker (dev dependency, not shipped in the bundle). |
| `pq-wireguard` (Kudelski Security) | — | — | rejected | **archived 2024-09-03** ("not actively maintained anymore"); kept only as historical reference, NOT integrated |
| `qkd-kem-provider` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2025-06; oqs-provider fork hybridising PQ KEMs with QKD — listed for the crypto-agility roadmap |
| `qkd-etsi-api-c-wrapper` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2024-11; C wrapper for ETSI 004/014 — listed for the crypto-agility roadmap |

**PQClean was a submodule until 2026-09-25 and has been removed.** Upstream
archived the repository, nothing in this repository built from it, and no
compose file mounted it.

## Notes per dependency

### arnika

**Three fixes reported from this project are upstream**, and all three were
carried as local patches until they merged: **#42** (multi-peer `SetPSK`
lookup), **#44** (a non-OK status on the final attempt left a CLOSED response
body in `res`, so `io.ReadAll` failed with "http: read on closed response
body"), and **#49** (clearing `res` also discarded the STATUS, so an exhausted
retry loop reported 503 and 403 identically -- requested in review on #44 and
taken rather than left to the maintainer). The patch files and their
`git apply` steps are deleted. What remains is a build-time assertion for each
fix that the image actually compiles: `nodes/alice/Dockerfile` asserts both
(`found := false` for #42, the KMS sentinel for #44/#49), and
`nodes/strongswan/Dockerfile` asserts the sentinel only, because the netlink
peer lookup #42 fixed is not compiled into the VICI build. A future bump to a
revision lacking either fix fails the build rather than shipping silently. At
the `f4cf9ba` pin the checks read `repositories/wgnetlink/netlink.go` and
`repositories/kms/kms.go`, where #51 moved them, and the sentinel is
`ErrUnavailable` in package `kms`: #51 renamed `ErrKMSUnavailable` when it gave
the reader its own package, with the message text unchanged. The assertion
targets the sentinel rather than the message because
`errors.Is(err, kms.ErrUnavailable)` is what a caller branches on; the rename
means each bump has to re-check the name as well.

**The build tag the local build narrows kept its first line.** #51 renamed
`wireguardnetlink.go` to `wire_wireguard_netlink.go`, and its first line is
byte-identical to the one `services/arnika-vici/build.sh` rewrites. The shape is
unchanged -- the default writer is selected by a trailing negation, so every new
adapter must be enumerated or it collides -- and `strongswan_vici` is still not
enumerated upstream, so the local narrowing is still required. `build.sh` now
also stops if upstream ever ships a `wire_strongswan_vici.go` or a
`repositories/swanvici/` of its own.

**#51 is adopted, ahead of its merge.** The pin moved on 2026-09-26 from
`3a8cc13` to `f4cf9ba`, the head of the open PR #51 (`pqc-hpke`; 55 commits past
the merge base, +10,721/-1,264 across 68 files). It removes the file-based PQC
source, `PQC_PSK_FILE`, which is how Rosenpass's output used to reach arnika: arnika now
agrees its PQC key with its peer over HPKE, and Rosenpass keys the separate
`wg1` data tunnel instead. It also replaced the two-method key-writer port with
`SetPSK(psk []byte) error`, which is why the VICI adapter moved to its own
package. The pin is an unreviewed pull request head, so three things follow:
the "on `main`" statements this row used to make no longer hold, a change to
the branch before merge may alter what is pinned here, and the pin is re-pinned
to the merge commit as soon as #51 merges. See [`roadmap.md`](roadmap.md).

**NOT post-v1.0.1.** `v1.0.1` (`ef5a5c6`) lives only on the `v1.x` branch and
the two have **diverged**, so the pin does not contain what GitHub labels the
latest release, and neither ref is a superset of the other. Upstream `arnika`
remains preferred over the `Veriqloud/arnika-vq` fork, which has no releases or
tags and whose only original commit adds a Dockerfile this project does not use.

### liboqs

Must stay in lockstep with `liboqs-python==0.16.0.1` -- a maintenance release
of 0.16.0 that is "still built for liboqs 0.16.0" and fixes GHSA-pw23-r5gj-42g8
(command injection in the automatic liboqs install, a path this image never
takes because liboqs is already present). The bindings never refuse a library
they find and only warn when major.minor differ, so any other mismatch appears
as a missing ctypes symbol rather than a clear error. Bump both together.

**GHSA-wh5q-mpc8-67wf** (published 2026-09-22, medium): a heap out-of-bounds
read in LMS/HSS signature verification, affecting liboqs 0.11.0 through 0.16.0
and fixed in 0.17.0, which was not yet released on 2026-09-25. The pin is inside
the affected range, but nothing built here compiles the affected code:
`OQS_ENABLE_SIG_STFL_LMS` defaults to OFF, and neither
`services/pqc-validator/Dockerfile` nor
`services/pqc-tls-demo/Dockerfile.oqs-provider` passes any stateful-signature
option to CMake. Bump to 0.17.0, with `liboqs-python`, when it is tagged.

This pin reaches neither VPN lane: Rosenpass compiles its own liboqs 0.8.0
(see [rosenpass](#rosenpass)), and arnika's PQC-HPKE half uses the Go standard
library.

### oqs-provider

The licence is MIT, verified against `submodules/oqs-provider/LICENSE.txt`;
this table said Apache-2.0 until 2026-08. **The pin is not a release.**
`git describe --tags` resolves it to `0.10.0-37-g5fd81fb`. Tag `0.11.0` is **not
an ancestor**: `git rev-list --left-right --count 0.11.0...HEAD` gives `2 23`,
so the pin lacks two commits the 0.11.0 release carries while holding 23 it
does not, and the upstream compatibility note cited below is published against
0.11.0, so it has to be read with that offset in mind.

**Version pairing to watch.** `pqc-tls-demo` builds liboqs and oqs-provider from
the vendored submodules (`pqc-validator` builds liboqs only), and upstream
documents oqs-provider 0.11.0 against **liboqs 0.15.0** while this repository
pins liboqs **0.16.0**. That span includes the removal of SPHINCS+ and a rename
in which `KEM_frodokem_*` came to mean the salted variant -- the same identifier
for a different algorithm. `sphincs` appears nowhere outside the submodules,
but `frodo` does: `services/pqc-tls-demo/Dockerfile.oqs-provider` puts
`frodo640aes` in `TLS_GROUPS` and passes it to `openssl s_server -groups`.
**Checked 2026-09-25: the pinned pair agrees.** The pin contains `3cd5b688`
("Add support for both FrodoKEM variants", #749), so in its `generate.yml`
`frodo640aes` is the salted FrodoKEM-640-AES (TLS group 65059) and
`efrodo640aes` the ephemeral one (65024, the codepoint `frodo640aes` had at
0.10.0). A handshake on this group with a pre-#749 peer fails rather than
silently substituting.

**The pin is 22 commits behind 0.12.0-rc2** (`26eee364`, 2026-09-16; no 0.12.0
final yet) and lacks four fixes made there -- #810 (heap overflow), #816
(double free), #814 and #829 (use-after-free). Bump to 0.12.0 when it is tagged;
the exposure meanwhile is the make-only `pqc-tls-demo` lane, which no compose
service builds.

### rosenpass

**Check the pin with `git -C submodules/rosenpass describe --tags
--exact-match`, not with `git submodule status`.** `v0.2.2` is an *annotated*
tag and `v0.2.3` a *lightweight* one, and `git submodule status` runs
`git describe` without `--tags`, which considers only annotated tags. In a full
clone that prints `(v0.2.2-43-g512fe426)` -- a 2024 tag for a 2026 pin, which
this row once recorded; in the shallow checkout a normal working tree has, it
prints `(v0.2.3)`. Both are the same commit. Rosenpass requires Rust 1.85 or
later, because a dependency (`clap_lex` 1.1.0) declares edition 2024, so
`nodes/alice/Dockerfile` pins `rust:1.90`; bump the two together.

**The KEMs come from liboqs 0.8.0.** Rosenpass depends on `oqs-sys` 0.8 with the
`classic_mceliece` and `kyber` features; `oqs-sys` 0.8.0 vendors liboqs 0.8.0
(released 2023) and its build script always compiles that copy, statically,
into the `rosenpass` binary. So the post-quantum key exchange that keys `wg1`
does not use the liboqs pin above and does not get its fixes. In particular
0.8.0 predates liboqs 0.9.1, 0.9.2 and 0.10.1, each a security release for
potential non-constant-time behaviour in Kyber (KyberSlash). Two things limit
the exposure: Rosenpass's Kyber keys are per-handshake ephemerals, and a
disassembly of this x86-64 build found no hardware division in the affected
reference functions ([`threat-model.md`](threat-model.md) section 4). Neither is
a fix. Upgrading is an upstream change, not a local bump: liboqs 0.9.0 changed
Classic McEliece in a way that breaks Rosenpass wire compatibility
(rosenpass#880, open; #1068). The newest crate that still ships round-3 Kyber is
`oqs-sys` 0.11.0 (liboqs 0.13.0).

The liboqs 0.8.0 code compiled for those two features carries, per its own
README: Classic McEliece (`pqclean_*`) public domain; Kyber (`pqcrystals-*`)
CC0 or Apache-2.0; SHA-3 (XKCP) CC0, except `brg_endian.h` (BSD-3-Clause) and
`KeccakP-1600-AVX2.s` (the BSD-like CRYPTOGAMS licence); the AES and SHA-2
implementations public domain; `src/common/common.c` partly Apache-2.0; and
liboqs itself MIT. A redistributor of the node image carries these.

**RustSec advisories in Rosenpass's `Cargo.lock`** (OSV, 2026-09-25):
RUSTSEC-2026-0190 (`anyhow` 1.0.102), RUSTSEC-2026-0204 (`crossbeam-epoch`
0.9.18), RUSTSEC-2024-0436 (`paste` 1.0.15) and RUSTSEC-2026-0173
(`proc-macro-error2` 2.0.1). The last two are "unmaintained" notices for
build-time procedural-macro crates. The image builds with the committed lock,
which Cargo honours as long as it matches `Cargo.toml`; adding `--locked` would
harden that, not change what is built.

### SeQUeNCe

Bumped to v1.0.0 from `d135e9f8`, which was v0.8.5 plus 10 commits and 276
behind master while this table claimed the release outright. The bump is
behaviour-neutral for the `sequence` backend, and the reason is worth
recording: that backend read `Noise().depolarizing_rate`, an attribute absent
from both versions, so it silently used a fallback. See
`tests/test_sequence_backend_actually_uses_sequence.py`. Both the pin and v1.2.0
declare `numpy>=2.3.5` and `qutip>=5.2.2`, which is why
`services/bb84-kme/requirements.txt`'s old `numpy<2.3` and `qutip==5.1.1` never
described the image: this editable install upgraded both past them. Measured in
the built image on 2026-09-25 -- numpy 2.5.3, qutip 5.3.1 -- and now pinned to
those in `requirements.txt` and `constraints.txt`.

SeQUeNCe requires `gmpy2`, and its detector and optical-channel modules import
it, so the LGPL library runs inside the `bb84-kme` process (licence notes
below). v1.2.0 (licence file byte-identical) is deferred to a change of its own,
with a before/after run of `tests/test_sequence_backend_actually_uses_sequence.py`;
the reasons are under "One genuine candidate" below.

### qkdnetsim

This row was wrong on three counts until 2026-09-16, all pointing the same way,
at "nothing is happening upstream": it said the pin "is upstream HEAD", that
"the project publishes no releases or tags", and that there were "no upstream
commits since". Tag `v3.1.3` exists at `1f11f559` (2026-09-03), and `v3.1.4`
followed, whose notes list NS-3 v3.48 compatibility; this image clones
`ns-3.46`. One of the commits the pin lacks matters here:
**`7a99fc17` (2026-08-24), "Adding QKDNetSim key mixing (QKD+PQC) on key
management layer"** -- the subject of this repository, arrived at independently
upstream. The others are `525e9bf7` (2026-08-27, NS-3 v3.48 compatibility) and
`1f11f559` (docs). **Not bumped, deliberately:** no qkdnetsim binary is invoked
by anything here (see the licence notes below), so moving the pin changes no
behaviour and only the comparison value is of interest. Read `7a99fc17` before
the next architecture pass rather than treating the pin as evidence the field
is static.

### strongswan

**6.1.0 is a security floor for this lane, not only a behaviour fix.** Its
release notes list eleven CVEs. Read against this lane's configuration:
CVE-2026-78133 (a use-after-free in rekey collisions that involve multiple key
exchanges, potentially remote code execution by an authenticated peer; every
release since 6.0.0, including the previous pin 6.0.7) applies, because the
advisory exempts only servers that do not accept multiple key exchanges and
this lane negotiates `ke1_mlkem768`. The lane seldom exercises that path --
the IKE SA is reauthenticated rather than rekeyed -- but it is reachable.
CVE-2026-78127 (memory exhaustion through the logging of IKE messages; every
release since 4.1.2, except builds compiled with `DEBUG_LEVEL=0`, which
`nodes/strongswan/Dockerfile` does not set) applies too. CVE-2026-78135 (a
usable Child SA from `CREATE_CHILD_SA` before authentication completes) is
fixed in 6.1.0 but does not apply: its advisory exempts servers that do not
accept EAP, and this lane authenticates with `auth = psk`. Do not move the pin
below 6.1.0. Checked against strongSwan's advisories and its release notes on
2026-09-26.

**`blowfish` was dropped from the licence cell with the 6.1.0 bump**: 6.1.0
removes that plugin -- `src/libstrongswan/plugins/blowfish` is gone and
`configure.ac` no longer references it -- so nothing built here can carry its
licence. `des`, `md4` and `md5` remain. Upstream's own `LICENSE` at tag 6.1.0
**still names Blowfish** at lines 39-40, because that file was not updated with
the removal; the cell follows what is in the tree. strongSwan runs only in the
`alice-ipsec` and `bob-ipsec` containers, started by the `ipsec` compose
profile.

## Published data restated in the WebUI (facts only)

`/protocol-lab` restates numbers from five papers and names from one
specification. Nothing below is vendored or redistributed: no figure, map,
table image or passage of text is copied, the topology drawings are this
project's own layout, and each number carries its source reference in
`services/webui-frontend/src/lib/sim/protocolLab/publishedNetworks.ts`. That
facts are not protected by copyright is this project's reading, not legal
advice; the non-commercial sources are held to numbers and names for that
reason.

| Source | Licence | What is restated | What is not |
|---|---|---|---|
| Dynes et al., *Cambridge quantum network*, npj Quantum Inf. 5, 101 (2019), doi:10.1038/s41534-019-0221-4 | CC BY 4.0 | Link lengths, losses, 580-day average rates; the 1000/800-key global store | Figures |
| Peev et al., *The SECOQC quantum key distribution network in Vienna*, New J. Phys. 11, 075001 (2009), doi:10.1088/1367-2630/11/7/075001 | CC BY-NC-SA 3.0 | Link lengths, losses, rates, QBERs; the section 5.1.2 re-routing stores and times | Figures, map, text |
| Sasaki et al., *Field test of quantum key distribution in the Tokyo QKD Network*, Opt. Express 19, 10387 (2011), doi:10.1364/OE.19.010387, arXiv:1103.3566 | Optica open-access agreement (non-commercial) | Link lengths, losses, rates, QBERs; the section 4 switch-over | Figures, text |
| Martin et al., *MadQCI: a heterogeneous and scalable SDN-QKD network deployed in production facilities*, npj Quantum Inf. 10, 80 (2024), doi:10.1038/s41534-024-00873-2, arXiv:2311.12791 | CC BY 4.0 | Span lengths and losses | Figures, Table 1 rates (not bound to spans) |
| Dosan et al., *Secure Medical Data Transmission Using Quantum Key Distribution and Post-Quantum Cryptography in Real-World Fiber Networks*, arXiv:2608.18869v2 (2026) | CC BY 4.0 | Table I values (rates, QBERs, coincidence rates); aerial and buried lengths; campaign lengths; the 2022 route of about 75 km; the BBM92 protocol; node names; a short quoted phrase about the keystore; the wind correlation r = 0.78; the QuantShake algorithms and its 120 s interval. One length, the 19 km buried section, is a number read from a Fig. 1(a) label; it also follows from the text (70 - 51 km, section IV.B) | Figures: none is reproduced |
| ETSI GS QKD 004 V2.1.1 (2020-08) | ETSI copyright, all rights reserved | Function, parameter and QoS field names, types, units and the numeric status codes 0-8, in `etsi004SpecV211.json` | Any description: every one is this project's paraphrase, and the PDF is not bundled |

## Submodule currency, and how it was checked

Verified 2026-09-25 by querying each upstream directly with
`git ls-remote --tags`, not from memory or from a package index.

**Five pins are exactly on the latest semver tag:** `SimQN` v0.2.3,
`liboqs` 0.16.0, `openQKDsecurity` v2.2.0, `rosenpass` v0.2.3,
`tno-qkd-key-rate` v2.0.4. `strongswan` is on the annotated `6.1.0`.

**Two upstreams publish no semver tags at all**, by the release-tag filter of
trap 1 below, so "behind" has no meaning for them: `qkd-pqc-paper-supplementary`, `qkd_kme_server`.
The first has no tags of any kind; the second has one pre-release tag,
v0.0.1-alpha, which that filter excludes, and the pin is 80 commits past it.
`qkdnetsim` was the third until it published `v3.1.3` on 2026-09-03 (and
`v3.1.4` on 2026-09-21).

### Three traps in reading this, each of which produced a wrong answer first

**1. Sorting tags naively picks nonsense.** Filter to `vX.Y.Z` before
comparing, or the "latest tag" comes out as `nist-branch-snapshot-2018-11` for
liboqs, `ietf116` for oqs-provider and `6.0dr18` for strongSwan.

**2. A newer tag can be an older tree.** `wgephemeralpeer` looks behind
`v1.0.6`, and moving to it would go back **fifteen months**:

| | commit | date |
|---|---|---|
| our pin | `0080bf8` | **2026-05-08** |
| `v1.0.6` | `8795a5a` | **2025-02-03** |

`v1.0.6` is an **ancestor** of the pin: `git merge-base --is-ancestor` succeeds,
`git rev-list --left-right --count v1.0.6...HEAD` is **0 / 45**, and
`git describe --tags` returns `v1.0.6-45-g0080bf8`, which only resolves for a
descendant. Moving to the tag would be a strict fifteen-month downgrade. An
earlier version of this passage called the two "divergent lines" and quoted a
count that does not reproduce; 45 is the correct number.

**3. Ancestry and counts are both meaningless in a shallow clone.** This is the
trap that produced the numbers above, and it is easy to hit here: most
submodule clones in a normal working tree are shallow, and a shallow clone
reports `git rev-list --count HEAD` = 1. CI makes it worse by design --
`.github/workflows/ci.yml` checks submodules out with `--depth 1`, so anyone
reproducing a figure there gets a different answer from someone with full
history, and neither is obviously wrong on its face. Check
`git rev-parse --is-shallow-repository` **before** quoting any `rev-list` or
`merge-base` result, and prefer a `--bare --filter=blob:none` mirror for audits.
Dates and `git describe` degrade more honestly than counts do.

### The pins that are not on a tag, and why each stays

Deliberately not on a tag, one paragraph each. (Written as prose rather than a
table: `tests/test_notices_match_the_pins.py` keys off any row whose first cell
is a submodule name, and a second table of the same shape silently overrode the
canonical one above -- it caught that on the first run of this section.)

- **oqs-provider**, pin `5fd81fb`. Tag `0.11.0` is a **downgrade in
  substance**: `git rev-list --left-right --count` measures **23 / 2**, so
  moving to it loses 23 commits and gains 2. The pin also carries the
  `Using with LibOQS 0.16.0` section that 0.11.0 predates, and `Makefile`
  builds it against exactly that liboqs pin.

- **wgephemeralpeer**, pin `0080bf8`. Tag `v1.0.6` is fifteen months older --
  see the dates above.

- **strawberryfields**, pin `162125d8`. Upstream **archived**. The pin is the
  final `master` commit, 8 commits ahead of the last tag `v0.23.0-post1`.
  Nothing newer exists.

- **arnika**, pin `f4cf9ba`, the head of the open PR #51, not a release. The
  `v1.0.1` tag is a **divergent line**, not a newer release. Its advisory,
  GHSA-rc6v-5rmx-w5mv, named three areas; at the pin, `repositories/kms/kms.go`
  carries the comment removing `InsecureSkipVerify` for it, the ACK path in
  `transport/server.go` checks the timestamp window, and the PQC key file the
  third area concerned no longer exists, because #51 removed it. (The previous
  pin `3a8cc13` handled that third area by rejecting a PSK file looser than
  0600.) No security gap from not taking `v1.0.1`.

### One genuine candidate, deliberately not taken

`SeQUeNCe` is pinned at `v1.0.0`. `v1.1.0` is an **incomplete release**: at that
tag `pyproject.toml` still reads `version = "1.0.0"`, there is no GitHub Release
object, `CHANGELOG.md` has no 1.1.0 entry, and PyPI still serves 1.0.0. The tag
appears to be a semantic-release run that produced a tag without the
version-bump commit. Pinning it would ship a tree that self-reports the version
already pinned.

`v1.2.0` (2026-09-12) is complete -- `pyproject.toml` reads
`version = "1.2.0"`, `CHANGELOG.md` carries a `## v1.2.0` entry, and a GitHub
Release object exists. The pin is **64 commits behind** it. It is not bumped in
the change that found it: the `sequence` backend is the only consumer, `v1.0.0`
was itself a behaviour-motivated bump (see the notes above), and a
two-minor-version move deserves its own before/after rather than riding along
with a documentation pass.

## License compatibility considerations

- **SimQN (GPL-3.0)** is used as a Python-importable library inside `services/bb84-kme`.
  Per the standard library-vs-binary distinction we treat this service as a GPLv3
  sub-component of the otherwise Apache-2.0 repository; the GPL only extends to
  derivative works of SimQN itself.
- **gmpy2 (LGPL-3.0-or-later)** is loaded into the same `bb84-kme` process,
  because SeQUeNCe imports it. Its wheel bundles GMP, MPFR and MPC as shared
  objects (GMP is dual-licensed LGPL-3.0-or-later / GPL-2.0-or-later; MPFR and
  MPC are LGPL-3.0-or-later). Redistributing the image means carrying those
  licence texts and a source offer for the three libraries; the relinking
  condition is met because they are shared objects. The **MPL-2.0** packages
  (`certifi`, `tqdm`, `fqdn`) are file-level copyleft; they ship unmodified, so
  pointing to their upstream source meets the obligation.
- **qkdnetsim and ns-3 (both GPL-2.0-only)** are not executed.
  `services/qkdnetsim-kme` runs `kme_facade.py`, a Flask app of this project's
  own; no qkdnetsim or ns-3 binary is invoked by anything in this repository,
  so no GPL obligation reaches the calling code. **Building is not the same as
  running, though.** `services/qkdnetsim-kme/Dockerfile` clones ns-3-dev at tag
  `ns-3.46`, compiles it with qkdnetsim, and ships the build output in an image.
  Hosting that image as a service distributes nothing; handing it to someone
  distributes GPL-2.0 object code from both, and the source offer has to cover
  ns-3-dev at `ns-3.46` as well as the qkdnetsim pin. It sits behind the
  `crossvalidate` profile and is not part of the default stack. "Only" matters:
  GPL-2.0-only code cannot be combined into one work with GPL-3.0 code (SimQN)
  or with the Apache-2.0 code, so keeping it in its own container is a
  requirement, not a convenience.
- **openQKDsecurity (MIT)** is *not* shipped in the runtime image and is not
  currently used to produce anything. `config/qkd_keyrate_table.json` names
  `tools/precompute_keyrate_table_fallback.py` in its `provenance` field and
  only Lo-Ma-Chen and Lim et al. PRA 89, 022307 (2014) in its `formulas` field;
  no MATLAB ran, so there is no derivative-work question to answer. If the
  submodule is ever used to generate a shipped artefact, the data-not-code
  argument has to be made then, on that premise.
- **Strawberry Fields (Apache-2.0)** is fully compatible with this repository's
  Apache-2.0 baseline.
- **strongSwan (GPL-2.0-or-later, with an OpenSSL/LGPL linking exception)** runs
  only in the `alice-ipsec` and `bob-ipsec` containers, built from
  `nodes/strongswan/` and started by the `ipsec` compose profile. Its source is
  unmodified. The Go VICI key-writer in `services/arnika-vici/` talks to charon
  over the local VICI unix socket (`/var/run/charon.vici`) through the MIT
  `govici` client and links no strongSwan code; it and the wrapper
  `entrypoint.sh` are this project's own work and remain Apache-2.0. Anyone who
  *redistributes* that image must meet the GPL-2.0 source-offer obligation for
  the strongSwan binaries (the special exception permits combining with OpenSSL
  and LGPL libraries).
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
  key exchange whose output key becomes the preshared key of the `wg1` data
  tunnel (until 2026-09-26 it was HKDF-combined with the QKD key by arnika). Both
  licenses are permissive and fully compatible with the Apache-2.0 baseline, as
  are `oqs-sys` and the liboqs 0.8.0 it links statically (see the notes above
  for the component terms).
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
SeQUeNCe with its LGPL `gmpy2`. Note the word: `SIMULATOR_BACKEND` is a runtime
variable and cannot un-ship a baked layer. `services/bb84-kme/Dockerfile` runs
`pip install -c constraints.txt -e /opt/SimQN` regardless of backend, and
installs SeQUeNCe the same way, so the image you hand over contains GPL-3.0 and
LGPL-3.0 code whichever backend it is configured to run. To avoid shipping
either, build without the SimQN line and without SeQUeNCe, which is what brings
in `gmpy2`; the MPL-2.0 packages remain, with only their file-level duties.
strongSwan is confined to the `alice-ipsec` and `bob-ipsec` image; the
WireGuard nodes contain no strongSwan code.

For the exact license text of each submodule, see the `LICENSE` file inside the
respective `submodules/<name>/` directory.
