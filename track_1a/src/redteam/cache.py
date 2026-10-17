"""Disk cache of every LLM call, keyed by model + request.

Live runs fill it; replay runs answer only from it. That lets `make run` reproduce a run
exactly on a machine without a GPU, and makes the findings check itself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "llm_cache"


class CacheMiss(RuntimeError):
    pass


def _key(model: str, messages, temperature, seed, max_tokens) -> str:
    req = {"model": model, "messages": messages, "temperature": temperature, "seed": seed,
           "max_tokens": max_tokens}
    return hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Cached:
    """Wraps a client. With replay=True the client is never called."""

    def __init__(self, client, model: str, replay: bool = False, root: Path = CACHE_DIR):
        self.client, self.model, self.replay, self.root = client, model, replay, root
        self.backend = "replay" if replay else client.backend

    def chat(self, messages, *, role, temperature=0.0, seed=None, max_tokens=700):
        k = _key(self.model, messages, temperature, seed, max_tokens)
        path = self.root / k[:2] / f"{k}.json"
        if path.exists():
            return json.loads(path.read_text())["content"]
        if self.replay:
            raise CacheMiss(f"{role} call not in cache ({k[:12]})")
        content = self.client.chat(messages, role=role, temperature=temperature, seed=seed,
                                   max_tokens=max_tokens)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"role": role, "model": self.model, "content": content},
                                   ensure_ascii=False))
        return content
