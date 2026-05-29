#!/usr/bin/env bash
# Continuous ping over the WireGuard tunnel to measure RTT + jitter.
set -euo pipefail
TARGET="${TARGET:-10.0.0.2}"
DURATION="${DURATION:-60}"
OUT="${OUT:-benchmarks/results/ping_$(date +%s).log}"
mkdir -p "$(dirname "$OUT")"
echo "ping ${TARGET} for ${DURATION}s -> ${OUT}"
docker exec alice ping -c "$DURATION" -i 1 "$TARGET" | tee "$OUT"
