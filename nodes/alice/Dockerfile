# ============================================================
# Node image: runs two WireGuard interfaces, arnika and Rosenpass.
# Single image used for alice, bob and charlie (role chosen by env).
#
# Build context is the REPO ROOT (see docker-compose.yml:
#   build: { context: ., dockerfile: nodes/alice/Dockerfile })
# so the vetted local submodules are available to COPY. We do NOT
# clone anything from the network at build time (reproducible/offline,
# license-vetted: arnika Apache-2.0, rosenpass MIT/Apache-2.0).
#
# What runs in the container (nodes/alice/entrypoint.sh):
#   wg0 : hop tunnel. arnika writes its PSK = HKDF-SHA3-256(QKD key || PQC-HPKE
#         key). arnika agrees the PQC-HPKE half with its peer over the arnika
#         UDP channel, so no file carries PQC key material.
#   wg1 : end-to-end data tunnel, carried inside wg0. Rosenpass writes its PSK
#         through its own WireGuard output (`wireguard wg1 <peer key>`), and the
#         Rosenpass exchange itself also runs inside wg0.
#
# Three build stages:
#   1) arnika-build    : compile arnika from submodules/arnika
#   2) rosenpass-build : compile REAL rosenpass from submodules/rosenpass (v0.2.3)
#   3) runtime         : Debian (glibc) with wireguard-tools + iproute2
#
# Note: the runtime is Debian (glibc), not Alpine (musl), because the
# rosenpass binary links glibc + libsodium; a glibc binary cannot run on
# a musl Alpine base (this previously caused a silent fallback). There is
# NO urandom stub: the wg1 PSK comes from a genuine Rosenpass exchange.
# ============================================================

# ---- Stage 1: build arnika from the local submodule --------
# Go 1.26 is required: arnika hardens key material with runtime/secret, which
# does not exist in earlier toolchains and is gated behind a GOEXPERIMENT.
# CGO_ENABLED / GOEXPERIMENT mirror upstream's own Makefile build vars.
#
# The pin is f4cf9ba (2026-09-24), the head of the OPEN, unmerged upstream PR
# arnika-project/arnika#51. It will be re-pinned to the merge commit once #51
# merges. The layout moved in that PR: one package per adapter under
# repositories/, and the wiring files are wire_*.go. The assertions below
# name the new paths.
FROM golang:1.26-bookworm AS arnika-build
WORKDIR /src
# Vendored, license-vetted upstream (arnika-project/arnika, Apache-2.0).
COPY submodules/arnika /src/arnika
WORKDIR /src/arnika
# Upstream's peer lookup in SetPSK used to return "not found" on the first
# NON-matching peer, so it only worked when the interface had exactly one peer.
# A node with two neighbours then installed no QKD-derived PSK -- and because
# WireGuard is unaffected, the tunnel still came up and passed traffic, so the
# loss of post-quantum protection was silent.
#
# This was carried here as a local patch until upstream merged the same fix as
# arnika-project/arnika#42 (`9d44332`, 2026-08-24); the pin contains it. The
# grep stays: it is what makes a future submodule bump to a revision WITHOUT
# the fix fail the build instead of quietly shipping an image whose PSK
# installation breaks only on multi-peer interfaces. Since #51 the writer lives
# in its own package, repositories/wgnetlink.
RUN grep -q "found := false" repositories/wgnetlink/netlink.go

# arnika#44 and #49, both MERGED 2026-09-02, and the pin contains them. The
# local patch that carried them is gone; this assertion is what the lifecycle
# note in that patch said to keep.
#
# It targets the exported sentinel error that callers branch on with
# `errors.Is`, because telling "KMS did not deliver a key" apart from other
# failures is the point of the change. The previous rationale was that the
# identifier survives while the message text may change; #51 then renamed the
# identifier (ErrKMSUnavailable in the old repositories/kms.go became
# ErrUnavailable in the new package repositories/kms) and kept the text. So
# neither half is stable across a restructuring, and this line has to be
# re-checked on every bump. A revision without the sentinel fails the build
# instead of silently shipping an arnika whose exhausted retry loop reports 503
# and 403 identically.
RUN grep -q "^var ErrUnavailable = " repositories/kms/kms.go

