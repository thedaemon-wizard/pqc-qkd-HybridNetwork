# Third-Party Notices

This repository incorporates the following open-source software as git submodules.
Each retains its original copyright notice and license terms.

| Submodule | License | Project | Phase | Activity (verified 2026-09-16) |
|---|---|---|---|---|
| `arnika` | Apache-2.0 | [arnika-project/arnika](https://github.com/arnika-project/arnika) — prototype developed at CANCOM Converged Services GmbH under EU EUROQCI / QCI-CAT (DIGITAL-2021-QCI-01, No. 101091642) | 0–7, 9 | pinned to `3a8cc13` (2026-09-11), which is `main` HEAD, 166 commits past the previous pin. **Three fixes reported from this project are now upstream**, and all three were carried as local patches until they merged: **#42** (multi-peer `SetPSK` lookup), **#44** (a non-OK status on the final attempt left a CLOSED response body in `res`, so `io.ReadAll` failed with "http: read on closed response body"), and **#49** (clearing `res` also discarded the STATUS, so an exhausted retry loop reported 503 and 403 identically -- requested in review on #44 and taken rather than left to the maintainer). Both patch files and their `git apply` steps are deleted; two `grep -q` assertions remain in each node Dockerfile -- `found := false` for #42 and **`ErrKMSUnavailable`** for #44/#49 -- so a future bump to a revision lacking either fails the build rather than shipping silently. The second targets the SENTINEL NAME, not the message text: the wording changed once between the PR and the merge, and `errors.Is(err, ErrKMSUnavailable)` is what a caller branches on. **This bump also moved a build tag.** Upstream added `&& !wireguard_netlink_netns` to `wireguardnetlink.go` when it landed the netns writer (#48), which `build.sh` asserts on and which correctly failed the build until updated. The underlying shape is unchanged -- the default writer is selected by a trailing negation, so every new adapter must be enumerated or it collides -- and `strongswan_vici` is still not enumerated upstream, so the local narrowing in `build.sh` is still required. NOT post-v1.0.1: `v1.0.1` (`ef5a5c6`) lives only on the `v1.x` branch and the two have **diverged**, so the pin does not contain what GitHub labels the latest release, and neither ref is a superset of the other. Upstream `arnika` remains preferred over the `Veriqloud/arnika-vq` fork, which has no releases or tags and whose only original commit adds a Dockerfile this project does not use. |
| `liboqs` | MIT (LICENSE text; GitHub auto-detector shows NOASSERTION) | Open Quantum Safe project | 0–7 | pinned to `5a1a854b`. active. Pinned to tag **0.16.0** (2026-07-09) and built from the submodule into the `pqc-validator` image. Must stay in lockstep with `liboqs-python==0.16.0.1` -- a maintenance release of 0.16.0 that is "still built for liboqs 0.16.0" and fixes GHSA-pw23-r5gj-42g8 (command injection in the automatic liboqs install, a path this image never takes because liboqs is already present). The bindings never refuse a library they find and only warn when major.minor differ, so any other mismatch appears as a missing ctypes symbol rather than a clear error. Bump both together. |
| `oqs-provider` | **MIT** | Open Quantum Safe project | 0–7 | pinned to `5fd81fb4`. active. Verified against `submodules/oqs-provider/LICENSE.txt`, which is the MIT text; this table previously said Apache-2.0. **The pin is not a release.** `git describe --tags` resolves it to `0.10.0-37-g5fd81fb`, a `main` commit 37 past the 0.10.0 tag. Tag `0.11.0` is **not an ancestor**: `git rev-list --left-right --count 0.11.0...HEAD` gives `2 23`, so the pin lacks two commits the 0.11.0 release carries while holding 23 it does not. The rest of this row previously reasoned as though the pin *were* 0.11.0. It is not, and the upstream compatibility note cited below is published against 0.11.0, so it has to be read with that offset in mind. **Version pairing to watch:** `pqc-tls-demo` builds liboqs and oqs-provider from the vendored submodules (`pqc-validator` builds liboqs only; this row said both until 2026-09-25), and upstream documents oqs-provider 0.11.0 against **liboqs 0.15.0** while this repository pins liboqs **0.16.0**. That span includes the removal of SPHINCS+ and a rename in which `KEM_frodokem_*` came to mean the salted variant -- the same identifier for a different algorithm. `sphincs` appears nowhere outside the submodules, but **`frodo` does**: `services/pqc-tls-demo/Dockerfile.oqs-provider` puts `frodo640aes` in `TLS_GROUPS` and passes it to `openssl s_server -groups`. This row previously read "Neither is used here ... so the skew is currently harmless", and that conclusion rested on a false premise -- the FrodoKEM rename is exactly the part of the skew that could bite. The blast radius is small but not zero: no compose service builds that image, so it is reached only by `make pqc-tls-demo-both`. **Checked 2026-09-25: the pinned pair agrees.** The pin contains `3cd5b688` ("Add support for both FrodoKEM variants", #749), so in its `generate.yml` `frodo640aes` is the salted FrodoKEM-640-AES (TLS group 65059) and `efrodo640aes` the ephemeral one (65024, the codepoint `frodo640aes` had at 0.10.0). A handshake on this group with a pre-#749 peer fails rather than silently substituting. **The pin is also 22 commits behind 0.12.0-rc2** (`26eee364`, 2026-09-16; no 0.12.0 final yet) and lacks four fixes there -- #810 (heap overflow), #816 (double free), #814 and #829 (use-after-free). Bump to 0.12.0 when it is tagged; the exposure meanwhile is the make-only `pqc-tls-demo` lane, which no compose service builds. |
| `rosenpass` | MIT / Apache-2.0 (dual) | Rosenpass project contributors | 0–7 | pinned to `512fe426`. pinned submodule **v0.2.3** (2026-08-03); real PQ key exchange in `nodes/alice`. **What `git submodule status` prints for this row depends on how deep the clone is, which is why it is not the thing to check.** `v0.2.2` is an *annotated* tag and `v0.2.3` is a *lightweight* one, and `git submodule status` runs `git describe` without `--tags`, which considers only annotated tags. In a full clone that walked back to `v0.2.2` and printed `(v0.2.2-43-g512fe426)` -- a 2024 tag for a 2026 pin, which is what this row used to record. In the shallow checkout a normal working tree actually has, `v0.2.2` is not reachable at all, plain `git describe` **fails**, and the output becomes `(v0.2.3)`. Both are the same commit; neither is a reliable answer. The pin is v0.2.3 -- confirm with `git -C submodules/rosenpass describe --tags --exact-match`, which returns it under either depth. See trap 3 above: this is the same shallow-clone effect, showing up in a command that looks like it is reporting a fact rather than computing one. Requires Rust >= 1.85 because a dependency (`clap_lex` 1.1.0) declares edition 2024, so `nodes/alice/Dockerfile` pins `rust:1.90` -- bump the two together. |
| `SimQN` | GPLv3 | independent (Cui et al.) | 8 | pinned to `29a94689`, which **is** `refs/tags/v0.2.3` -- the pin is on the latest release, not behind it. Verified 2026-08-28: `git ls-remote --tags --heads https://github.com/ertuil/SimQN` prints `29a94689... refs/tags/v0.2.3`, and the only branches are `main`, `gh-pages` and `old` -- there is no `master` for the pin to trail. |
| `SeQUeNCe` | custom Argonne "OPEN SOURCE LICENSE" (BSD-3-Clause-equivalent terms; GitHub shows NOASSERTION) — commercial use permitted with attribution | Argonne National Laboratory | 8 | pinned to `ffd7c837`, the tag **v1.0.0** (2026-06-17). Bumped from `d135e9f8`, which was v0.8.5 plus 10 commits and 276 behind master while this row claimed the release outright. The bump is behaviour-neutral for the `sequence` backend, and the reason is worth recording: that backend read `Noise().depolarizing_rate`, an attribute absent from both versions, so it silently used a fallback. See `tests/test_sequence_backend_actually_uses_sequence.py`. **v1.2.0 is out** (`344c3997`, 2026-09-12; 64 commits past the pin, licence file byte-identical). Not bumped in this batch; it is on the roadmap. Both the pin and v1.2.0 declare `numpy>=2.3.5` and `qutip>=5.2.2`, which is why `services/bb84-kme/requirements.txt`'s old `numpy<2.3` and `qutip==5.1.1` never described the image: this editable install upgraded both past them. Measured in the built image on 2026-09-25 -- numpy 2.5.3, qutip 5.3.1 -- and now pinned to those in `requirements.txt` and `constraints.txt`. |
| `qkdnetsim` | GPL v2 | QKDNetSim project (Mehic et al.) | 8 | pinned to `1cda34cb` (2026-05-03). **This row was wrong on three counts until 2026-09-16** and is corrected rather than quietly rewritten, because all three pointed the same way -- at "nothing is happening upstream". It said the pin "is upstream HEAD" (it was **3 behind** then, and is **4 behind** since `v3.1.4`, `e6330fe6`, 2026-09-21, whose notes list NS-3 v3.48 compatibility -- this image clones `ns-3.46`), that "the project publishes no releases or tags" (tag **`v3.1.3`** exists at `1f11f559`, 2026-09-03), and that there were "no upstream commits since" (there are three). One of them matters here: **`7a99fc17` (2026-08-24), "Adding QKDNetSim key mixing (QKD+PQC) on key management layer"** -- the subject of this repository, arrived at independently upstream. The others are `525e9bf7` (2026-08-27, NS-3 v3.48 compatibility) and `1f11f559` (docs). **Not bumped, deliberately:** no qkdnetsim binary is invoked by anything here (see the GPL note below), so moving the pin changes no behaviour and only the comparison value is of interest. Read `7a99fc17` before the next architecture pass rather than treating the pin as evidence the field is static. |
| `openQKDsecurity` | MIT | Lütkenhaus group / U. Waterloo | 8 (offline) | pinned to `f952c355`. active; pinned submodule **v2.2.0** (2026-06-17). This row previously claimed the pin was "3 commits ahead of v2.2.0, so it already includes that release" -- the comparison was inverted. `git describe` read `v2.1.0-2-g6ffeed8`, i.e. 3 commits BEHIND, and v2.2.0 was not an ancestor. Bumped, and `tests/test_notices_match_the_pins.py` now checks every row: the backticked pin against `git ls-tree HEAD` (the index, which is correct even for the submodules not checked out), and a bolded tag against `git ls-remote --tags`. It deliberately does NOT use `git submodule status`, which reports the working tree. |
| `strawberryfields` | Apache-2.0 | Xanadu | 8 | pinned to `162125d8`. **ARCHIVED on GitHub** (read-only; last push 2026-01-16) and the Xanadu cloud is decommissioned. Local simulation still runs and backs the `cvqkd` backend. |
| `tno-qkd-key-rate` | Apache-2.0 | TNO (Netherlands Org. for Applied Scientific Research) | 8 | pinned to `4cac9df0`. pinned submodule **v2.0.4**, 2026-02 (active); `tno` backend + key-rate cross-check |
| `strongswan` | **GPL-2.0-or-later** (+ OpenSSL/LGPL linking exception; des/md4/md5 plugins differ) | strongSwan project | 9 | pinned to `b43f6bfe`, the annotated tag **6.1.0** (tagged 2026-09-06, released 2026-09-07). Moved up from 6.0.7 for [`50177b40`](https://github.com/strongswan/strongswan/commit/50177b4004d1fec4299cd7bed4a3c7fb0f4208d7), which enforces `ppk_required` on the initiator -- see [`vici-ppk.md`](vici-ppk.md). **`blowfish` was dropped from this cell with the bump**: 6.1.0 removes that plugin -- `src/libstrongswan/plugins/blowfish` is gone and `configure.ac` no longer references it -- so nothing built here can carry its licence. `des`, `md4` and `md5` remain. Note for anyone checking: upstream's own `LICENSE` at tag 6.1.0 **still names Blowfish** at lines 39-40, because that file was not updated with the removal. The cell follows what is in the tree, not what the licence file says about code that is no longer in it. |
| `PQClean` | per-algorithm (mostly Public Domain / MIT) | PQClean consortium | 8 | pinned to `202a8f96`. **ARCHIVED on GitHub** (read-only; last push 2026-08-04). Previously listed here as "active", which was wrong. Reference implementations only; nothing is built from it today. |
| `qkd-pqc-paper-supplementary` | **NONE — no licence file of any kind** | aparcar / Spooren et al. | 9 | pinned to `712e4b36`. Reference only: not redistributed, not built into any image, and not to be vendored into a derived work without the authors' permission. Absent from this table until now, which is the omission that matters most here. |
| `fastapi` (PyPI) | MIT | Sebastián Ramírez and contributors | 0–12 | v0.141.1 in `bb84-kme`, `pqc-validator` and `webui-backend`. Moved from 0.115.6 on 2026-09-25 because that release capped Starlette below 0.42 (next row). |
| `starlette` (PyPI) | BSD-3-Clause | Encode OSS and contributors | 0–12 | v1.7.0, pinned next to fastapi in all three services. 0.41.3 carried seven published advisories on 2026-09-25, three HIGH, one of them an O(n^2) Range-header DoS in `FileResponse` that the public demo exposed through `/api/exports/download`. |
| `liboqs-python` (PyPI) | MIT | Open Quantum Safe project | 0–7 | v0.16.0.1; see the `liboqs` row for the version coupling. |
| `wgephemeralpeer` | GPL-3.0 | Mullvad VPN | 11 | pinned to `0080bf8d` (2026-05-08); latest release is v1.0.6 (2025-02-03) and upstream has moved on since the pin. Alternative PSK-injection (benchmark reference, no live integration). |
| `html-to-image` (npm) | MIT | bubkoo et al. | 12 | v1.11.13; capture DOM to PNG for ExportToolbar PNG / Animation |
| `modern-gif` (npm) | MIT | qq15725 | 12 | v2.1.0 (2026-04-16); encodes animated GIF exports in a worker. Replaced `gifshot`, which had not been released since 2017-12-18. |
| `@noble/post-quantum` (npm) | MIT | Paul Miller | 12 | v0.7.1 (2026-08-27; enforces the digest lengths that pre-hash XOF OIDs promise and hardens WebCrypto input validation); in-browser ML-KEM / ML-DSA for the client-side PQC validator. Self-audited; makes no constant-time claim. |
| `@noble/hashes` (npm) | MIT | Paul Miller | 12 | v2.4.0; SHA-3 and HKDF. This is the package that actually performs the HKDF-SHA3-256 the README headlines for the client-side lane. |
| `@noble/ciphers` (npm) | MIT | Paul Miller | 12 | v2.4.0; ChaCha20-Poly1305 for the in-browser AEAD. |
| `react` / `react-dom` (npm) | MIT | Meta and contributors | 12 | v18.3.1; WebUI runtime. |
| `react-router-dom` (npm) | MIT | Remix / React Training | 12 | v6.30.6; client-side routing. 6.30.6 closes the open-redirect advisories fixed on the 6.x line (GHSA-jjmj-jmhj-qwj2, GHSA-2j2x-hqr9-3h42). Two remain that are fixed only in 7.18.0, and neither is reachable here as far as this project can tell: GHSA-wrjc-x8rr-h8h6 needs an attacker-controlled `to` in `<Link>` or `useNavigate`, and the only navigation targets are the constant list in `App.tsx`; GHSA-337j-9hxr-rhxg affects SSR hydration, and this is a client-only SPA. The v7 migration is on the roadmap. |
| `plotly.js` (npm) | MIT | Plotly | 12 | v4.1.1; charting. **This row named `plotly.js-dist-min` 2.35.3 until 2026-09-25, which the site never shipped**: nothing imported it, and `react-plotly.js` loads `plotly.js/dist/plotly`, so npm resolved the undeclared peer to plotly.js 3.5.1 -- whose bundle embedded maplibre-gl 4.7.1 (GHSA-jrc7-96c5-q579, CRITICAL, fixed 6.4.1). plotly.js is now declared directly and the unused package removed; 4.1.1 bundles maplibre-gl 6.9.0 (BSD-3-Clause). **4.0.0 turned on a "send to cloud" modebar button by default** that uploads chart data to cloud.plotly.com; every chart here passes `PLOT_CONFIG` (`src/lib/plotConfig.ts`), which turns it off, and a test fails if one does not. The *library* is MIT; Plotly's commercial offerings are separate and not used. |
| `react-plotly.js` (npm) | MIT | Plotly | 12 | v4.1.0; React bindings for the above, with its own TypeScript types (the local `declare module` stub was removed). |
| `d3-force` (npm) | ISC | Mike Bostock | 12 | v3.0.0; force-directed layout for the topology graph. |
| `vite` (npm) | MIT | Evan You and contributors | 12 | v6.4.3; build tool (dev dependency, not shipped in the bundle). |
| `typescript` (npm) | Apache-2.0 | Microsoft | 12 | v5.9.3; type checker (dev dependency, not shipped in the bundle). |
| `qkd_kme_server` | MIT (`LICENSE`: "MIT License, Copyright (c) 2025 Thomas Prévost") | Thomas Prévost (`thomasarmel`) | 14 | pinned to `4d53a3dc` (2026-04-01), which is upstream HEAD. There have been no upstream commits since, so this is current rather than actively developed; the row previously read "active", and the licence column read "(see repo LICENSE)" without saying what it was. Rust ETSI GS QKD 014 v1.1.1 KME, **vendored for reference and not built**: no Dockerfile, compose file or Makefile target in this repository compiles or runs it (checked 2026-09-25). This row used to call it a third reference implementation alongside `bb84-kme` and `qkdnetsim-kme`, which read as though it were deployed. |
| `pq-wireguard` (Kudelski Security) | — | — | rejected | **archived 2024-09-03** ("not actively maintained anymore"); kept only as historical reference, NOT integrated |
| `qkd-kem-provider` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2025-06; oqs-provider fork hybridising PQ KEMs with QKD — listed for the crypto-agility roadmap |
| `qkd-etsi-api-c-wrapper` (qursa-uc3m) | MIT | UC3M / Vigo (QURSA) | reference | 2024-11; C wrapper for ETSI 004/014 — listed for the crypto-agility roadmap |

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
| Dosan et al., *Secure medical data transmission using QKD and PQC in real-world fiber networks*, arXiv:2608.18869v2 (2026) | CC BY 4.0 | Table I values, aerial and buried lengths, campaign lengths | Figures |
| ETSI GS QKD 004 V2.1.1 (2020-08) | ETSI copyright, all rights reserved | Function, parameter and QoS field names, types, units and the numeric status codes 0-8, in `etsi004SpecV211.json` | Any description: every one is this project's paraphrase, and the PDF is not bundled |

## Submodule currency, and how it was checked

Verified 2026-09-16 by querying each upstream directly with
`git ls-remote --tags`, not from memory or from a package index.

**Five pins are exactly on the latest semver tag:** `SimQN` v0.2.3,
`liboqs` 0.16.0, `openQKDsecurity` v2.2.0, `rosenpass` v0.2.3,
`tno-qkd-key-rate` v2.0.4. `strongswan` is on the annotated `6.1.0`.

**Three upstreams publish no semver tags at all**, so "behind" has no meaning
for them: `PQClean`, `qkd-pqc-paper-supplementary`, `qkd_kme_server`.
`qkdnetsim` was the fourth until it published `v3.1.3` on 2026-09-03 (and `v3.1.4` on 2026-09-21).

### Three traps in reading this, each of which produced a wrong answer first

**1. Sorting tags naively picks nonsense.** Filter to `vX.Y.Z` before
comparing, or the "latest tag" comes out as `round3` for PQClean,
`nist-branch-snapshot-2018-11` for liboqs, `ietf116` for oqs-provider and
`6.0dr18` for strongSwan.

**2. A newer tag can be an older tree.** `wgephemeralpeer` looks behind
`v1.0.6`, and moving to it would go back **fifteen months**:

| | commit | date |
|---|---|---|
| our pin | `0080bf8` | **2026-05-08** |
| `v1.0.6` | `8795a5a` | **2025-02-03** |

`v1.0.6` is an **ancestor** of the pin: `git merge-base --is-ancestor` succeeds,
`git rev-list --left-right --count v1.0.6...HEAD` is **0 / 45**, and
`git describe --tags` returns `v1.0.6-45-g0080bf8`, which only resolves for a
descendant. Moving to the tag would be a strict fifteen-month downgrade. The
conclusion stands; the reasoning below it did not.

**This passage was wrong from 2026-08 until 2026-09-16, and the correction is
kept because the error is instructive.** It said the two were "divergent lines"
and quoted `1 / 69`. The first came from reading "v1.0.6 is not a *descendant*"
as "the lines diverged", which drops the case that actually holds -- v1.0.6 is
not a descendant because it is an *ancestor*. The second number does not
reproduce. It then dismissed an earlier audit that had reported "45 commits
ahead of v1.0.6" as "wrong in its number, and right only by accident": **45 is
the correct number**, and that dismissal is withdrawn.

**3. Ancestry and counts are both meaningless in a shallow clone.** This is the
trap that produced the numbers above, and it is easy to hit here: **9 of the 15
submodule clones in a normal working tree are shallow, and 8 of those report
`git rev-list --count HEAD` = 1.** CI makes it worse by design --
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
  final `master` commit, ahead of the last tag `v0.23.0`. Nothing newer exists.

- **arnika**, pin `3a8cc13`, on `main`. The `v1.0.1` tag is a **divergent
  line**, not a newer release. Both of its security fixes
  (GHSA-rc6v-5rmx-w5mv, and removing `InsecureSkipVerify`) are present on
  `main` as re-applied changes: `config/config.go` rejects a PSK file looser
  than 0600, and `repositories/kms.go` carries the removal comment. No security
  gap from staying.

### One genuine candidate, deliberately not taken

`SeQUeNCe` is pinned at `v1.0.0`. `v1.1.0` is an **incomplete release**: at that
tag `pyproject.toml` still reads `version = "1.0.0"`, there is no GitHub Release
object, `CHANGELOG.md` has no 1.1.0 entry, and PyPI still serves 1.0.0. The tag
appears to be a semantic-release run that produced a tag without the
version-bump commit. Pinning it would ship a tree that self-reports the version
already pinned. That diagnosis still holds, and it is left here because it is
the reason the pin skipped a tag rather than trailing one.

**The re-check condition this paragraph set has now been met.** `v1.2.0`
(2026-09-12) is complete -- `pyproject.toml` reads `version = "1.2.0"`,
`CHANGELOG.md` carries a `## v1.2.0` entry, and a GitHub Release object exists.
The pin is **64 commits behind** it. Not bumped in the same change that found
it: the `sequence` backend is the only consumer, `v1.0.0` was itself a
behaviour-motivated bump (see the row above), and a two-minor-version move
deserves its own before/after rather than riding along with a documentation
pass. Verified 2026-09-16.

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
  **Building is not the same as running, though.** `services/qkdnetsim-kme/Dockerfile`
  compiles NS-3 with qkdnetsim (`./ns3 build qkdnetsim`) and copies the build
  into the runtime image. Hosting that image as a service distributes nothing;
  handing the image to someone distributes GPL-2.0 object code, with the
  source-offer obligations that carries. It sits behind the `crossvalidate`
  profile and is not part of the default stack.
- **openQKDsecurity (MIT)** is *not* shipped in the runtime image, and is not
  currently used to produce anything. This entry previously read "We use it
  off-line to pre-compute `config/qkd_keyrate_table.json`; the resulting table
  is data, not derivative MATLAB code, and may be redistributed freely." The
  conclusion happens to be right and the premise is wrong, which is worse than
  either alone: that table's own `provenance` field names
  `tools/precompute_keyrate_table_fallback.py`, its `formulas` field names only
  Lo-Ma-Chen and Lim et al. PRA 89, 022307 (2014), and `tools/precompute_keyrate_table.m` has
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
`services/bb84-kme/Dockerfile` runs `pip install -c constraints.txt -e /opt/SimQN` regardless of
backend, so the image you hand over contains GPL-3.0 code whichever backend it
is configured to run. To actually avoid shipping it, build without that line.
The privileged WireGuard nodes link strongSwan only when the optional IPsec
profile is enabled; the default WireGuard+arnika+rosenpass path does not.

For the exact license text of each submodule, see the `LICENSE` file inside the
respective `submodules/<name>/` directory.
