# =====================================================================
# strongSwan IPsec/IKEv2 with RFC 9370 ML-KEM hybrid key exchange.
#
# Three-stage build:
#   1) liboqs-builder    — compile liboqs into /opt/oqs
#   2) strongswan-builder— compile strongSwan with openssl plugin
#   3) runtime           — Alpine with binaries + arnika-vici-bridge
#
# RFC 9370 hybrid:
#   IKE proposal = aes256-sha256-modp2048-ml_kem_768
# =====================================================================

# ---------- Stage 1: liboqs ----------
FROM debian:12-slim AS liboqs-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake ninja-build gcc g++ libssl-dev pkg-config && \
    rm -rf /var/lib/apt/lists/*

COPY submodules/liboqs /src/liboqs
WORKDIR /src/liboqs
RUN cmake -S . -B build -GNinja \
        -DCMAKE_INSTALL_PREFIX=/opt/oqs \
        -DBUILD_SHARED_LIBS=ON \
        -DOQS_USE_OPENSSL=ON \
        -DOQS_DIST_BUILD=ON && \
    cmake --build build --parallel && \
    cmake --install build

# ---------- Stage 2: strongSwan ----------
FROM debian:12-slim AS strongswan-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git build-essential autoconf automake libtool \
        bison flex gperf pkg-config libssl-dev libcurl4-openssl-dev \
        libgmp-dev libldns-dev libxml2-dev libsystemd-dev libgcrypt20-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=liboqs-builder /opt/oqs /opt/oqs
ENV PKG_CONFIG_PATH=/opt/oqs/lib/pkgconfig:/opt/oqs/lib64/pkgconfig
ENV LD_LIBRARY_PATH=/opt/oqs/lib:/opt/oqs/lib64

COPY submodules/strongswan /src/strongswan
WORKDIR /src/strongswan
# Configure strongSwan with PQC-enabled openssl plugin and vici control socket
RUN ./autogen.sh && \
    ./configure \
        --prefix=/usr/local \
        --sysconfdir=/etc \
        --enable-openssl \
        --enable-vici \
        --enable-swanctl \
        --enable-systemd=no \
        --enable-monolithic=no \
        --disable-static \
        --enable-shared && \
    make -j"$(nproc)" 2>&1 | tail -n 20 && \
    make install 2>&1 | tail -n 10

# ---------- Stage 3: runtime ----------
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libssl3 libgmp10 libcurl4 libldns3 libxml2 \
        libgcrypt20 iproute2 iptables iputils-ping bash curl jq tini && \
    rm -rf /var/lib/apt/lists/*

COPY --from=liboqs-builder /opt/oqs/lib /opt/oqs/lib
COPY --from=liboqs-builder /opt/oqs/lib64 /opt/oqs/lib64
COPY --from=strongswan-builder /usr/local /usr/local
COPY --from=strongswan-builder /etc/swanctl /etc/swanctl
COPY --from=strongswan-builder /etc/strongswan.conf /etc/strongswan.conf

ENV LD_LIBRARY_PATH=/opt/oqs/lib:/opt/oqs/lib64:/usr/local/lib

COPY nodes/strongswan/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY nodes/strongswan/swanctl.conf.tmpl /etc/swanctl/conf.d/pqcqkd.conf.tmpl
COPY nodes/strongswan/arnika-vici-bridge.sh /usr/local/bin/arnika-vici-bridge.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/arnika-vici-bridge.sh && \
    mkdir -p /var/run/strongswan

EXPOSE 500/udp 4500/udp
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/entrypoint.sh"]