# The PQC half of the wg0 PSK now comes from arnika's own HPKE key agreement
# (repositories/pqchpke), switched by PQC_ENABLED. The file-based handover
# (PQC_PSK_FILE, fed by Rosenpass) is gone from the pin, and the compose files
# no longer set it. A bump to a revision without the package or without the
# PQC_ENABLED switch would leave MODE=QkdAndPqcRequired with no PQC source, so
# every rotation would invalidate the tunnel: fail the build instead.
RUN test -d repositories/pqchpke \
    && grep -q '"PQC_ENABLED"' config/config.go
RUN CGO_ENABLED=0 GOEXPERIMENT=runtimesecret \
    go build -trimpath -ldflags "-w -s" -o /out/arnika .

# ---- Stage 2: build REAL rosenpass from the local submodule -
# Rosenpass keys wg1, the end-to-end data tunnel. It no longer feeds arnika.
#
# rust 1.90, not 1.83. rosenpass v0.2.3 is itself edition 2021, but its
# dependency graph pulls clap_lex 1.1.0, which declares edition 2024 --
# stabilised in Rust 1.85. Cargo 1.83 fails the manifest parse outright:
#   feature `edition2024` is required ... not stabilized in this version
# Bump this together with the submodule pin.
FROM rust:1.90-bookworm AS rosenpass-build
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libsodium-dev clang cmake git build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Vendored, pinned to tag v0.2.3 = 512fe426 (MIT / Apache-2.0).
# Deterministic/offline.
#
# The entrypoint relies on how this version behaves, not only on how it is
# configured: only the end of a pair with the lower wg0 address is given an
# endpoint, and v0.2.3 never initiates towards a peer without one.
# tests/test_rosenpass_responder_never_initiates.py pins this commit and names
# what to re-read in protocol.rs and app_server.rs before moving it.
COPY submodules/rosenpass /src/rosenpass
WORKDIR /src/rosenpass
# Real build -- oqs-sys (Kyber) + libsodium. No fallback stub: if this fails
# the image build fails loudly rather than shipping fake random PSKs.
#
# Which liboqs this links is NOT the submodules/liboqs pin. rosenpass's
# Cargo.lock resolves oqs-sys 0.8.0, which vendors liboqs 0.8.0 (2023) and
# builds it statically into this binary. That release predates the liboqs
# 0.9.1, 0.9.2 and 0.10.1 security releases for non-constant-time Kyber code,
# so fixes tracked against the liboqs pin do not reach this lane. Moving it
# means changing rosenpass's own dependency, which is an upstream change: its
# Classic McEliece parameters changed in liboqs 0.9.0, so a local bump would
# break wire compatibility with every other rosenpass peer.
RUN cargo build --release --bin rosenpass

# ---- Stage 3: runtime (Debian / glibc) --------------------
FROM debian:bookworm-slim

# wireguard-go is the USERSPACE data plane, for hosts whose kernel has no
# wireguard module. It is what `wg-quick` falls back to by default:
#
#   cmd "${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}" "$INTERFACE"
#
# so installing it at /usr/bin/wireguard-go makes the fallback work with no
# environment variable at all. Previously nothing provided a userspace
# implementation, and wg-quick exits when the module is absent AND the binary
# is missing -- precisely the case the fallback exists for.
#
# It is packaged in bookworm main: 2.5 MB installed, depends only on libc6.
# An earlier check concluded it was not packaged; that misread the
# `Installed: (none)` line of `apt-cache policy` as absence while the
# `Candidate:` line beneath it said otherwise. Vendoring boringtun was
# considered and is strictly worse here -- not in Debian at all, its own README
# says not to pin to master (which submodules do), its binary is named
# `boringtun-cli` so the wg-quick default breaks, and dropping privileges
# forces WG_SUDO=1 plus CAP_NET_ADMIN.
#
# wireguard-tools also provides `wg`, which rosenpass runs itself to install
# each wg1 key (`wg set wg1 peer <key> preshared-key /dev/stdin`). iproute2
# provides `ss`, which the entrypoint uses to confirm Rosenpass has bound its
# UDP socket on the wg0 address before starting arnika.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-go \
        wireguard-tools iproute2 iptables iputils-ping \
        bash curl jq ca-certificates tini libsodium23 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=arnika-build /out/arnika /usr/local/bin/arnika
COPY --from=rosenpass-build /src/rosenpass/target/release/rosenpass /usr/local/bin/rosenpass

COPY nodes/alice/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY nodes/alice/rosenpass-sidecar.sh /usr/local/bin/rosenpass-sidecar.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/rosenpass-sidecar.sh

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/entrypoint.sh"]
