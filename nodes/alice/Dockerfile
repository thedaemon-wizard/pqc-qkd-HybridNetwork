# ============================================================
# Node image — runs WireGuard, Arnika, and a Rosenpass sidecar.
# Single image used for both alice and bob (role chosen by env).
#
# Build context is the REPO ROOT (see docker-compose.yml:
#   build: { context: ., dockerfile: nodes/alice/Dockerfile })
# so the vetted local submodules are available to COPY — we do NOT
# clone anything from the network at build time (reproducible/offline,
# license-vetted: arnika Apache-2.0, rosenpass MIT/Apache-2.0).
#
# Three build stages:
#   1) arnika-build    : compile arnika from submodules/arnika
#   2) rosenpass-build : compile REAL rosenpass from submodules/rosenpass (v0.2.3)
#   3) runtime         : Debian (glibc) with wireguard-tools + iproute2
#
# NOTE: the runtime is Debian (glibc), not Alpine (musl), because the
# rosenpass binary links glibc + libsodium; a glibc binary cannot run on
# a musl Alpine base (this previously caused a silent fallback). There is
# NO urandom stub anymore — the post-quantum half of HKDF(QKD‖PQC) is a
# genuine rosenpass exchange.
# ============================================================

# ---- Stage 1: build arnika from the local submodule --------
# Go 1.26 is required: arnika hardens key material with runtime/secret, which
# does not exist in earlier toolchains and is gated behind a GOEXPERIMENT.
# CGO_ENABLED / GOEXPERIMENT mirror upstream's own Makefile build vars.
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
# arnika-project/arnika#42 (`9d44332`, 2026-08-24); the pin now contains it and
# the patch file is gone. The grep stays: it is what makes a future submodule
# bump to a revision WITHOUT the fix fail the build instead of quietly shipping
# an image whose PSK installation breaks only on multi-peer interfaces.
RUN grep -q "found := false" repositories/wireguard-netlink.go

# arnika#44, still OPEN. `kmsRequest` closed the response body BEFORE deciding
# whether to retry was the intent, but the close sat AFTER that decision while
# `res` kept its value -- so a non-OK status on the final attempt carried a
# CLOSED body out of the loop and `io.ReadAll` failed with "http: read on
# closed response body". Compounding it, a 4xx/5xx is a successful HTTP
# transaction, so `err` was nil and nothing distinguished "the KMS refused"
# from a real fetch.
#
# Carried here exactly as the peer-lookup fix above was carried until arnika#42
# merged. Delete the patch when #44 merges and the pin moves; keep the grep.
COPY nodes/alice/0001-arnika-do-not-read-a-closed-response-body.patch /tmp/kms.patch
# `rm -f .git` first: a submodule's .git is a FILE pointing at
# ../../.git/modules/..., which does not exist in the image, and `git apply`
# fails with "not a git repository" before it looks at the patch. The pointer
# is dangling here regardless. Measured -- the build failed on exactly this.
RUN rm -f .git && git apply /tmp/kms.patch && rm /tmp/kms.patch
# Asserts the patched property, so a submodule bump to a revision without the
# fix fails the build instead of silently shipping the old behaviour.
RUN grep -q "KMS did not return" repositories/kms.go
RUN CGO_ENABLED=0 GOEXPERIMENT=runtimesecret \
    go build -trimpath -ldflags "-w -s" -o /out/arnika .

# ---- Stage 2: build REAL rosenpass from the local submodule -
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
# Deterministic/offline. Lines 13 and 36 already said v0.2.3; this one said
# v0.2.2, so the file disagreed with itself about what it builds.
COPY submodules/rosenpass /src/rosenpass
WORKDIR /src/rosenpass
# Real build — oqs-sys (Kyber) + libsodium. No fallback stub: if this fails
# the image build fails loudly rather than shipping fake random PSKs.
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
