# shellcheck shell=bash
# Sourced by deploy/deploy.sh and deploy/deploy-demo.sh. Two helpers that both
# scripts need and that must not drift apart: the firewall step and --pull.

# ---- configure_firewall --------------------------------------------------
# Opens what this stack needs and leaves every other rule alone.
#
# Both scripts used to run `ufw --force reset` and then allow 22/80/443 only.
# A reset deletes every rule already on the host, so on a machine that serves
# anything else -- another site, a monitoring agent, SSH on a non-standard
# port -- re-running the deploy dropped those services, or locked the operator
# out of SSH. The rules are now ADDED, the SSH port is read from sshd rather
# than assumed, and the default-deny policy is set only when UFW was inactive,
# i.e. only when this script is the one turning the firewall on.
#
# SKIP_UFW=1 leaves the firewall entirely untouched.
configure_firewall() {
  command -v ufw >/dev/null 2>&1 || { log "ufw not installed; firewall left as is"; return 0; }
  if [[ "${SKIP_UFW:-0}" == "1" ]]; then
    log "SKIP_UFW=1: firewall left as is"
    return 0
  fi
  local ssh_ports p
  ssh_ports="$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2}' | sort -u)"
  ssh_ports="${ssh_ports:-22}"
  log "firewall: adding rules for ssh ($(echo $ssh_ports)), 80/tcp, 443/tcp, 443/udp; existing rules are kept"
  for p in $ssh_ports; do ufw allow "${p}/tcp" >/dev/null; done
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null   # HTTP/3
  if ufw status | grep -q "^Status: inactive"; then
    log "firewall: ufw was inactive; enabling with default deny incoming"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw --force enable >/dev/null
  fi
}

# ---- fast_forward_to_branch ---------------------------------------------
# The body of `--pull`, shared so deploy.sh and deploy-demo.sh update a host the
# same way. It was inline in deploy-demo.sh only, while deploy/README.md told
# operators to run `deploy.sh --pull` too -- which deploy.sh did not accept.
# Expects DEPLOY_BRANCH and a `log` function; DEPLOY_NAME prefixes errors.
fast_forward_to_branch() {
  log "fetching origin/${DEPLOY_BRANCH}"
  git fetch --prune origin "${DEPLOY_BRANCH}"

  # Report local modifications, but do NOT refuse on their mere existence.
  #
  # An earlier version aborted on any dirty file. Tested against the real demo
  # host, that made the script unusable: the box carries a deliberate local
  # Caddyfile edit serving a second project's domain, plus a submodule pointer
  # and some stray untracked files. None of them are touched by the update. A
  # guard that blocks the correct action pushes the operator into running the
  # git commands by hand, which is strictly less safe than the script.
  #
  # `git merge --ff-only` below already refuses precisely when it matters -- it
  # will not overwrite a locally-modified file that the incoming commits change
  # -- and it is exact about which files those are, which a blanket
  # `git diff --quiet` cannot be.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    log "note: local modifications present; they are preserved unless the update touches them"
    git status --short >&2
  fi

  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "${DEPLOY_BRANCH}" ]]; then
    log "switching from ${current} to ${DEPLOY_BRANCH}"
    git checkout "${DEPLOY_BRANCH}"
  fi

  before="$(git rev-parse HEAD)"
  # --ff-only: fail loudly rather than create a merge commit on a deploy host,
  # and it aborts before touching anything if a locally-modified file would be
  # overwritten. That is the real safety check; see the note above.
  if ! git merge --ff-only "origin/${DEPLOY_BRANCH}"; then
    echo "[${DEPLOY_NAME:-deploy}] fast-forward refused. Either the branch has diverged, or" >&2
    echo "[${DEPLOY_NAME:-deploy}] the update would overwrite a locally-modified file." >&2
    echo "[${DEPLOY_NAME:-deploy}] Nothing has been changed. Resolve, then re-run." >&2
    exit 1
  fi
  after="$(git rev-parse HEAD)"

  if [[ "$before" == "$after" ]]; then
    log "already up to date at ${after:0:8}"
  else
    log "updated ${before:0:8} -> ${after:0:8}"
    git --no-pager log --oneline "${before}..${after}" | sed 's/^/  /'
  fi
}
