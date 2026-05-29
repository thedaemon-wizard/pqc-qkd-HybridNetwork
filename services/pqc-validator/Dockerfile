# =====================================================================
# pqc-validator — runs the same NIST PQC test vectors through both
# liboqs (production) and PQClean (reference) and asserts byte-equality.
# =====================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential cmake ninja-build git \
        libssl-dev pkg-config && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Lightweight Python stack
COPY services/pqc-validator/requirements.txt .
RUN pip install -r requirements.txt

# We mount /submodules/PQClean at runtime via compose volume to avoid
# baking the whole 200MB into the image.
COPY services/pqc-validator/app /app/app

EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD curl -sf http://localhost:8090/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
