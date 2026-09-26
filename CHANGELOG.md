# Changelog

All notable changes to this repository, one section per release. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release
numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html);
while the major version is 0, any release may change configuration or
interfaces. Each release is a git tag, `v` plus the number.

This file is the summary. The build-by-build record, with how each change was
verified at the time, is [`docs/phases.md`](docs/phases.md).

## [0.2.0] - unreleased

Not tagged yet: the date and the `v0.2.0` tag are set when the change is
tagged, after it is merged.

The arnika pin moves to the head of arnika PR #51, which replaces the file
handover of the PQC key with a key agreement between the arnika peers, and the
WireGuard lane takes the layering of the reference paper
(arXiv:2604.05599, 4.2). Detail:
[`docs/phases.md`](docs/phases.md#2026-09-26--arnika-51-adopted-and-the-wireguard-lane-layered-as-in-the-paper-release-020).

### Changed

- `submodules/arnika` is pinned to `f4cf9ba` (2026-09-24), the head of the
  **open, unmerged** arnika PR #51, instead of `3a8cc13` on upstream `main`. It
  will be re-pinned to the merge commit once #51 merges.
- arnika's PQC half is PQC-HPKE on every instance: HPKE in Base mode
  (RFC 9180) with the KEM MLKEM1024-P384 (a hybrid of ML-KEM-1024 and P-384
  ECDH, codepoint 0x0051 of draft-ietf-hpke-pq, not yet an RFC), HKDF-SHA384
  and an export-only AEAD, agreed over the UDP socket the peers already share.
  Every instance runs `PQC_ENABLED=true` with `QkdAndPqcRequired` and the
  30 s interval; charlie's instance moves from `AtLeastQkdRequired` to match
  its peer.
- WireGuard lane: `wg0` is the hop tunnel, keyed by arnika with
  HKDF-SHA3-256 over the QKD key and the PQC-HPKE key; the new `wg1` is the
  end-to-end data tunnel, keyed by Rosenpass (Classic McEliece 460896 +
  Kyber512) and carried inside `wg0`. The Rosenpass exchange itself runs
  between the two `wg0` addresses: the node with the lower `wg0` address
  initiates it and the other only answers, since two initiators left the ends
  on different `wg1` keys after a cold start. In the multi-hop overlay the
  charlie leg gets the same two layers, so the relay also holds that leg's
  `wg1` key.
- The WireGuard entrypoint starts arnika at the next wall-clock multiple of
  `ARNIKA_INTERVAL`, which it now parses, so that the two processes of a pair
  start counting their intervals in step, as they did while arnika waited
  for the first Rosenpass key: the pinned arnika fails closed at the end of a
  BACKUP interval that received no `key_id`, and a `key_id` that reaches the
  BACKUP before its own boundary is counted in its previous interval. The
  IPsec entrypoint deliberately starts arnika as at 0.1.0, so that both arms
  of the before/after measurement run the same entrypoint start behaviour;
  the start offset itself is measured in each arm. Neither is a mitigation of
  the IPsec lane's PPK ordering race. The two nodes of a pair are recreated
  together
  ([`docs/BUILD.md`](docs/BUILD.md#73-starting-arnika-on-the-interval-boundary)).
- IPsec lane: IKEv2 with ML-KEM-768 (RFC 9370) plus an RFC 8784 PPK that is
  arnika's HKDF-SHA3-256 over the QKD key and the PQC-HPKE key. Rosenpass no
  longer takes part in it.
- The strongSwan VICI key writer implements upstream's one-method port,
  `SetPSK(psk []byte) error`, as the package `repositories/swanvici`, wired by
  `wire_strongswan_vici.go` under the `strongswan_vici` build tag.
  Invalidation moved into arnika's `KeyWriterService`. The text of the
  adapter's log lines is unchanged.
- `GET /api/wg/{node}` reports `wg1` under `data_tunnel`, next to the existing
  `wg0` fields, and a `psk_source` for each. Each node's sample is cached for
  `WG_SHOW_TTL_S` (5 s by default), since it now costs two `docker exec`s.
- The documentation describes the new lanes throughout, re-analyses the
  SP 800-227 position of the new PQC input (not called approved), records what
  commit `3e02741` is expected to do to the IPsec lane's rotation race (move
  the exposed intervals, not remove them; not yet measured), records
  strongSwan 6.1.0 as the IPsec lane's security floor (CVE-2026-78133), and
  adds ANSSI's IPsec technical sheet (ANSSI-FT-117) to the threat model.
- The WebUI frontend package reports version 0.2.0.

### Added

- `WG1_ALICE_IP`, `WG1_BOB_IP`, `WG1_LISTEN_PORT_ALICE` and
  `WG1_LISTEN_PORT_BOB` for the `wg1` interface, and `WG1_CHARLIE_IP` and
  `WG1_LISTEN_PORT_CHARLIE` (defaults `10.0.1.3` and `51832`, in
  `docker-compose.multihop.yml`) for the charlie leg's
  ([`docs/BUILD.md`](docs/BUILD.md#72-arnika-and-the-two-wireguard-interfaces)).
- `scripts/ppk_race_report.py`, which applies the counting rules of the
  planned before/after measurement to the IPsec nodes' logs at either pin:
  it counts PPK rotations and authentication failures, gives each failure one
  class, breaks the invalidation writes down by the arnika message that
  triggered them, prints the offset between the two nodes' interval
  boundaries over time, each PRIMARY's KMS fetch time, the `key_id`s that
  arrived before the receiver's own boundary and any tick whose interval
  numbers differ or whose two ends hold the same role, keeps a per-tick
  series of these in its JSON output, and compares two arms with an exact
  binomial test
  ([`docs/vici-ppk.md`](docs/vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race)).
- The `/vpn` page counts the WireGuard peers with a recent handshake beside
  those that ever completed one, and its WireGuard status badge follows the
  recent handshakes, since a set PSK is not evidence that a daemon keyed the
  tunnel and a handshake record stays after the two ends diverge onto
  different keys.
- The node entrypoints check their input before arnika sees it: `PQC_ENABLED`
  must be exactly `true` or `false`, and the WireGuard entrypoint accepts
  `ARNIKA_INTERVAL` only in whole hours, minutes and seconds. Host tests run
  these checks under bash rather than matching their spelling, and a host
  test ties the one-initiator Rosenpass behaviour to the pinned rosenpass
  commit.
- `CITATION.cff` and this changelog.

### Removed

- `PQC_PSK_FILE` and the `pqc-psk-*` volumes: the pinned arnika no longer
  reads a PQC key from a file.

### Security

- The node entrypoints refuse an `ARNIKA_PSK` shorter than 32 bytes or equal
  to the placeholder in `.env.example`.
- Every `wg0` and `wg1` peer is created with a random placeholder PSK that
  only its own node knows, so neither tunnel completes a handshake until
  arnika or Rosenpass has installed the same key on both ends. A `preshared
  key` line on a peer is therefore no longer evidence that either daemon wrote
  it; a completed handshake is.
- When Rosenpass exits, its sidecar installs a random PSK on every `wg1` peer
  and starts it again, so `wg1` fails closed instead of keeping its last key.
- Not a fix, but disclosed: arnika runs without `CAP_IPC_LOCK`, so its key
  material may reach swap ([`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)).

## [0.1.0] - 2026-09-26

The repository as it stood at `94eb164`, tagged afterwards so that the change
above has a baseline. It collects the work recorded in
[`docs/phases.md`](docs/phases.md) from the first phases to the public-demo
hardening of 2026-09-26.

### Added

- A BB84 key-management entity behind the ETSI GS QKD 014 REST API, with seven
  selectable simulator backends (QuTiP, SimQN, SeQUeNCe, CV-QKD, TNO,
  composite and a QKDNetSim proxy), a decoy-state key-rate model with the
  Lim et al. finite-key analysis, and all tunables in
  `config/qkd_params.yaml` (Phase 8).
- The WireGuard lane: arnika, pinned to `3a8cc13` on upstream `main`, fusing
  the QKD key with Rosenpass's output file through HKDF-SHA3-256 into the
  `wg0` preshared key.
- The IPsec lane: strongSwan 6.1.0 with IKEv2, ECP-256 plus ML-KEM-768
  (RFC 9370), and the fused key delivered as an RFC 8784 PPK by a Go VICI key
  writer for arnika (Phase 9).
- The multi-hop trusted-node overlay with a relay node, `charlie`.
- The WebUI: fourteen routes, among them the client-side `/e2e` (Phase 10),
  `/paper-flow` (Phase 14), `/bb84` with Worker, WASM, WebGL2 and WebGPU tiers,
  and `/protocol-lab`, with per-page exports (Phase 12).
- An ETSI GS QKD 004 V2.1.1 endpoint in the KME over this project's own HTTP
  binding, off by default (2026-09-25).
- A crypto-agility matrix over ML-KEM and HQC, and ML-DSA and SLH-DSA.
- Public-demo hardening (2026-09-25 and 2026-09-26): redacted container logs,
  live simulator overrides made opt-in, allow-lists on the Docker-backed
  routes, a rate limit on mutating requests and bounded exports.

[0.2.0]: https://github.com/thedaemon-wizard/pqc-qkd-HybridNetwork/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/thedaemon-wizard/pqc-qkd-HybridNetwork/tree/v0.1.0
