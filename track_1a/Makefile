.PHONY: run live dev dashboard test crosscheck docker-build

IMAGE ?= apertus-redteam
DOCKER_RUN = docker run --rm -v "$(CURDIR)/runs:/app/runs"

# Judges: builds the image, replays the canonical run from data/llm_cache, validates every findings
# file, rebuilds the five findings from data/runs (the speech finding from per-clip scores, keeping
# the model outputs it quotes) and fails on any difference with findings/, then prints the
# report's summary table. Always a replay: no GPU, and a model server that happens to answer on
# the tunnel is never called.
run: docker-build
	$(DOCKER_RUN) -e REDTEAM_BACKEND=replay $(IMAGE)

# A new run against the live model servers, e.g. make live ARGS="--only hist_womens_suffrage_1971".
# ARGS reaches redteam.run as the shell splits it, so quote inside it: ARGS="--system 'Be brief.'".
# Inside the container 127.0.0.1 is the container itself, so the host's SSH tunnels (:8000 target,
# :8002 attacker and judge) are reached via host.docker.internal; set LIVE_LLM_BASE_URL and
# LIVE_RED_LLM_BASE_URL for other servers (LLM_BASE_URL is the host's own view and is not used).
# It stops before the run unless both servers answer, instead of replaying from the cache or letting
# the target act as its own attacker and judge (for that, set LIVE_RED_LLM_BASE_URL to the target's
# URL). New calls are added to data/llm_cache on the host, one file each, so the run can be replayed
# afterwards; the image leaves those files out until scripts/pack_cache.py folds them into the pack.
LIVE_LLM_BASE_URL ?= http://host.docker.internal:8000/v1
LIVE_RED_LLM_BASE_URL ?= http://host.docker.internal:8002/v1
ARGS ?=
LIVE_RUN = $(DOCKER_RUN) --add-host=host.docker.internal:host-gateway \
  -v "$(CURDIR)/data/llm_cache:/app/data/llm_cache" \
  -e LLM_BASE_URL="$(LIVE_LLM_BASE_URL)" -e LLM_NAME -e LLM_API_KEY \
  -e RED_LLM_BASE_URL="$(LIVE_RED_LLM_BASE_URL)" -e RED_LLM_NAME -e RED_LLM_API_KEY $(IMAGE)
live: docker-build
	$(LIVE_RUN) python -c 'from redteam import llm; llm.require_servers()'
	$(LIVE_RUN) python -m redteam.run $(ARGS)
	$(DOCKER_RUN) $(IMAGE) python -m redteam.check

docker-build:
	docker build -t $(IMAGE) .

# Local development (no Docker), reaches the tunnels on 127.0.0.1:8000 and :8002 directly.
dev:
	PYTHONPATH=src python3 -m redteam.run

# Reuses an already-running dashboard instead of failing on the busy port.
PORT ?= 8765
dashboard:
	@if curl -sf -o /dev/null http://127.0.0.1:$(PORT)/api/runs; then \
	  echo "dashboard already running: http://127.0.0.1:$(PORT)"; open http://127.0.0.1:$(PORT) 2>/dev/null || true; \
	else PORT=$(PORT) PYTHONPATH=src python3 -m redteam.server; fi

test:
	python3 -m unittest discover tests -v

# A second derivation of every number in findings/, docs/figures/numbers.json and the report, from
# data/runs and data/llm_cache without the harness's counting code; fails on any difference.
crosscheck:
	PYTHONPATH=src python3 -m crosscheck
