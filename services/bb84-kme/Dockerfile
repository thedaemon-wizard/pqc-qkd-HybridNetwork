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
# Fields could pull a Starlette the pinned fastapi does not support; that once
# crashed the KME on startup ("Router.__init__() got an unexpected keyword
# argument 'on_startup'"), and the check at the end of this RUN still guards it.
# Each install must SUCCEED. These were previously chained as
# `pip install ... || echo "...failed; will use volume mount" && \`, which
# cannot fail the build: `A || B && C` runs C either way, so a broken backend
# produced a green image whose simulator was simply absent at runtime, where
# it degrades to a logged warning. The comment above already claimed they
# "fail fast at build time"; now they do.
RUN pip install -c constraints.txt 'Cython<3.0' && \
    pip install -c constraints.txt -e /opt/SimQN && \
    pip install -c constraints.txt -e /opt/SeQUeNCe && \
    pip install -c constraints.txt -e /opt/strawberryfields && \
    pip install -c constraints.txt -e /opt/tno-qkd-key-rate && \
    python -c "import fastapi, starlette; from fastapi import APIRouter; APIRouter(on_startup=[]); print('web stack OK: starlette', starlette.__version__)"

# Every `==` pin in requirements.txt must be what pip actually installed.
#
# requirements.txt is read as the record of what this image ships, and three
# times it was not: numpy and qutip (moved by SeQUeNCe's editable install until
# they were added to constraints.txt), then pyyaml, pinned at 6.0.2 while the
# image shipped 6.0.3. Each was found by hand, after the fact. The editable
# installs above run AFTER requirements.txt and can move any package that
# constraints.txt does not hold, so the check runs here, after the last of them.
# Names are compared in normalised form (PEP 503), so `prometheus-client` and
# `prometheus_client` are the same package.
RUN python - <<'PINCHECK'
import re
import subprocess
import sys

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"],
                        capture_output=True, text=True, check=True).stdout
installed = {}
for line in freeze.splitlines():
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)$", line.strip())
    if m:
        installed[norm(m.group(1))] = m.group(2)
drift = []
for line in open("requirements.txt"):
    line = line.split("#", 1)[0].strip()
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(\S+)$", line)
    if not m:
        continue
    got = installed.get(norm(m.group(1)))
    if got != m.group(2):
        drift.append(f"{m.group(1)}: requirements.txt pins {m.group(2)}, image has {got}")
if drift:
    raise SystemExit("PIN DRIFT (pin it in constraints.txt too, or fix the pin):\n  "
                     + "\n  ".join(drift))
print("requirements.txt pins match the installed packages:", len(installed), "installed")
PINCHECK

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
# The ETSI GS QKD 004 spec facts: ONE file, shared with the browser simulator
# on /protocol-lab. The frontend image can only read its own directory, so the
# file lives there and is copied in here (this image builds from the repository
# root). Loading it at build time fails the build if it is missing or disagrees
# with the status enum in app/etsi004_spec.py.
COPY services/webui-frontend/src/lib/sim/etsi004SpecV211.json ./app/etsi004SpecV211.json
ENV ETSI004_SPEC_FILE=/app/app/etsi004SpecV211.json
RUN python -c "from app.etsi004_spec import load_spec; s = load_spec(); print('etsi004 spec', s['version'], len(s['transitions']), 'transitions')"

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=5s \
    CMD curl -sf http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
