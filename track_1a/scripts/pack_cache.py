"""Fold the LLM calls stored as their own files into the cache's one compressed pack.

    python3 scripts/pack_cache.py [--root data/llm_cache] [--prune]

A live run writes each new call to its own file in data/llm_cache. This writes a new
data/llm_cache/pack.jsonl.xz holding every entry of the old pack and every own file (an own file
wins, as it does when the cache is read). The new pack replaces the old one only after it reads
back equal, entry by entry. With --prune, the own files it now holds are deleted afterwards;
nothing is deleted otherwise. The same entries always give the same bytes: lines sorted by key,
keys sorted within each line, and no timestamp in the file.
"""
from __future__ import annotations

import argparse
import json
import lzma
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.cache import CACHE_DIR, PACK, read_pack  # noqa: E402


def own_files(root: Path) -> dict[str, Path]:
    """Every call stored as its own file, by key."""
    return {path.stem: path for path in sorted(root.glob("??/*.json"))}


def encode(entries: dict[str, dict]) -> bytes:
    lines = (json.dumps({"key": key, **entries[key]}, ensure_ascii=False, sort_keys=True) + "\n"
             for key in sorted(entries))
    return lzma.compress("".join(lines).encode())


def pack(root: Path) -> tuple[dict[str, dict], dict[str, Path]]:
    """Write the new pack; returns its entries and the own files it took in."""
    path = root / PACK
    entries = read_pack(path) if path.exists() else {}
    files = own_files(root)
    entries.update({key: json.loads(file.read_text()) for key, file in files.items()})
    new = path.with_name(PACK + ".new")
    new.write_bytes(encode(entries))
    if read_pack(new) != entries:
        new.unlink()
        raise SystemExit(f"the new pack did not read back equal; {path} is unchanged")
    os.replace(new, path)
    return entries, files


def prune(entries: dict[str, dict], files: dict[str, Path]) -> int:
    """Delete the own files whose entry the pack holds unchanged, then their emptied folders."""
    pruned = 0
    for key, file in files.items():
        if json.loads(file.read_text()) == entries[key]:
            file.unlink()
            pruned += 1
    for folder in {file.parent for file in files.values()}:
        if not any(folder.iterdir()):
            folder.rmdir()
    return pruned


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=CACHE_DIR, help="cache directory")
    ap.add_argument("--prune", action="store_true",
                    help="delete the own files once the new pack holds them")
    args = ap.parse_args(argv)
    entries, files = pack(args.root)
    size = (args.root / PACK).stat().st_size
    print(f"{args.root / PACK}: {len(entries)} calls, {len(files)} from own files, "
          f"{size / 1e6:.1f} MB")
    if args.prune:
        print(f"deleted {prune(entries, files)} own files now in the pack")


if __name__ == "__main__":
    main()
