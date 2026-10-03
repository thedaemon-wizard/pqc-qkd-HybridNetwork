# ===================================================================
# PQC-QKD Hybrid PoC — Makefile
# ===================================================================
SHELL := /bin/bash
PROJECT ?= pqcqkd
COMPOSE ?= docker compose

# Compose file selection
COMPOSE_FILES ?= -f docker-compose.yml
# Append override files manually, e.g.:
#   make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.qkdnetsim.yml"
# A host without the WireGuard kernel module needs no override: the node
# entrypoint falls back to the wireguard-go binary the image ships.

DC = $(COMPOSE) $(COMPOSE_FILES)

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------
.PHONY: init
init: ## Initialize: env file, submodules
	@test -f .env || cp .env.example .env
	git submodule update --init --recursive
	@echo "[init] mTLS certs NOT generated. Nothing consumes them: no compose"
	@echo "[init] service or Dockerfile references pki/, and /hil says so on"
	@echo "[init] screen. Run 'make pki' if you are building that lane."

# Separated from `init` on 2026-08-29. It used to run unconditionally, so every
# clone wrote a 4096-bit CA key plus four keypairs (chmod 600) into the working
# tree for a lane that does not exist -- grep for `pki/` across
# docker-compose*.yml, deploy/*.yml and every Dockerfile returns zero hits.
# Generating unused private key material is not neutral: it is one more secret
# on disk, in a repository whose own release gates scan for exactly that.
.PHONY: pki
pki: ## Generate self-signed mTLS certs (Phase 7 lane; not wired up yet)
	./pki/gen-certs.sh

.PHONY: build
build: ## Build all docker images
	$(DC) build

.PHONY: up
up: ## Start the full stack (detached)
	$(DC) up -d

.PHONY: up-multihop
up-multihop: ## Start with multi-hop Charlie node
	$(DC) -f docker-compose.multihop.yml --profile multihop up -d

.PHONY: down
down: ## Stop & remove the stack
	$(DC) down

.PHONY: clean
clean: ## Down + prune volumes
	$(DC) down -v --remove-orphans

.PHONY: ps
ps: ## Show running containers
	$(DC) ps

.PHONY: logs
logs: ## Tail all logs
	$(DC) logs -f --tail=100

.PHONY: logs-alice
logs-alice: ## Tail alice logs
	$(DC) logs -f alice

.PHONY: logs-bob
logs-bob: ## Tail bob logs
	$(DC) logs -f bob

.PHONY: tail-logs
tail-logs: ## (Phase 12-A) Tail rotating log files inside pqcqkd-logs volume
	# No `|| true`: if the container is not up, failing here names the real
	# problem, whereas swallowing it produced a confusing error from `tail -f`
	# one line later. VERIFICATION_CHECKLIST.md row 5.3 forbids the pattern.
	$(DC) exec webui-backend ls -lh /var/log/pqcqkd/
	$(DC) exec webui-backend tail -f /var/log/pqcqkd/webui-backend.log

# -------------------------------------------------------------------
# Verification / Smoke
# -------------------------------------------------------------------
# The two WireGuard tunnels of the node pair, as docker-compose.yml defaults
# them (WG_BOB_IP and WG1_BOB_IP). wg0 is the hop tunnel arnika keys; wg1 is the
# data tunnel Rosenpass keys, and its endpoint is bob's wg0 address, so an echo
# answered on WG1_PEER_IP has crossed both tunnels. Override both if .env moves
# the addresses.
WG0_PEER_IP ?= 10.0.0.2
WG1_PEER_IP ?= 10.0.1.2

