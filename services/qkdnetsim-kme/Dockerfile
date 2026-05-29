# =====================================================================
# qkdnetsim-kme — NS-3 v3.46 + qkdnetsim contrib (ETSI GS QKD 014 reference)
#
# Build stages:
#   1) builder : compile NS-3 + qkdnetsim from source
#   2) runtime : ubuntu:22.04 with just the binaries + minimal libs
#
# This image is used by the `composite_sim_to_net` backend and by
# tests/test_etsi014_crossvalidate.py to cross-check the Python KME
# against the reference C++ implementation.
#
# NOTE: First build is ~10-15 min. Subsequent builds are cached.
# =====================================================================
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git wget unzip \
        gcc g++ make cmake ninja-build pkg-config \
        python3 python3-dev python3-pip \
        libxml2 libxml2-dev libgtk-3-0 libgtk-3-dev \
        libcrypto++-dev libcrypto++-doc libcrypto++-utils uuid-dev \
        libboost-all-dev flex bison sqlite sqlite3 libsqlite3-dev \
        gdb tcpdump iproute2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

ARG NS3_REF=ns-3.46
RUN git clone --depth 1 -b ${NS3_REF} https://gitlab.com/nsnam/ns-3-dev.git ns-3-dev

# Copy in the qkdnetsim submodule (build context = repo root, set by compose)
COPY submodules/qkdnetsim /src/ns-3-dev/contrib/qkdnetsim

WORKDIR /src/ns-3-dev
# Configure with examples + the qkdnetsim module
RUN ./ns3 configure --enable-examples --enable-modules='core;network;internet;applications;point-to-point;mobility;qkdnetsim' 2>&1 | tail -n 5 || true

# Build — the qkdnetsim ETSI 014 example produces a binary we can invoke
RUN ./ns3 build qkdnetsim 2>&1 | tail -n 20 || \
    ./ns3 build 2>&1 | tail -n 30

# =====================================================================
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip libxml2 libgtk-3-0 \
        libcrypto++8 uuid libsqlite3-0 libboost-all-dev \
        ca-certificates curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir flask==3.0.3 pyyaml==6.0.2

COPY --from=builder /src/ns-3-dev/build /opt/ns3/build
COPY --from=builder /src/ns-3-dev/contrib/qkdnetsim /opt/ns3/contrib/qkdnetsim
ENV LD_LIBRARY_PATH=/opt/ns3/build/lib

COPY services/qkdnetsim-kme/kme_facade.py /opt/qkdnetsim-kme/kme_facade.py
WORKDIR /opt/qkdnetsim-kme
EXPOSE 80 81
HEALTHCHECK --interval=5s --timeout=3s --retries=20 --start-period=10s \
    CMD curl -sf http://localhost:80/health || exit 1

CMD ["python3", "kme_facade.py"]
