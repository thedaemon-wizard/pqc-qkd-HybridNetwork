#!/usr/bin/env python3
"""Render PNG charts from benchmark results CSVs."""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def main() -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("pip install matplotlib", file=sys.stderr)
        sys.exit(1)

    results = Path("benchmarks/results")
    out = results / "plots"
    out.mkdir(parents=True, exist_ok=True)

    hs = results / "handshake_age.csv"
    if hs.exists():
        ts, age = [], []
        with hs.open() as f:
            reader = csv.reader(f); next(reader, None)
            for row in reader:
                ts.append(float(row[0])); age.append(float(row[1]))
        if ts:
            t0 = ts[0]
            plt.figure(figsize=(8, 3))
            plt.plot([t - t0 for t in ts], age, color="#5b8def")
            plt.xlabel("Elapsed (s)"); plt.ylabel("Handshake age (s)")
            plt.title("WireGuard handshake age (PSK rotation drops it to ~0)")
            plt.grid(True, alpha=0.3); plt.tight_layout()
            plt.savefig(out / "handshake_age.png", dpi=110)
            print(f"wrote {out/'handshake_age.png'}")


if __name__ == "__main__":
    main()
