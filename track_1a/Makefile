.PHONY: run dev dashboard test docker-build

IMAGE ?= apertus-redteam
# Inside Docker the host's SSH tunnel (127.0.0.1:8000) is reached via host.docker.internal.
LLM_BASE_URL ?= http://host.docker.internal:8000/v1

# Judges: `make run` builds the image, runs the full agent graph, validates every findings file.
# With no reachable LLM endpoint it replays the recorded run from data/llm_cache (no GPU).
run: docker-build
	docker run --rm --add-host=host.docker.internal:host-gateway \
	  -e LLM_BASE_URL=$(LLM_BASE_URL) -e LLM_NAME -e LLM_API_KEY \
	  -v "$(CURDIR)/runs:/app/runs" $(IMAGE)

docker-build:
	docker build -t $(IMAGE) .

# Local development (no Docker), reaches the tunnel on 127.0.0.1:8000 directly.
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
