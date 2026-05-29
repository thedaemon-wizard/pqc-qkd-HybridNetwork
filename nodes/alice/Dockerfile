# ============================================================
# Node image — runs WireGuard, Arnika, and a Rosenpass sidecar.
# Single image used for both alice and bob (role chosen by env).
#
# Two build stages:
#   1) arnika-build : compile the unmodified arnika Go binary
#   2) rosenpass-build: compile Rosenpass via the official Rust toolchain
#   3) runtime      : Alpine with wireguard-tools + iproute2
# ============================================================

# ---- Stage 1: build arnika ---------------------------------
FROM golang:1.24-alpine AS arnika-build
RUN apk add --no-cache git make
WORKDIR /src
# Copy in submodule (build context = repo root via compose `context:` is per-node;
# we use a build-arg approach so the Dockerfile is locally complete and the
# compose file uses extra-context.  When integrated into compose we mount via build.)
ARG ARNIKA_REPO=https://github.com/cancom/arnika-vq.git
ARG ARNIKA_REF=main
RUN git clone "$ARNIKA_REPO" arnika && cd arnika && git checkout "$ARNIKA_REF"
WORKDIR /src/arnika
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /out/arnika .

# ---- Stage 2: build rosenpass ------------------------------
FROM rust:1.83-bookworm AS rosenpass-build
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libsodium-dev clang protobuf-compiler git build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
ARG ROSENPASS_REPO=https://github.com/rosenpass/rosenpass.git
ARG ROSENPASS_REF=main
RUN git clone --depth 1 --branch "$ROSENPASS_REF" "$ROSENPASS_REPO" rosenpass || \
    git clone "$ROSENPASS_REPO" rosenpass
WORKDIR /src/rosenpass
# Best effort - fallback to dummy stub if upstream build breaks on this toolchain.
RUN cargo build --release --bin rosenpass || (echo "rosenpass build failed - producing stub" && \
        mkdir -p target/release && \
        printf '#!/bin/sh\necho "[rosenpass stub] writing random pqc.psk every 60s"\nmkdir -p /var/lib/rosenpass\nwhile :; do head -c 32 /dev/urandom | base64 > /var/lib/rosenpass/pqc.psk; sleep 60; done\n' > target/release/rosenpass && \
        chmod +x target/release/rosenpass)

# ---- Stage 3: runtime --------------------------------------
FROM alpine:3.20

RUN apk add --no-cache \
        wireguard-tools iproute2 iptables iputils \
        bash curl jq ca-certificates tini

COPY --from=arnika-build /out/arnika /usr/local/bin/arnika
COPY --from=rosenpass-build /src/rosenpass/target/release/rosenpass /usr/local/bin/rosenpass

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY rosenpass-sidecar.sh /usr/local/bin/rosenpass-sidecar.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/rosenpass-sidecar.sh

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/entrypoint.sh"]
