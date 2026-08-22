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

RUN apt-get update && apt-get install -y --no-install-recommends \
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