# How long the smoke waits for each tunnel to answer. Neither is up the moment
# the containers are: every peer starts with a random placeholder PSK, so a
# tunnel answers only once its keying daemon has installed the same key on
# both ends. wg0 waits for arnika, which starts at the next wall-clock multiple
# of ARNIKA_INTERVAL (up to one interval) and whose first interval can fail
# closed before the first PQC key is agreed; four intervals at the default 30s.
# The number does not follow ARNIKA_INTERVAL: if .env changes the interval,
# raise SMOKE_WG0_WAIT_S to about four intervals too (for example 480 at 2m),
# or the smoke reports a false FAIL while arnika is still waiting to start.
# wg1 then waits for the first Rosenpass exchange, which runs inside wg0 and
# retransmits at most 10 s apart (RETRANSMIT_DELAY_END), and for WireGuard's
# next handshake attempt, 5 s apart (REKEY_TIMEOUT).
SMOKE_WG0_WAIT_S ?= 120
SMOKE_WG1_WAIT_S ?= 60
# WireGuard's REJECT_AFTER_TIME: a session older than this carries no data, so
# a latest handshake older than this is not evidence of a working tunnel.
WG_REJECT_AFTER_TIME_S = 180

# $(call smoke_ping,<iface>,<peer tunnel ip>,<wait s>): wait up to <wait s>
# for one echo, then require three.
define smoke_ping
	@deadline=$$(( $$(date +%s) + $(3) )); \
	until $(DC) exec -T alice ping -c 1 -W 2 $(2) >/dev/null 2>&1; do \
	  if [ "$$(date +%s)" -ge "$$deadline" ]; then \
	    echo "FAIL: no answer from $(2) over $(1) within $(3)s"; exit 1; \
	  fi; \
	  sleep 1; \
	done
	$(DC) exec -T alice ping -c 3 -W 2 $(2) || (echo "FAIL: ping over $(1)"; exit 1)
endef

# $(call smoke_handshake,<iface>,<peer tunnel ip>): the peer that owns
# <peer tunnel ip>/32 has completed a handshake within WG_REJECT_AFTER_TIME_S.
# This, not a `preshared key` line, is the evidence that the keying daemon
# wrote the key: every peer carries a random placeholder PSK from the moment it
# is added, so a preshared key is always present, and only matching keys on
# both ends complete a handshake. Reads allowed-ips and latest-handshakes,
# neither of which prints a key.
define smoke_handshake
	@peer=$$($(DC) exec -T alice wg show $(1) allowed-ips \
	  | awk -v ip="$(2)/32" '{ for (i = 2; i <= NF; i++) if ($$i == ip) print $$1 }'); \
	if [ -z "$$peer" ]; then echo "FAIL: $(1) has no peer for $(2)"; exit 1; fi; \
	hs=$$($(DC) exec -T alice wg show $(1) latest-handshakes \
	  | awk -v k="$$peer" '$$1 == k { print $$2 }'); \
	age=$$(( $$(date +%s) - $${hs:-0} )); \
	if [ "$${hs:-0}" -eq 0 ] || [ "$$age" -gt $(WG_REJECT_AFTER_TIME_S) ]; then \
	  echo "FAIL: $(1) peer $(2) has no handshake in the last $(WG_REJECT_AFTER_TIME_S)s"; exit 1; \
	fi; \
	echo "$(1) peer $(2): latest handshake $${age}s ago"
endef

