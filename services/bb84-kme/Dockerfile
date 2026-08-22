# ============================================================
# BB84 KME — QuTiP simulator + ETSI GS QKD 014 REST API
# ============================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/bb84-kme/pyproject.toml services/bb84-kme/requirements.txt services/bb84-kme/constraints.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Editable installs of the heavy Phase 8 backends.  We do them inside the
# image so they fail fast at build time; volume-mount at runtime overlays
# the submodule source for live development.
COPY submodules/SimQN /opt/SimQN
COPY submodules/SeQUeNCe /opt/SeQUeNCe
COPY submodules/strawberryfields /opt/strawberryfields
# TNO-Quantum qkd_key_rate (Apache-2.0): independent decoy-state BB84/BBM92
# key-rate engine used as the `tno` backend + closed-form cross-check.
COPY submodules/tno-qkd-key-rate /opt/tno-qkd-key-rate
# Use requirements.txt as a pip CONSTRAINTS file (-c) for every editable backend
# install so none of them can upgrade the pinned web stack (fastapi / starlette /
# uvicorn / pydantic). Without this, a transitive dep of SeQUeNCe / Strawberry
# Fields pulls a newer Starlette that breaks fastapi 0.115.6 and the KME crashes
# on startup ("Router.__init__() got an unexpected keyword argument 'on_startup'").
# Each install must SUCCEED. These were previously chained as
# `pip install ... || echo "...failed; will use volume mount" && \`, which
# cannot fail the build: `A || B && C` runs C either way, so a broken backend
# produced a green image whose simulator was simply absent at runtime, where
# it degrades to a logged warning. The comment above already claimed they
# "fail fast at build time"; now they do.
RUN pip install -c constraints.txt pandas 'Cython<3.0' && \
    pip install -c constraints.txt -e /opt/SimQN && \
    pip install -c constraints.txt -e /opt/SeQUeNCe && \
    pip install -c constraints.txt -e /opt/strawberryfields && \
    pip install -c constraints.txt -e /opt/tno-qkd-key-rate && \
    python -c "import fastapi, starlette; from fastapi import APIRouter; APIRouter(on_startup=[]); print('web stack OK: starlette', starlette.__version__)"

# Prove the four backends are importable, in the image, at build time.
#
# Installing without importing is not the same check: a package can install and
# still fail to import on a transitive-dependency clash, which is precisely the
# class the `-c constraints.txt` pins exist to prevent.
#
# IMPORT the modules rather than probing names. The distribution name and the
# module name differ for two of these -- SimQN provides `qns`, and the TNO
# package provides the namespace module `tno.quantum.communication.qkd_key_rate`
# -- and guessing either reports a confident false absence. These are the exact
# imports the backends use.
RUN python - <<'PYCHECK'
import importlib
mods = ["qns", "sequence", "strawberryfields",
        "tno.quantum.communication.qkd_key_rate"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}: {type(e).__name__}: {e}")
print("backend modules importable:", [m for m in mods if not any(b.startswith(m) for b in bad)])
if bad:
    raise SystemExit("BACKEND IMPORT FAILURES:\n  " + "\n  ".join(bad))
PYCHECK

COPY services/bb84-kme/app/ ./app/

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=5s \
    CMD curl -sf http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
