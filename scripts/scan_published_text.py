"""Scan text that is published beside the tree, not in it, for disclosures.

Commit messages, pull-request titles and bodies, and issue and review comments
are public, but none of them is a tracked file, so the tracked-content guards in
tests/ never read them. This applies the SAME matchers to that text instead of
restating them, so the two cannot drift:

  - the hashed private-name matcher of
    tests/test_private_files_have_a_safe_harbour.py, whose digests are the only
    record of the names -- this file must not spell them either;
  - the tooling, demo-host and address patterns of
    tests/test_repo_is_publication_ready.py.

It adds two things those guards deliberately leave out of the tree scan:

  - the operator's numbered working notes, matched by the digest of their
    stem (`_names_a_numbered_note` in the same test module), so this file does
    not spell the stem either. The tree scan leaves it out because a
    word-plus-number token is ordinary prose there;
  - the attribution phrases a tool writes into a message or a PR body, which
    carry no vendor word. Every Co-authored-by trailer is refused, not only one
    naming a tool: this repository has a single author, so any such trailer is
    either a tool's or a mistake.

Nothing matched is ever printed, only where and in which category. CI logs of a
public repository are public too, and a report that echoes a private name
republishes it.

Usage:
  python scripts/scan_published_text.py --git-range A..B
      one record per commit message in the range, labelled by commit
  python scripts/scan_published_text.py --all-commits
      the same, for every commit reachable from any local ref
  ... --accept-commit SHA
      report a commit that is already published and has been accepted as is,
      without failing on it (repeatable; a prefix is enough). The list of
      accepted commits is the operator's and is not kept in the tree: pointing
      at a commit from here would tell a reader where to look.
  ... | python scripts/scan_published_text.py --jsonl
      one JSON object per line, {"id": <label>, "text": <body>}
  ... | python scripts/scan_published_text.py --label NAME
      the whole of stdin as a single record

Needs pytest importable, because the pattern module it reuses is a test module.
Exit status: 0 clean, 1 findings, 2 usage or environment error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# Shortest commit prefix --accept-commit takes; git's own default abbreviation.
MIN_ACCEPT_PREFIX = 7

# Attribution phrases that name no vendor, so the vendor-word pattern cannot
# see them. Word-bounded: "WebLLM" is a library name, not an attribution.
ATTRIBUTION = re.compile(
    r"\bLLM\b|\bco-authored-by\b|\bdevtools mcp\b|\bgenerated with\b", re.I)


def _load(module_file: str):
    """Import a test module by path, without making tests/ a package."""
    path = TESTS / module_file
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _categories(text: str, private, publication) -> list[str]:
    found = []
    if publication.TOOLING.search(text) or ATTRIBUTION.search(text):
        found.append("assistant-tooling reference")
    if private._names_a_private_file(text):
        found.append("operator-private file name")
    if private._names_a_numbered_note(text):
        found.append("operator working-file name (numbered note)")
    if publication._DEMO_FQDN.search(text):
        found.append("demo host name")
    for m in publication._IPV4.finditer(text):
        ip = m.group()
        if not (publication._IPV4_PRIVATE.match(ip) or ip.startswith("0.0.0.0")):
            found.append("public IPv4 address")
            break
    for m in publication._IPV6.finditer(text):
        if not publication._IPV6_LOCAL.match(m.group()):
            found.append("global IPv6 address")
            break
    return found


def _records(args) -> list[tuple[str, str]]:
    if args.git_range or args.all_commits:
        revs = ["--all"] if args.all_commits else [args.git_range]
        shas = subprocess.run(
            ["git", "rev-list", *revs], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.split()
        out = []
        for sha in shas:
            if any(sha.startswith(a) for a in args.accept_commit):
                print(f"accepted: commit {sha[:12]} (already published, not rewritten)")
                continue
            body = subprocess.run(
                ["git", "log", "-1", "--format=%B", sha], cwd=ROOT, check=True,
                capture_output=True, text=True).stdout
            out.append((f"commit {sha[:12]}", body))
        return out
    data = sys.stdin.read()
    if args.jsonl:
        out = []
        for n, line in enumerate(data.splitlines(), 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            out.append((str(obj.get("id", f"record {n}")), str(obj.get("text", ""))))
        return out
    return [(args.label, data)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--git-range", help="scan each commit message in this range")
    src.add_argument("--all-commits", action="store_true",
                     help="scan every commit message reachable from any local ref")
    src.add_argument("--jsonl", action="store_true",
                     help='stdin is JSON lines of {"id": ..., "text": ...}')
    ap.add_argument("--accept-commit", action="append", default=[],
                    metavar="SHA", help="published commit accepted as is")
    ap.add_argument("--label", default="stdin",
                    help="name of the single stdin record (plain mode)")
    args = ap.parse_args(argv)
    # A short or empty prefix would accept far more than the commit meant; an
    # empty one accepts every commit, which would turn the scan off unannounced.
    short = [a for a in args.accept_commit
             if not re.fullmatch(rf"[0-9a-f]{{{MIN_ACCEPT_PREFIX},40}}", a)]
    if short:
        print(f"::error::--accept-commit needs at least {MIN_ACCEPT_PREFIX} hex "
              f"digits: {short}", file=sys.stderr)
        return 2

    try:
        private = _load("test_private_files_have_a_safe_harbour.py")
        publication = _load("test_repo_is_publication_ready.py")
    except ImportError as exc:
        print(f"::error::cannot load the shared matchers: {exc}", file=sys.stderr)
        return 2

    records = _records(args)
    hits = 0
    for rid, text in records:
        cats = _categories(text, private, publication)
        if cats:
            hits += 1
            # Location and category only. Never the matched text.
            print(f"::error::{rid}: {', '.join(cats)}")
    print(f"scanned {len(records)} record(s); {hits} with findings")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
