#!/bin/sh
# Audit the parts of the project that live on GitHub rather than in the tree.
#
# `scripts/secret_scan.sh` and the CI `secrets` job cover tracked files and
# commit messages. Neither can see pull-request titles and bodies, issue and
# review comments, the contributor list, or the collaborator list -- those are
# GitHub state, not repository state, and they are exactly where an attribution,
# a host identifier or a private file name would appear without any commit
# recording it.
#
# Run before a release. Needs `gh` authenticated with repo read access, and a
# Python with pytest (the project venv) for the text scan.
#
# The text surfaces go through scripts/scan_published_text.py, which applies
# the matchers the tracked-content guards already use: tooling words (vendor
# names AND the vendor-free attribution phrases), the demo host and public
# addresses, the hashed private-file names, and the generic shapes of numbered
# working notes. An earlier version grepped a literal list here that lacked the
# one product name the tooling actually signs with, and checked neither host
# identifiers nor private names; it reported clean while a PR body carried the
# demo host and another named two private notes. The private names cannot be
# written into this script without disclosing them, which is why the scan
# reuses the hashed matcher instead of a grep.
#
# Commit messages on every local ref are scanned too. Pull-request heads are
# only local refs once fetched; to include them first run
#   git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'
set -eu

cd "$(dirname "$0")/.."

REPO="${REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || { echo "::error::$PY is not executable; set PYTHON to a Python with pytest" >&2; exit 2; }
SCAN="$PY scripts/scan_published_text.py"
fail=0

# An account list is checked twice: for bot-shaped logins here, and for tooling
# names by the same scanner as the text, so no list of those names is repeated
# in this file.
check_accounts() {
    label="$1"
    logins="$2"
    extra=$(printf '%s\n' "$logins" | grep -icE -- '-bot$|\[bot\]' || true)
    if [ "$extra" -ne 0 ]; then
        echo "::error::unexpected $label account (bot)"
        fail=1
    fi
    if ! printf '%s\n' "$logins" | $SCAN --label "$label logins" >/dev/null; then
        echo "::error::unexpected $label account (tooling name)"
        fail=1
    fi
}

echo "auditing GitHub surface for $REPO"

# ---- 1) pull request and issue titles, bodies and comments -----------------
# One JSON line per record, so a multi-line body stays one record and the scan
# can name where a finding is without printing it. gh writes to a file first:
# this is /bin/sh, with no pipefail, so in `gh ... | scan` a failed gh call
# would hand the scan an empty stream and read as "0 records, clean".
records=$(mktemp)
reviews=$(mktemp)
trap 'rm -f "$records" "$reviews"' EXIT

scan_json() {
    label="$1"
    shift
    if ! gh "$@" > "$records"; then
        echo "::error::could not read $label from GitHub"
        fail=1
        return
    fi
    if out=$($SCAN --jsonl < "$records"); then
        echo "  $label: $(printf '%s\n' "$out" | tail -n 1)"
    else
        printf '%s\n' "$out"
        echo "::error::$label disclose something (see above)"
        fail=1
    fi
}

scan_json "pull request titles and bodies" \
    pr list --repo "$REPO" --state all --limit 500 --json number,title,body \
    --jq '.[] | {id: "PR #\(.number)", text: "\(.title)\n\(.body // "")"} | tojson'
scan_json "issue titles and bodies" \
    issue list --repo "$REPO" --state all --limit 500 --json number,title,body \
    --jq '.[] | {id: "issue #\(.number)", text: "\(.title)\n\(.body // "")"} | tojson'
scan_json "issue and PR conversation comments" \
    api --paginate "repos/$REPO/issues/comments" \
    --jq '.[] | {id: "comment \(.id)", text: (.body // "")} | tojson'
scan_json "PR review line comments" \
    api --paginate "repos/$REPO/pulls/comments" \
    --jq '.[] | {id: "review comment \(.id)", text: (.body // "")} | tojson'

# Review BODIES (the text submitted with an approve or request-changes) have no
# repository-wide endpoint, so they are read per pull request.
for n in $(gh pr list --repo "$REPO" --state all --limit 500 --json number --jq '.[].number'); do
    gh api "repos/$REPO/pulls/$n/reviews" \
       --jq ".[] | select((.body // \"\") != \"\") | {id: \"PR #$n review \\(.id)\", text: .body} | tojson" \
       >> "$reviews" || { echo "::error::could not read reviews of PR #$n"; fail=1; }
done
if out=$($SCAN --jsonl < "$reviews"); then
    echo "  PR review bodies: $(printf '%s\n' "$out" | tail -n 1)"
else
    printf '%s\n' "$out"
    echo "::error::PR review bodies disclose something (see above)"
    fail=1
fi

# ---- 2) contributors ------------------------------------------------------
# A tool that commits on your behalf shows up here even when every message is
# clean, because it is the AUTHOR that GitHub counts.
echo "  contributors:"
gh api "repos/$REPO/contributors" --jq '.[] | "    \(.login) (\(.contributions))"'
check_accounts contributor "$(gh api "repos/$REPO/contributors" --jq '.[].login')"

# ---- 3) collaborators -----------------------------------------------------
echo "  collaborators:"
gh api "repos/$REPO/collaborators" \
   --jq '.[] | "    \(.login) \(.permissions | to_entries | map(select(.value)) | map(.key) | join(","))"'
check_accounts collaborator "$(gh api "repos/$REPO/collaborators" --jq '.[].login')"

# ---- 4) commit messages and authorship, all local refs --------------------
# The message check in CI covers only the pushed range; this covers history.
#
# Rewriting a published branch is the operator's decision, not an audit's. A
# commit the operator has accepted as published is passed in through
# AUDIT_ACCEPTED_COMMITS (space-separated SHA prefixes) and reported rather than
# failing every run -- a gate that always fails stops being read. The list is
# not kept in the tree, because naming a commit here would point a reader at
# it. Anything else still fails.
accept_args=""
for c in ${AUDIT_ACCEPTED_COMMITS:-}; do accept_args="$accept_args --accept-commit $c"; done
# shellcheck disable=SC2086  # word splitting of accept_args is intended
if ! $SCAN --all-commits $accept_args; then
    echo "::error::a commit message on a local ref discloses something (see above)"
    fail=1
fi

# The message check would pass a commit whose AUTHOR is a tool. Names and
# addresses are split into words so a tooling name inside an address is seen.
echo "  distinct commit identities:"
git log --all --format='    %an <%ae> / %cn <%ce>' | sort -u
if ! git log --all --format='%an %ae %cn %ce' | sort -u | tr '@<>/.' '     ' \
        | $SCAN --label "commit identities" >/dev/null; then
    echo "::error::tooling identity in commit authorship"
    fail=1
fi

trailers=$(git log --all --format='%(trailers)' | grep -icE 'co-authored-by' || true)
echo "  Co-authored-by trailers: $trailers"
[ "$trailers" -eq 0 ] || { echo "::error::Co-authored-by trailer present"; fail=1; }

[ "$fail" -eq 0 ] && echo "ok: GitHub surface is clean"
exit "$fail"
