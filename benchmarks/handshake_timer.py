#!/usr/bin/env python3
"""Measure the WireGuard handshake age before/after a PSK rotation.

Run from the project root:
    python3 benchmarks/handshake_timer.py
"""
from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path


def wg_show(container: str, iface: str = "wg0") -> str:
    return subprocess.check_output(
        ["docker", "exec", container, "wg", "show", iface, "dump"],
        text=True,
    )


def parse_handshake_age(dump: str) -> float | None:
    """Last column of `dump` is `latest-handshake` epoch; 0 if none."""
    # Skip header (interface row). Each peer row has tab-separated fields.
    for line in dump.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 5:
            try:
                ts = int(parts[4])
                return time.time() - ts if ts > 0 else None
            except ValueError:
                continue
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--container", default="alice")
    p.add_argument("--duration", type=int, default=120, help="seconds to observe")
    p.add_argument("--out", default="benchmarks/results/handshake_age.csv")
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        f.write("epoch,handshake_age_s\n")
        t0 = time.time()
        while time.time() - t0 < args.duration:
            try:
                dump = wg_show(args.container)
                age = parse_handshake_age(dump)
                if age is not None:
                    f.write(f"{time.time():.2f},{age:.2f}\n")
                    f.flush()
                    print(f"handshake_age={age:.2f}s")
            except subprocess.CalledProcessError as e:
                print(f"wg show failed: {e}")
            time.sleep(2.0)
    print(f"results: {out_path}")


if __name__ == "__main__":
    main()
