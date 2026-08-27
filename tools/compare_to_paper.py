#!/usr/bin/env python3
"""Index the published paper supplementary data and summarise each CSV.

`submodules/qkd-pqc-paper-supplementary/` contains the raw experimental data
from Spooren et al. (arXiv:2604.05599).

WHAT THIS TOOL DOES NOT DO: it does not align quantities. It reads columns 0
and 1 of every CSV it finds and summarises column 1, whatever that column
happens to hold. Different files hold different things there, and the summary
carried no record of which -- so `rosenpass-scalability/results/
experiment-summary.csv`, whose columns are `peer_count` and `avg_cpu_percent`,
produced `mean: 11.93`, and docs/phases.md read that mean CPU PERCENTAGE as a
handshake TIME and reported "within +/-15 % of the paper\'s 10.27 s @ 10 nodes".
Two different units, at a peer count (10) that is not in the file, against an
`ours` entry of `{"n": 0}`.

The summaries now carry `x_column` and `y_column`, taken from the CSV header,
so a reader can see what was averaged before comparing it to anything. Read
those names before drawing any conclusion from `mean`.

Usage (inside .venv):
    python tools/compare_to_paper.py --our benchmarks/results/handshake_age.csv \
                                      --paper-dir submodules/qkd-pqc-paper-supplementary
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _setup_logger() -> logging.Logger:
    log_dir = Path(os.environ.get("LOG_DIR", "benchmarks/results"))
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
    root = logging.getLogger(); root.setLevel(logging.INFO); root.handlers.clear()
    sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
    fh = RotatingFileHandler(log_dir / "compare_to_paper.log",
                              maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt); root.addHandler(fh)
    return logging.getLogger("compare-to-paper")


log = _setup_logger()


def load_csv_two_col(path: Path) -> tuple[list[float], list[float], list[str]]:
    """Columns 0 and 1 as floats, plus the header row so callers can say which.

    Returning the header is the point: without it every summary looks the same
    whether column 1 is seconds, a percentage or a byte count.
    """
    xs, ys = [], []
    with path.open() as f:
        reader = csv.reader(f)
        header = next(reader, None) or []
        for row in reader:
            if len(row) < 2:
                continue
            try:
                xs.append(float(row[0])); ys.append(float(row[1]))
            except ValueError:
                continue
    return xs, ys, [h.strip() for h in header[:2]]


def summarise(name: str, xs: list[float], ys: list[float],
              header: list[str] | None = None) -> dict[str, object]:
    """Summarise column 1, and SAY WHICH COLUMN that was.

    `mean` on its own is unitless and invites comparison with anything of a
    similar magnitude. Carrying the column names makes a units mismatch visible
    in the output file rather than only in the source of the tool.
    """
    header = header or []
    cols = {
        "x_column": header[0] if len(header) > 0 else "(no header)",
        "y_column": header[1] if len(header) > 1 else "(no header)",
    }
    if not ys:
        return {"name": name, "n": 0, **cols}
    n = len(ys)
    mean = sum(ys) / n
    var = sum((y - mean) ** 2 for y in ys) / n
    return {"name": name, "n": n, **cols, "summarised": cols["y_column"],
            "mean": mean, "stddev": var ** 0.5, "min": min(ys), "max": max(ys)}


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
        xs, ys, header = load_csv_two_col(our_path)
        summary["ours"] = summarise("ours", xs, ys, header)
    else:
        # n == 0 means "we never measured", not "we measured zero". Anything
        # reading this file must not treat the two the same; docs/phases.md
        # once reported a +/-15 % agreement against exactly this empty entry.
        log.warning("our file missing: %s", our_path)
        summary["ours"] = {"name": "ours", "n": 0,
                           "note": f"{our_path} does not exist; nothing measured"}

    # Scan the paper supplementary for relevant CSV / log files
    paper_candidates: list[dict] = []
    if paper_root.exists():
        for csvf in paper_root.rglob("*.csv"):
            if csvf.stat().st_size > 0 and csvf.stat().st_size < 50_000_000:
                try:
                    xs, ys, header = load_csv_two_col(csvf)
                    paper_candidates.append({
                        "path": str(csvf.relative_to(paper_root)),
                        **summarise(csvf.stem, xs, ys, header),
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
    log.info("wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
