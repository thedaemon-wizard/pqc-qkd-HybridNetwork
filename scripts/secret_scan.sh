#!/usr/bin/env bash
# Scan the working tree for secrets. Exit non-zero if any are found.
#
# The fallback branch used to be unable to fail, and unable to stay quiet:
#
#     set +e
#     grep -rEn ... . | head -n 50
#
# `set +e` disarms `set -e`, and a pipeline's status is its LAST command's, so
# the script took `head`'s 0 whatever grep found. Measured 2026-08-27: planting
# a file containing `-----BEGIN OPENSSH PRIVATE KEY-----` and running this  # PUBGUARD-ALLOW
# script printed the file, the line number AND the matching line, then exited 0.
# VERIFICATION_CHECKLIST row 6.12 cites it as one of the two things that "see
# tracked files and commit messages", so a release check reported success while
# quoting a private key back at the operator.
#
# Two rules now, and they are the reason for every awkward bit of shell below:
#
#   1. A find is a FAILURE. Not a warning, not a note. Exit 1.
#   2. A find is REDACTED. Print `path:line` and nothing else. The gitleaks
#      branch passes --redact; the fallback printed the matched text verbatim,
#      which turns "we found a leaked key" into "we copied a leaked key into
#      CI's log, which is public on a public repository".
#
# A missing gitleaks is still not silently OK: the fallback is a handful of
# regexes against gitleaks' hundreds of rules, so it says so and says what it
# cannot see.
set -euo pipefail

if command -v gitleaks >/dev/null 2>&1; then
    exec gitleaks detect --source . --no-banner --redact
fi

echo "gitleaks not installed; falling back to a small regex scan." >&2
echo "Install it for real coverage: https://github.com/gitleaks/gitleaks" >&2
echo "This fallback checks a handful of patterns, NOT gitleaks' full rule set." >&2

# `|| true` on the grep only: no-match is exit 1 for grep and is the GOOD case
# here, so it must not trip `set -e`. The find/no-find decision is made below
# from the output, not from grep's status.
#
# --exclude the scanner itself. The old version matched its own pattern line and
# reported scripts/secret_scan.sh as a hit, which trains a reader to skim past
# the one output that is supposed to be alarming.
hits=$(grep -rEn --binary-files=without-match \
         --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
         --exclude-dir=submodules --exclude-dir=results \
         --exclude="$(basename "$0")" \
         'PRIVATE KEY|BEGIN OPENSSH|password[[:space:]]*=[[:space:]]*['"'"'"][^'"'"'"]{8,}' \
         . 2>/dev/null | cut -d: -f1,2 || true)

if [ -n "$hits" ]; then
    echo "::error::possible secrets in tracked content (paths only; the matched text is deliberately NOT printed)" >&2
    printf '%s\n' "$hits" | head -n 50 >&2
    n=$(printf '%s\n' "$hits" | grep -c . || true)
    echo "::error::$n candidate location(s). Inspect each by hand; do not paste the contents anywhere." >&2
    exit 1
fi

echo "ok: no secrets matched the fallback patterns (gitleaks absent -- coverage is partial)"
