# =====================================================================
# strongSwan IPsec/IKEv2 node for the QKD/PQC lane.
#
#   * RFC 9370 hybrid key exchange : ECP-256 + ML-KEM-768 (ke1_mlkem768)
#   * RFC 9242 IKE_INTERMEDIATE    : carries the ML-KEM payloads, encrypted
#                                    and therefore fragmentable
#   * RFC 8784 PPK                 : the arnika-derived HKDF(QKD || PQC) key,
#                                    injected natively over the VICI socket
#
# Base image: Debian trixie, because its OpenSSL is >= 3.5 and strongSwan's
# `openssl` plugin sources ML-KEM from it (strongSwan >= 6.0.2). The previous
# bookworm base shipped OpenSSL 3.0, which has no ML-KEM at all -- so the
# RFC 9370 proposal could never have negotiated no matter how it was spelled.
# The self-contained `ml` plugin is ALSO built, as the fallback provider.
#
# liboqs is deliberately NOT used here: upstream strongSwan has no oqs plugin
# (that was a fork-only experiment, removed at the 6.0.0 cut), so the previous
# liboqs build stage contributed nothing but build time and a broken
# COPY of a lib64 directory that liboqs never creates on Debian.
# =====================================================================

# ---- Stage 1: strongSwan ----------------------------------------------
FROM debian:trixie-slim AS strongswan-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates build-essential autoconf automake libtool \
        bison flex gperf pkg-config libssl-dev libcurl4-openssl-dev \
        libgmp-dev libldns-dev libxml2-dev libgcrypt20-dev \
    && rm -rf /var/lib/apt/lists/*

# ML-KEM via the openssl plugin needs OpenSSL >= 3.5. Fail at build time rather
# than at handshake time if the base image regresses.
RUN set -eu; \
    v=$(openssl version | awk '{print $2}'); \
    major=${v%%.*}; rest=${v#*.}; minor=${rest%%.*}; \
    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 5 ]; }; then \
        echo "FATAL: OpenSSL $v < 3.5, the openssl plugin cannot provide ML-KEM" >&2; \
        exit 1; \
    fi; \
    echo "OpenSSL $v provides ML-KEM"

# Pinned to 6.0.7 (2026-06-08), which fixes CVE-2026-47895 -- a double-free in
# identity cloning, reachable through exactly the load-shared `owners` path this
# node uses on every key rotation.
COPY submodules/strongswan /src/strongswan
WORKDIR /src/strongswan
RUN ./autogen.sh && \
    ./configure \
        --prefix=/usr/local \
        --sysconfdir=/etc \
        --enable-openssl \
        --enable-ml \
        --enable-vici \
        --enable-swanctl \
        --enable-systemd=no \
        --disable-static \
        --enable-shared && \
    make -j"$(nproc)" && \
    make install

# The `ml` plugin is opt-in (configure.ac: ARG_ENABL_SET([ml], ...)) and is not
# among the 25 default plugins, so verify it actually got built.
RUN test -f /usr/local/lib/ipsec/plugins/libstrongswan-ml.so \
    || { echo "FATAL: ml plugin was not built" >&2; exit 1; }

# ---- Stage 2: arnika + the strongSwan VICI key-writer ------------------
FROM golang:1.26-bookworm AS arnika-build
COPY submodules/arnika /src/arnika
COPY services/arnika-vici /src/arnika-vici
# arnika#44 (OPEN), same patch and same reason as nodes/alice/Dockerfile.
# Applied to the submodule copy BEFORE build.sh assembles its working tree,
# because build.sh copies `$ARNIKA_SRC`/. wholesale -- patching afterwards
# would be patching a tree that has already been consumed.
COPY nodes/alice/0001-arnika-do-not-read-a-closed-response-body.patch /tmp/kms.patch
# `rm -f .git` first: a submodule's .git is a FILE pointing at
# ../../.git/modules/..., which does not exist in the image, and `git apply`
# fails with "not a git repository" before it looks at the patch. The pointer
# is dangling here regardless. Measured -- the build failed on exactly this.
RUN cd /src/arnika && rm -f .git && git apply /tmp/kms.patch && rm /tmp/kms.patch \
    && grep -q "ErrKMSUnavailable" repositories/kms.go
RUN sh /src/arnika-vici/build.sh /src/arnika /src/arnika-vici /out/arnika

# ---- Stage 3: runtime --------------------------------------------------
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libssl3 libgmp10 libcurl4 libldns3 libxml2 \
        libgcrypt20 iproute2 iptables iputils-ping bash curl jq tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=strongswan-builder /usr/local /usr/local
COPY --from=strongswan-builder /etc/strongswan.conf /etc/strongswan.conf
COPY --from=arnika-build /out/arnika /usr/local/bin/arnika

ENV LD_LIBRARY_PATH=/usr/local/lib

# Building a plugin is not enough -- charon only loads what the `load` line
# names (upstream issue #2690: "ML_KEM algorithms not working" is this exact
# mistake). `openssl` is listed before `ml` so OpenSSL 3.5 provides ML-KEM and
# `ml` acts as the fallback; first provider in load order wins.
COPY nodes/strongswan/strongswan.conf /etc/strongswan.conf
COPY nodes/strongswan/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY nodes/strongswan/swanctl.conf.tmpl /etc/swanctl/conf.d/pqcqkd.conf.tmpl

# swanctl reads /etc/swanctl/swanctl.conf and follows its includes; conf.d is
# not scanned on its own. strongSwan's `make install` only writes this file via
# an install-data-local rule that ends in `|| true`, so it is absent here --
# which made every --load-conns a silent no-op ("no connections found").
# The credential directories are created for the same reason.
RUN set -eu; \
    printf 'include conf.d/*.conf\n' > /etc/swanctl/swanctl.conf; \
    mkdir -p /etc/swanctl/x509 /etc/swanctl/x509ca /etc/swanctl/private \
             /etc/swanctl/pubkey /etc/swanctl/rsa /etc/swanctl/ecdsa \
             /var/run/strongswan; \
    chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 500/udp 4500/udp
# Debian trixie ships tini at /usr/bin/tini, not /sbin/tini as on bookworm.
# Asserted at build time so a base-image move cannot make the container
# fail only at `docker run`.
RUN test -x /usr/bin/tini || { echo "FATAL: tini not at /usr/bin/tini" >&2; exit 1; }
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/entrypoint.sh"]
