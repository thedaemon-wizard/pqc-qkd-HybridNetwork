# =====================================================================
# qkdnetsim-kme — Flask ETSI GS QKD 014 facade (kme_facade.py). The image also
#                 compiles NS-3 v3.46 + qkdnetsim, which is NOT executed.
#
# Build stages:
#   1) builder : compile NS-3 + qkdnetsim from source
#   2) runtime : ubuntu:22.04 with the build output and the Flask facade
#
# The runtime entrypoint is kme_facade.py, a Flask app that mints keys with
# `secrets.token_bytes`. It is used by the `composite_sim_to_net` and
# `qkdnetsim_proxy` backends as a second, independently written ETSI 014
# server, which exercises bb84-kme's client code against a server it was not
# written alongside. What that checks is the REST contract, never key material.
#
# Nothing runs tests/test_etsi014_contract.py against this container. CI points
# that suite at bb84-kme-a and bb84-kme-b, no CI job or Makefile target starts
# the `crossvalidate` overlay, and the facade implements only the GET forms, so
# the suite's POST-form cases would get 405 here. This header used to name that
# suite as the one exercising the image; an earlier version named a
# cross-validation test that has never existed. See the note on the build step
# below for the same shape one layer down, where a failed NS-3 compile still
# produced a green image because the healthcheck probed a Flask route.
#
# NOTE: First build is ~10-15 min. Subsequent builds are cached. CI does not
# build this image, so whether it still builds is checked only by hand (last
# built and started 2026-09-26: /health and the ETSI 014 status call answer).
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
# qkdnetsim's installation steps (its README, steps 4-5) patch NS-3's own
# gnuplot module before configuring: model/qkd-graph.cc uses
# Gnuplot2dDataset::FILLEDCURVE, which exists only after that patch. Without it
# the build stops at
#
#     error: 'FILLEDCURVE' is not a member of 'ns3::Gnuplot2dDataset'
#
# which is how this image failed when it was last built by hand (2026-09-26).
# `--check` first, so a patch that no longer applies to the pinned NS-3 fails
# here with git's message rather than as a compile error later.
RUN git apply --check contrib/qkdnetsim/patches/gnuplot_h.patches && \
    git apply --check contrib/qkdnetsim/patches/gnuplot_cc.patches && \
    git apply contrib/qkdnetsim/patches/gnuplot_h.patches && \
    git apply contrib/qkdnetsim/patches/gnuplot_cc.patches
# Configure with examples + the qkdnetsim module.
#
# The three routing modules are not optional. qkdnetsim's model headers include
# `ns3/aodv-packet.h`, `ns3/dsdv-packet.h` and `ns3/olsr-header.h`, so a module
# list without them fails with
#
#     fatal error: ns3/dsdv-packet.h: No such file or directory
#
# and this image did exactly that until 2026-08-28 -- meaning the whole
# `crossvalidate` profile was unbuildable, which nothing in the repository said.
# `dsdv` is the one the compiler reaches first; adding it alone just moves the
# error to the next header, so all three go in together.
#
# Note WHERE it surfaced: `configure` succeeded and the error appeared four
# files into `ns3 build`, because omitting a dependency is not a configure
# error. So the trailing `|| true` below buys nothing here and would swallow a
# genuine configure failure; it survives only because the build step runs under
# `pipefail` and fails the image when NS-3 does not compile. That guard is what
# turned this from a silently NS-3-less image into a red build.
RUN ./ns3 configure --enable-examples --enable-modules='core;network;internet;applications;point-to-point;mobility;aodv;dsdv;olsr;qkdnetsim' 2>&1 | tail -n 5 || true

# Build the qkdnetsim module library.
#
# `./ns3 build qkdnetsim` builds the module target, not the qkdnetsim example
# programs, and nothing in the runtime stage invokes an NS-3 binary either. The
# examples also need modules the list above leaves out (netanim, flow-monitor,
# internet-apps and, for the emulation variants, fd-net-device), so a binary
# built from them should not be assumed to exist in this image.
#
# `pipefail` is required for the `||` below to mean anything. Without it this
# stage runs under `/bin/sh -c` and takes the PIPELINE's status, which is
# `tail`'s and therefore always 0 -- so the fallback was unreachable dead code
# AND a failed compile produced a green image, whose runtime stage then copied
# a build directory with no NS-3 libraries. The healthcheck probes a Flask
# `/health` that never touches NS-3, so nothing downstream noticed. Same
# pattern that was removed from services/bb84-kme/Dockerfile.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN ./ns3 build qkdnetsim 2>&1 | tail -n 20 || \
    ./ns3 build 2>&1 | tail -n 30

# =====================================================================
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip libxml2 libgtk-3-0 \
        libcrypto++8 uuid libsqlite3-0 libboost-all-dev \
        ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*
COPY services/qkdnetsim-kme/requirements.txt /opt/qkdnetsim-kme/requirements.txt
RUN pip install --no-cache-dir -r /opt/qkdnetsim-kme/requirements.txt

COPY --from=builder /src/ns-3-dev/build /opt/ns3/build
COPY --from=builder /src/ns-3-dev/contrib/qkdnetsim /opt/ns3/contrib/qkdnetsim
ENV LD_LIBRARY_PATH=/opt/ns3/build/lib

COPY services/qkdnetsim-kme/kme_facade.py /opt/qkdnetsim-kme/kme_facade.py
WORKDIR /opt/qkdnetsim-kme
# Port 80 only. 81 was also exposed for an ETSI 004 endpoint that was
# withdrawn; nothing listens there.
EXPOSE 80
HEALTHCHECK --interval=5s --timeout=3s --retries=20 --start-period=10s \
    CMD curl -sf http://localhost:80/health || exit 1

CMD ["python3", "kme_facade.py"]
