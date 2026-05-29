#!/usr/bin/env bash
# Throughput benchmark over the WireGuard tunnel.
# Bob runs iperf3 server (one-shot), Alice runs the client.
set -euo pipefail
DURATION="${DURATION:-20}"
OUT="${OUT:-benchmarks/results/iperf3_$(date +%s).log}"
mkdir -p "$(dirname "$OUT")"

docker exec -d bob sh -c "iperf3 -s -1 -B 10.0.0.2 > /tmp/iperf.log 2>&1 || true"
sleep 1
docker exec alice iperf3 -c 10.0.0.2 -t "$DURATION" --json | tee "$OUT"
