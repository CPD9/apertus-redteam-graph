"""What "Start a new run" on the dashboard would use now, decided the way llm.detect() decides: the
target's endpoint if it answers, else a replay of the cached run named in models.json, else canned
mock answers. REDTEAM_BACKEND forces mock or replay, and LLM_NAME / RED_LLM_NAME make a replay
repeat the cached answers of other models than the named run's.

Every dashboard poll carries the answer, every 700 ms while a run is live, so it is kept for KEEP_S
seconds instead of probing the endpoint each time. Only the host and port of the endpoint are
named: the page may be read by others.
"""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from urllib.parse import urlparse

from . import llm

KEEP_S = 30


def plan() -> dict:
    return _decide(int(time.time() // KEEP_S))


# window only keys the cache: one answer per KEEP_S seconds.
@lru_cache(maxsize=1)
def _decide(window: int) -> dict:
    forced = os.environ.get("REDTEAM_BACKEND", "").lower()
    url = urlparse(os.environ.get("LLM_BASE_URL", llm.DEFAULT_BASE_URL))
    if forced in ("mock", "replay"):
        backend = "MOCK" if forced == "mock" else "replay"
    elif llm.probe(url.geturl(), os.environ.get("LLM_API_KEY", ""), timeout=1) is not None:
        backend = "vllm"
    else:
        backend = "replay" if llm.MODELS_FILE.exists() else "MOCK"
    replay = _replay() if backend == "replay" else {}
    return {"backend": backend, "forced": forced in ("mock", "replay"),
            "endpoint": f"{url.hostname}:{url.port}" if url.port else url.hostname,
            "replays": replay.get("run"), "replay_model": replay.get("model")}


def _replay() -> dict:
    """The run a replay repeats, which models.json names once a live run has written it, and the
    model whose cached answers it replays. llm._replay() takes LLM_NAME and RED_LLM_NAME over
    models.json; with either set to another model the replay no longer repeats the named run."""
    try:
        models = json.loads(llm.MODELS_FILE.read_text())
    except (OSError, ValueError):
        models = {}
    if not isinstance(models, dict):
        models = {}
    target = os.environ.get("LLM_NAME") or models.get("target")
    red = os.environ.get("RED_LLM_NAME") or models.get("red")
    same = target == models.get("target") and red == models.get("red")
    return {"run": models.get("run_id") if same else None, "model": target}