.PHONY: smoke
# Three of these four steps used to end in a pipe or a `sleep`, so the recipe
# took THAT command's exit status: `... | head -c 400; echo` is always 0, and so
# is a `for` loop whose body ends in `sleep 1`. Only the ping could fail. A
# stack with the KME down, a 404 on /enc_keys and zero PSK rotations still
# printed "Smoke OK" and exited 0 -- and this is the documented merge gate.
#
# Each step now asserts on CONTENT. Deliberately not a global
# `.SHELLFLAGS := -eu -o pipefail -c`: that would change every recipe in this
# file, including ones that rely on a non-zero exit being tolerated, and none
# of those can be exercised here.
smoke: ## Quick end-to-end smoke test
	@echo "==> Wait for KME health..."
	@ok=0; for i in $$(seq 1 30); do \
	  if $(DC) exec -T bb84-kme-a curl -sf http://localhost:8080/health >/dev/null 2>&1; then ok=1; break; fi; \
	  sleep 1; \
	done; \
	if [ "$$ok" -ne 1 ]; then echo "FAIL: bb84-kme-a never became healthy"; exit 1; fi
	@echo "==> Verify ETSI-014 contract..."
	@out=$$($(DC) exec -T bb84-kme-a curl -sf "http://localhost:8080/api/v1/keys/ALICE/enc_keys?number=1&size=256"); \
	echo "$$out" | head -c 400; echo; \
	echo "$$out" | grep -q '"key_ID"' || { echo "FAIL: /enc_keys returned no key_ID"; exit 1; }
	@echo "==> Verify wg0 alice->bob (hop tunnel, keyed by arnika), waiting up to $(SMOKE_WG0_WAIT_S)s..."
	$(call smoke_ping,wg0,$(WG0_PEER_IP),$(SMOKE_WG0_WAIT_S))
	$(call smoke_handshake,wg0,$(WG0_PEER_IP))
	@echo "==> Verify wg1 alice->bob (data tunnel inside wg0, keyed by Rosenpass), waiting up to $(SMOKE_WG1_WAIT_S)s..."
	$(call smoke_ping,wg1,$(WG1_PEER_IP),$(SMOKE_WG1_WAIT_S))
	$(call smoke_handshake,wg1,$(WG1_PEER_IP))
	@echo "==> Check PSK rotation logs..."
	@n=$$($(DC) logs alice --since=2m 2>&1 | grep -cE "PSK configured|HKDF derivation completed"); \
	$(DC) logs alice --since=2m 2>&1 | grep -E "PSK configured|HKDF derivation completed" | head -n 5; \
	if [ "$$n" -eq 0 ]; then echo "FAIL: no PSK rotation in the last 2 minutes"; exit 1; fi
	@echo "==> Smoke OK"

.PHONY: test
test: ## Run pytest contract & integration tests
	$(VENV)/python -m pytest tests/ -v

# Counts, not a gate: PPK rotations R, auth failures F and the five failure
# classes on the IPsec lane, split by alice's role, from `docker logs -t` of
# both IPsec nodes. The rules are the ones written down in the script before any
# before/after run. Pass ARGS=--json for a record `compare` can read later, or
# ARGS="--since 2026-09-26T00:00:00Z" to leave out a window with a restart.
.PHONY: ppk-race-report
ppk-race-report: ## Count PPK rotations and failure classes on the IPsec lane
	$(VENV)/python scripts/ppk_race_report.py report --docker $(ARGS)

.PHONY: bench
bench: ## Run latency / throughput benchmarks
# Through the venv, not the shebang: `#!/usr/bin/env python3` resolves to the
# host's system interpreter (3.9 on the development host), which has none of
# this project's packages.
	$(VENV)/python benchmarks/handshake_timer.py
	./benchmarks/ping_loop.sh
	./benchmarks/iperf3_runner.sh

# -------------------------------------------------------------------
# Visualization
# -------------------------------------------------------------------
.PHONY: animations
animations: ## Render all Manim scenes
	cd animations && $(abspath $(VENV))/python -m manim -ql bb84_polarization.py BB84PolarizationScene
	cd animations && $(abspath $(VENV))/python -m manim -ql hkdf_combine.py HKDFCombineScene
	cd animations && $(abspath $(VENV))/python -m manim -ql multi_hop_network.py MultiHopScene

# -------------------------------------------------------------------
# Host-side OSS build (optional; used for pqc-tls-demo)
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# Phase 9 — Quantum-Secure VPN extensions
# -------------------------------------------------------------------
.PHONY: up-ipsec
up-ipsec: ## Start the strongSwan IPsec/IKEv2 lane (RFC 9370)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.strongswan.yml --profile ipsec up -d

.PHONY: down-ipsec
down-ipsec: ## Stop the strongSwan lane
	$(COMPOSE) -f docker-compose.yml -f docker-compose.strongswan.yml --profile ipsec down

.PHONY: pqc-tls-demo-both
pqc-tls-demo-both: ## Build both PQC TLS lanes (oqs-provider + OpenSSL 3.5 native)
	# Built directly, not through compose: no compose file defines a
	# `pqc-tls-demo-oqs` service, so `$(COMPOSE) build pqc-tls-demo-oqs` could
	# only ever fail into its own fallback. Both lanes are image-only build
	# artefacts with no compose service, and are treated the same way.
	docker build -t pqcqkd/pqc-tls-demo-oqs:local -f services/pqc-tls-demo/Dockerfile.oqs-provider .
	docker build -t pqcqkd/pqc-tls-demo-native:local -f services/pqc-tls-demo/Dockerfile.openssl35-native .

