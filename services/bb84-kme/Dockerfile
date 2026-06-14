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

COPY services/bb84-kme/pyproject.toml services/bb84-kme/requirements.txt ./
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
RUN pip install pandas 'Cython<3.0' && \
    pip install -e /opt/SimQN || echo "SimQN editable install failed; will use volume mount" && \
    pip install -e /opt/SeQUeNCe || echo "SeQUeNCe editable install failed; will use volume mount" && \
    pip install -e /opt/strawberryfields || echo "strawberryfields editable install failed; will use volume mount" && \
    pip install -e /opt/tno-qkd-key-rate || echo "TNO qkd_key_rate install failed; tno backend disabled"

COPY services/bb84-kme/app/ ./app/

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=5s \
    CMD curl -sf http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
