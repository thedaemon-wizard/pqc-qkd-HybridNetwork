# Benchmarks

What the benchmark scripts measure, how to run them, and what has actually
been measured so far.

Moved out of `README.md` section 9 on 2026-09-25.

## Status: no results are committed

`benchmarks/results/` is gitignored, and on the development host it holds
only two logs, one of them empty. Nothing in this repository reports a
benchmark figure measured on this stack, and the paper's numbers below are
**targets quoted from the paper**, not results reproduced here. A reader who
finds a latency or throughput figure attributed to this project elsewhere
should look for the run that produced it.

## Running them

Against a running stack (`make up`):

```bash
make bench
.venv/bin/python benchmarks/plot_results.py
```

`make bench` runs three scripts, through the project venv:

| Script | Measures | Output (under `benchmarks/results/`) |
|---|---|---|
| `benchmarks/handshake_timer.py` | WireGuard handshake age around a PSK rotation; it should drop to about zero at each rotation | `handshake_age.csv` |
| `benchmarks/ping_loop.sh` | RTT and jitter over `wg0`, `alice` to `10.0.0.2`, 60 s by default (`DURATION`) | `ping_<epoch>.log` |
| `benchmarks/iperf3_runner.sh` | Throughput over the tunnel | `iperf3_<epoch>.log` (JSON) |

`plot_results.py` renders `plots/handshake_age.png` from the CSV.

## What to compare against

Spooren et al., *PQC-Enhanced QKD Networks: A Layered Approach*,
[arXiv:2604.05599](https://arxiv.org/abs/2604.05599), Evaluation:

- Mean end-to-end setup time 10.27 s at 10 hops and 10.62 s at 100 hops
  (Test 2, Long Distance).
- Handshake traffic per key negotiation (Table 1): WireGuard 3 packets /
  398 bytes, arnika key_ID exchange 2 packets / 78 bytes, Rosenpass 4 packets /
  4772 bytes.

`tests/test_paper_budgets.py` checks the Table 1 figures against the
redistributed PDF, and `/paper-flow` and `/verify` display them. They are the
paper's measurements on its own testbed; a run here would be a separate
measurement on different hardware.
