#!/bin/sh
# Audit the parts of the project that live on GitHub rather than in the tree.
#
# `scripts/secret_scan.sh` and the CI `secrets` job cover tracked files and
# commit messages. Neither can see pull-request titles and bodies, the
# contributor list, or the collaborator list -- those are GitHub state, not
# repository state, and they are exactly where an attribution would appear
# without any commit recording it.
#
# Run before a release. Needs `gh` authenticated with repo read access.
#
# Deliberately reads the patterns from a variable rather than repeating them
# inline in each grep: the file has to name what it forbids in order to look for
# it, and one occurrence is easier to keep exempt than five.
set -eu

REPO="${REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
PATTERNS='generated with|co-authored-by|anthropic|copilot|chatgpt'
fail=0

echo "auditing GitHub surface for $REPO"

# ---- 1) pull request titles and bodies ------------------------------------
prs=$(gh pr list --repo "$REPO" --state all --limit 500 \
        --json number,title,body --jq '.[] | "\(.number)\t\(.title)\t\(.body // "")"')
n_pr=$(gh pr list --repo "$REPO" --state all --limit 500 --json number --jq 'length')
hits=$(printf '%s\n' "$prs" | grep -icE "$PATTERNS" || true)
echo "  $n_pr pull request(s) scanned; $hits match(es)"
if [ "$hits" -ne 0 ]; then
    printf '%s\n' "$prs" | grep -inE "$PATTERNS" | cut -c1-200
    echo "::error::tooling attribution found in a pull request title or body"
    fail=1
fi

# ---- 2) contributors ------------------------------------------------------
# A tool that commits on your behalf shows up here even when every message is
# clean, because it is the AUTHOR that GitHub counts.
echo "  contributors:"
gh api "repos/$REPO/contributors" --jq '.[] | "    \(.login) (\(.contributions))"'
extra=$(gh api "repos/$REPO/contributors" --jq '.[].login' | grep -icE "$PATTERNS|-bot$|\[bot\]" || true)
if [ "$extra" -ne 0 ]; then
    echo "::error::unexpected contributor account"
    fail=1
fi

# ---- 3) collaborators -----------------------------------------------------
echo "  collaborators:"
gh api "repos/$REPO/collaborators" \
   --jq '.[] | "    \(.login) \(.permissions | to_entries | map(select(.value)) | map(.key) | join(","))"'
extra=$(gh api "repos/$REPO/collaborators" --jq '.[].login' | grep -icE "$PATTERNS|-bot$|\[bot\]" || true)
if [ "$extra" -ne 0 ]; then
    echo "::error::unexpected collaborator account"
    fail=1
fi

# ---- 4) commit authorship, all refs ---------------------------------------
# The message check in CI would pass a commit whose AUTHOR is a tool.
echo "  distinct commit identities:"
git log --all --format='    %an <%ae> / %cn <%ce>' | sort -u
ids=$(git log --all --format='%an%ae%cn%ce' | grep -icE "$PATTERNS" || true)
if [ "$ids" -ne 0 ]; then
    echo "::error::tooling identity in commit authorship"
    fail=1
fi

trailers=$(git log --all --format='%(trailers)' | grep -icE 'co-authored-by' || true)
echo "  Co-authored-by trailers: $trailers"
[ "$trailers" -eq 0 ] || { echo "::error::Co-authored-by trailer present"; fail=1; }

[ "$fail" -eq 0 ] && echo "ok: GitHub surface is clean"
exit "$fail"
