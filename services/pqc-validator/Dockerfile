# =====================================================================
# pqc-validator — runs the same NIST PQC test vectors through both
# liboqs (production) and PQClean (reference) and asserts byte-equality.
#
# liboqs is built HERE, from the vendored submodule, rather than being
# downloaded by liboqs-python at first import.
#
# The previous image installed no C liboqs at all and relied on
# liboqs-python's auto-install fallback, which git-clones and compiles
# liboqs the first time `import oqs` runs. That had three problems:
#
#   1. It made image startup depend on the network and on GitHub being
#      reachable, inside a container that is otherwise self-contained.
#   2. The liboqs version was implicit -- whatever liboqs-python happened
#      to default to -- while the repository separately vendors and
#      documents a pinned liboqs submodule that the image never used.
#   3. It broke. liboqs-python 0.16.0's auto-install fails with
#      "Error installing liboqs / No oqs shared libraries found", so the
#      image could not be built from a clean checkout at all.
#
# liboqs-python loads any liboqs it can already find and only falls back to
# installing one when that load fails (see _load_liboqs in oqs.py). Building
# it here therefore disables the fallback path entirely.
#
# VERSION COUPLING: liboqs-python performs NO version check on a library it
# finds -- a mismatch surfaces as a missing ctypes symbol or a crash, not a
# clear error. So the two are pinned to the SAME version on purpose:
#
#     submodules/liboqs            -> tag 0.16.0
#     liboqs-python (requirements) -> ==0.16.0
#
# Bump them together, and re-run the smoke test at the end of this file.
# =====================================================================
FROM python:3.12-slim AS liboqs-build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Vendored, pinned, and offline: the build context is the repository root.
COPY submodules/liboqs /src/liboqs

# Shared library, because liboqs-python loads it through ctypes.
# BUILD_TESTING=OFF drops the KAT binaries the validator does not use.
RUN cmake -S /src/liboqs -B /build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=ON \
        -DOQS_BUILD_ONLY_LIB=ON \
        -DCMAKE_INSTALL_PREFIX=/opt/liboqs && \
    cmake --build /build --parallel && \
    cmake --install /build

# =====================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# liboqs-python looks under $OQS_INSTALL_PATH/lib and /lib64 before it
# considers installing anything. Pointing it at the build above is what
# keeps the auto-install path dormant.
ENV OQS_INSTALL_PATH=/opt/liboqs
ENV LD_LIBRARY_PATH=/opt/liboqs/lib:/opt/liboqs/lib64

# curl for HEALTHCHECK; libssl3 is liboqs' only runtime link dependency.
# No compiler or cmake in the final image -- the build stage kept them out.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl libssl3 && rm -rf /var/lib/apt/lists/*

COPY --from=liboqs-build /opt/liboqs /opt/liboqs

WORKDIR /app

# Lightweight Python stack
COPY services/pqc-validator/requirements.txt .
RUN pip install -r requirements.txt

# Fail the BUILD, not the first request, if the bindings cannot reach the
# library or the algorithms the validator needs are missing. Without this the
# image builds cleanly and dies at runtime, which is how the previous
# breakage reached a deployed host.
RUN python -c "\
import oqs;\
kems = oqs.get_enabled_kem_mechanisms();\
sigs = oqs.get_enabled_sig_mechanisms();\
assert 'ML-KEM-768' in kems, 'ML-KEM-768 missing';\
assert 'ML-DSA-65' in sigs, 'ML-DSA-65 missing';\
k = oqs.KeyEncapsulation('ML-KEM-768');\
pk = k.generate_keypair();\
ct, ss1 = k.encap_secret(pk);\
assert k.decap_secret(ct) == ss1, 'ML-KEM-768 roundtrip mismatch';\
s = oqs.Signature('ML-DSA-65');\
spk = s.generate_keypair();\
assert s.verify(b'pqc-validator build check', s.sign(b'pqc-validator build check'), spk), 'ML-DSA-65 verify failed';\
print('liboqs', oqs.oqs_version(), '/ liboqs-python', oqs.oqs_python_version(), '- ML-KEM-768 and ML-DSA-65 OK')"

# We mount /submodules/PQClean at runtime via compose volume to avoid
# baking the whole 200MB into the image.
COPY services/pqc-validator/app /app/app

EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD curl -sf http://localhost:8090/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
