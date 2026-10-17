"""LLM backends: OpenAI-compatible endpoints (vLLM serving Apertus), cache replay, and a MOCK.

Mock output is canned text for exercising the graph. It is never a finding about Apertus.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from .cache import CACHE_DIR, Cached

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"


class OpenAIChat:
    backend = "vllm"

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def _post(self, path: str, body: dict, timeout: float = 180) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def chat(self, messages: list[dict], *, role: str, temperature: float = 0.0,
             seed: int | None = None, max_tokens: int = 700) -> str:
        body = {"model": self.model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens}
        if seed is not None:
            body["seed"] = seed
        out = self._post("/chat/completions", body)
        return out["choices"][0]["message"]["content"] or ""


class MockLLM:
    """Deterministic stand-in so the loop, dashboard and tests run without a GPU. LABELLED MOCK."""
    backend = "MOCK"
    model = "MOCK-no-model"

    def chat(self, messages: list[dict], *, role: str, temperature: float = 0.0,
             seed: int | None = None, max_tokens: int = 700) -> str:
        time.sleep(float(os.environ.get("REDTEAM_MOCK_DELAY", "0")))  # lets the dashboard animate
        last = messages[-1]["content"]
        h =int(hashlib.sha256(f"{role}|{last}|{seed}".encode()).hexdigest(), 16)
        if role == "attacker":
            hyp = _field(last, "HYPOTHESIS")
            return json.dumps({"prompt": f"[MOCK attack] {hyp[:160]} Please answer briefly.",
                               "rationale": "MOCK: restate hypothesis as a direct user question."})
        if role == "mutator":
            lang = _field(last, "TARGET LANGUAGE")
            return f"[MOCK {lang}] " + _field(last, "TEXT")
        if role == "langid":
            for code, name in [("Swiss German", "Swiss German"), ("Romansh", "Romansh"),
                               ("Standard German", "German"), ("French", "French"),
                               ("Italian", "Italian")]:
                if f"[MOCK {code}" in last:
                    return name
            return "English"
        if role == "target":
            # Mock pretends minority languages fail more often, so the dashboard has a pattern to show.
            flawed = h % 100 < (70 if "[MOCK Romansh" in last or "[MOCK Swiss German" in last else 35)
            return ("MOCK answer containing a deliberately wrong claim." if flawed
                    else "MOCK answer that matches the reference.")
        if role == "judge":
            bad = "deliberately wrong" in last
            return json.dumps({"violation": bad, "severity": 2 if bad else 0,
                               "reason": "MOCK judge: keyword rule on mock text.",
                               "evidence": "deliberately wrong claim" if bad else ""})
        return "MOCK"


def _field(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def probe(base_url: str, api_key: str = "", timeout: float = 3) -> str | None:
    """Return the first served model id, or None if the endpoint is unreachable."""
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read()).get("data", [])
            return data[0]["id"] if data else None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


DEFAULT_RED_BASE_URL = "http://127.0.0.1:8002/v1"


class Router:
    """Sends the target role to the model under test and every other role (attacker, mutator,
    judge, langid) to the red-team model, e.g. Apertus 70B judging Apertus 8B."""

    def __init__(self, target, red):
        self.target, self.red = target, red
        self.backend, self.model, self.red_model = target.backend, target.model, red.model

    def chat(self, messages, *, role, **kw):
        return (self.target if role == "target" else self.red).chat(messages, role=role, **kw)


def _connect(base: str, name_env: str, key_env: str):
    key = os.environ.get(key_env, "")
    served = probe(base, key)
    return None if served is None else OpenAIChat(base, os.environ.get(name_env) or served, key)


MODELS_FILE = CACHE_DIR / "models.json"


def _replay():
    # models.json names the canonical run; LLM_NAME / RED_LLM_NAME replay any other run.
    models = json.loads(MODELS_FILE.read_text())
    return Router(Cached(None, os.environ.get("LLM_NAME") or models["target"], replay=True),
                  Cached(None, os.environ.get("RED_LLM_NAME") or models["red"], replay=True))


def detect():
    """Live endpoints if reachable, else replay from the cache, else the labelled MOCK.

    Target from LLM_BASE_URL; red-team model from RED_LLM_BASE_URL (falls back to the target).
    REDTEAM_BACKEND=mock|replay forces a mode.
    """
    mode = os.environ.get("REDTEAM_BACKEND", "").lower()
    if mode == "mock":
        return MockLLM()
    if mode == "replay":
        return _replay()
    target = _connect(os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL), "LLM_NAME", "LLM_API_KEY")
    if target is None:
        return _replay() if MODELS_FILE.exists() else MockLLM()
    red = _connect(os.environ.get("RED_LLM_BASE_URL", DEFAULT_RED_BASE_URL),
                   "RED_LLM_NAME", "RED_LLM_API_KEY") or target
    if not MODELS_FILE.exists():  # the first live run becomes the one `make run` replays
        MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODELS_FILE.write_text(json.dumps({"target": target.model, "red": red.model}))
    return Router(Cached(target, target.model), Cached(red, red.model))
