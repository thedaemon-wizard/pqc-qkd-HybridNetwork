# ===================================================================
# PQC-QKD Hybrid PoC — Makefile
# ===================================================================
SHELL := /bin/bash
PROJECT ?= pqcqkd
COMPOSE ?= docker compose

# Compose file selection
COMPOSE_FILES ?= -f docker-compose.yml
# Append override files manually, e.g.:
#   make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.boringtun.yml"

DC = $(COMPOSE) $(COMPOSE_FILES)

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------
.PHONY: init
init: ## Initialize: env file, submodules, certs
	@test -f .env || cp .env.example .env
	git submodule update --init --recursive
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

# -------------------------------------------------------------------
# Verification / Smoke
# -------------------------------------------------------------------
.PHONY: smoke
smoke: ## Quick end-to-end smoke test
	@echo "==> Wait for KME health..."
	@for i in $$(seq 1 30); do \
	  $(DC) exec -T bb84-kme-a curl -sf http://localhost:8080/health >/dev/null 2>&1 && break; \
	  sleep 1; \
	done
	@echo "==> Verify ETSI-014 contract..."
	$(DC) exec -T bb84-kme-a curl -sf "http://localhost:8080/api/v1/keys/ALICE/enc_keys?number=1&size=256" | head -c 400; echo
	@echo "==> Verify wg0 ping alice->bob..."
	$(DC) exec -T alice ping -c 3 -W 2 10.0.0.2 || (echo "FAIL: ping over wg0"; exit 1)
	@echo "==> Check PSK rotation logs..."
	$(DC) logs alice --since=2m | grep -E "PSK configured|HKDF derivation completed" | head -n 5
	@echo "==> Smoke OK"

.PHONY: test
test: ## Run pytest contract & integration tests
	python3.12 -m pytest tests/ -v

.PHONY: bench
bench: ## Run latency / throughput benchmarks
	./benchmarks/handshake_timer.py
	./benchmarks/ping_loop.sh
	./benchmarks/iperf3_runner.sh

# -------------------------------------------------------------------
# Visualization
# -------------------------------------------------------------------
.PHONY: animations
animations: ## Render all Manim scenes
	cd animations && python3.12 -m manim -ql bb84_polarization.py BB84PolarizationScene
	cd animations && python3.12 -m manim -ql hkdf_combine.py HKDFCombineScene
	cd animations && python3.12 -m manim -ql multi_hop_network.py MultiHopScene

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
	$(COMPOSE) build pqc-tls-demo-oqs || \
	docker build -t pqcqkd/pqc-tls-demo-oqs:local -f services/pqc-tls-demo/Dockerfile.oqs-provider .
	docker build -t pqcqkd/pqc-tls-demo-native:local -f services/pqc-tls-demo/Dockerfile.openssl35-native .

.PHONY: paper-compare
paper-compare: ## Compare benchmark results to Spooren et al. paper supplementary
	source .venv/bin/activate && python tools/compare_to_paper.py

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
.PHONY: fmt
fmt: ## Format Python with ruff
	python3.12 -m ruff format services/ tests/ animations/ benchmarks/ || true

.PHONY: lint
lint: ## Lint Python with ruff
	python3.12 -m ruff check services/ tests/ animations/ benchmarks/ || true
