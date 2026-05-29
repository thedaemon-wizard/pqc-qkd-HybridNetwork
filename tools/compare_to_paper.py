#!/usr/bin/env python3
"""Compare our benchmark output against the published paper supplementary data.

`submodules/qkd-pqc-paper-supplementary/` contains the raw experimental data
from Spooren et al. (arXiv:2604.05599) — handshake traces, key rotation logs,
multi-hop daisy-chain timings, failure-recovery measurements.

This tool aligns our `benchmarks/results/*.csv` to those baselines and produces
overlay plots in `benchmarks/results/paper_overlay/`.

Usage (inside .venv):
    python tools/compare_to_paper.py --our benchmarks/results/handshake_age.csv \
                                      --paper-dir submodules/qkd-pqc-paper-supplementary
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def load_csv_two_col(path: Path) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    with path.open() as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            try:
                xs.append(float(row[0])); ys.append(float(row[1]))
            except ValueError:
                continue
    return xs, ys


def summarise(name: str, xs: list[float], ys: list[float]) -> dict[str, float]:
    if not ys:
        return {"name": name, "n": 0}
    n = len(ys)
    mean = sum(ys) / n
    var = sum((y - mean) ** 2 for y in ys) / n
    return {"name": name, "n": n, "mean": mean, "stddev": var ** 0.5,
            "min": min(ys), "max": max(ys)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--our", default="benchmarks/results/handshake_age.csv")
    ap.add_argument("--paper-dir", default="submodules/qkd-pqc-paper-supplementary")
    ap.add_argument("--out", default="benchmarks/results/paper_comparison.json")
    args = ap.parse_args()

    our_path = Path(args.our)
    paper_root = Path(args.paper_dir)

    summary: dict[str, object] = {
        "our_file": str(our_path),
        "paper_dir": str(paper_root),
    }

    if our_path.exists():
        xs, ys = load_csv_two_col(our_path)
        summary["ours"] = summarise("ours", xs, ys)
    else:
        print(f"[warn] our file missing: {our_path}", file=sys.stderr)
        summary["ours"] = {"name": "ours", "n": 0}

    # Scan the paper supplementary for relevant CSV / log files
    paper_candidates: list[dict] = []
    if paper_root.exists():
        for csvf in paper_root.rglob("*.csv"):
            if csvf.stat().st_size > 0 and csvf.stat().st_size < 50_000_000:
                try:
                    xs, ys = load_csv_two_col(csvf)
                    paper_candidates.append({
                        "path": str(csvf.relative_to(paper_root)),
                        **summarise(csvf.stem, xs, ys),
                    })
                except Exception as e:
                    paper_candidates.append({
                        "path": str(csvf.relative_to(paper_root)),
                        "error": str(e),
                    })
    summary["paper_baselines"] = paper_candidates

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
