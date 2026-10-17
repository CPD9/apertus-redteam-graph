"""Disk cache of every LLM call, keyed by model + request.

Live runs fill it; replay runs answer only from it. That lets `make run` reproduce a run
exactly on a machine without a GPU, and makes the findings check itself.

A live run writes each call to its own file, <root>/<key[:2]>/<key>.json. The calls of the
recorded runs are kept in one compressed file, <root>/pack.jsonl.xz (scripts/pack_cache.py), so
the repository holds one file instead of thousands. The pack is read only when a call has no file
of its own, and then whole, once per process; a call's own file wins over the pack.
"""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import threading
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "llm_cache"
PACK = "pack.jsonl.xz"

_packs: dict[Path, tuple[int, dict[str, dict]]] = {}  # pack path -> (mtime, entries by key)
_packs_lock = threading.Lock()  # the verifier looks calls up from several threads


class CacheMiss(RuntimeError):
    pass


def _key(model: str, messages, temperature, seed, max_tokens) -> str:
    req = {"model": model, "messages": messages, "temperature": temperature, "seed": seed,
           "max_tokens": max_tokens}
    return hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def entry_path(root: Path, key: str) -> Path:
    return root / key[:2] / f"{key}.json"


def read_pack(path: Path) -> dict[str, dict]:
    """Every entry of a pack by key: one JSON object per line, with its key under "key"."""
    with lzma.open(path, "rt", encoding="utf-8") as f:
        return {entry.pop("key"): entry for entry in map(json.loads, f)}


def packed(root: Path) -> dict[str, dict]:
    """The pack of a cache directory, read on first use and again only if the file changes."""
    path = root / PACK
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    with _packs_lock:
        if path not in _packs or _packs[path][0] != mtime:
            _packs[path] = (mtime, read_pack(path))
        return _packs[path][1]


def write_entry(path: Path, entry: dict) -> None:
    """Write a call's own file whole or not at all, so a run stopped mid-write leaves no cut-off
    file to fail every later replay. The temporary name is unique to the process and thread,
    since a run writes calls from several threads at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Not mkstemp: its files are owner-only, and `make live` writes the cache as root in Docker.
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(entry, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def lookup(root: Path, key: str) -> dict | None:
    try:
        return json.loads(entry_path(root, key).read_text())
    except FileNotFoundError:
        return packed(root).get(key)


class Cached:
    """Wraps a client. With replay=True the client is never called."""

    def __init__(self, client, model: str, replay: bool = False, root: Path = CACHE_DIR):
        self.client, self.model, self.replay, self.root = client, model, replay, root
        self.backend = "replay" if replay else client.backend

    def chat(self, messages, *, role, temperature=0.0, seed=None, max_tokens=700):
        k = _key(self.model, messages, temperature, seed, max_tokens)
        entry = lookup(self.root, k)
        if entry is not None:
            return entry["content"]
        if self.replay:
            raise CacheMiss(f"{role} call not in cache ({k[:12]})")
        content = self.client.chat(messages, role=role, temperature=temperature, seed=seed,
                                   max_tokens=max_tokens)
        write_entry(entry_path(self.root, k),
                    {"role": role, "model": self.model, "content": content})
        return content