.PHONY: paper-compare
paper-compare: ## Compare benchmark results to Spooren et al. paper supplementary
	$(VENV)/python tools/compare_to_paper.py

.PHONY: browser-smoke
browser-smoke: ## Verify the WebUI in a real browser (requires Vite dev server running)
	cd services/webui-frontend && npm install --silent && npx vite build
	@echo "Built; start dev server with: cd services/webui-frontend && npx vite --host 0.0.0.0"

.PHONY: build-liboqs
build-liboqs: ## Build & install liboqs into /opt/oqs (requires sudo)
	cmake -S submodules/liboqs -B submodules/liboqs/build -GNinja \
		-DCMAKE_INSTALL_PREFIX=/opt/oqs \
		-DBUILD_SHARED_LIBS=ON \
		-DOQS_USE_OPENSSL=ON
	cmake --build submodules/liboqs/build --parallel
	sudo cmake --install submodules/liboqs/build

.PHONY: build-oqs-provider
build-oqs-provider: ## Build & install oqs-provider (requires liboqs)
	cmake -S submodules/oqs-provider -B submodules/oqs-provider/build -GNinja \
		-DCMAKE_PREFIX_PATH=/opt/oqs \
		-DCMAKE_INSTALL_PREFIX=/opt/oqs
	cmake --build submodules/oqs-provider/build --parallel
	sudo cmake --install submodules/oqs-provider/build

.PHONY: pqc-list
pqc-list: ## List PQC algorithms exposed by oqs-provider
	OPENSSL_MODULES=/opt/oqs/lib64/ossl-modules openssl list -kem-algorithms -provider oqsprovider | head -n 30

# -------------------------------------------------------------------
# Lint / format
# -------------------------------------------------------------------
# CI_LINT_PATHS must equal the argument list in .github/workflows/ci.yml's
# `ruff check` step. tests/test_make_lint_matches_ci.py parses both files and
# fails if they drift -- the help text below claims they are the same, and that
# claim was false for however long animations/ has been in this list.
#
# What was wrong: `lint` ran ruff over `services/ tests/ tools/ animations/
# benchmarks/` while CI runs it over `services/ tests/ tools/ benchmarks/`.
# animations/ has 149 errors today, so `make lint` fails locally on code CI is
# green about, while advertising "same rules as CI". A developer who runs the
# documented command sees a wall of errors that no gate cares about, and the
# reasonable response -- ignoring `make lint` -- also disables it for the paths
# that DO gate.
#
# animations/ stays unlinted rather than being cleaned up, and that is a
# decision, not an oversight: those are Manim scenes that render documentation
# videos. Nothing imports them, no image ships them, and Manim's idioms trip
# rules chosen for service code. `lint-animations` exists for anyone who wants
# to look; it is deliberately not a gate.
CI_LINT_PATHS = services/ tests/ tools/ benchmarks/ scripts/

# `.venv/bin/`, not `python3.12 -m`. The system interpreter has neither ruff nor
# pytest here, so the documented commands exited "No module named ruff" -- a
# target that cannot run is not a gate either. VERIFICATION_CHECKLIST's
# one-command block already used .venv; the Makefile had not caught up.
VENV ?= .venv/bin

.PHONY: fmt
fmt: ## Format Python with ruff (same paths as CI lints)
	$(VENV)/ruff format $(CI_LINT_PATHS)

.PHONY: lint
lint: ## Lint Python with ruff (exactly what CI's python job runs)
# No `|| true`. These targets used to swallow every failure, so `make lint`
# reported success no matter what -- which is why 99 lint errors accumulated
# unnoticed, one of them a reference to an undefined name.
	$(VENV)/ruff check $(CI_LINT_PATHS)

.PHONY: lint-animations
lint-animations: ## Lint animations/ (NOT a gate; CI does not run this)
	@echo "animations/ is not linted by CI -- see the note above CI_LINT_PATHS."
	@echo "Manim scenes, not shipped code. Failures here block nothing."
	$(VENV)/ruff check animations/
