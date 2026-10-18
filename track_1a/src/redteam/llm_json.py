"""Getting one JSON object out of a chat model, with a single repair round."""
from __future__ import annotations

import json
import re


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (models often wrap it in prose/fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    return json.loads(m.group(0))


def ask_json(llm, msg: str, role: str, max_tokens: int = 1500) -> dict:
    """One call, plus one repair round if the model's JSON is broken or cut off."""
    messages = [{"role": "user", "content": msg}]
    reply = llm.chat(messages, role=role, temperature=0.0, max_tokens=max_tokens)
    try:
        return parse_json(reply)
    except ValueError:  # json.JSONDecodeError is a ValueError too
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "That was not valid JSON. Reply again with the "
                      "same content as one valid JSON object, nothing else. Keep it short."}]
        repaired = llm.chat(messages, role=role, temperature=0.0, max_tokens=max_tokens)
        try:
            return parse_json(repaired)
        except ValueError:
            # Last resort only, so replies that parsed before keep their exact path (replay stays exact).
            return lenient_json(repaired, reply)


def lenient_json(*replies: str) -> dict:
    """Accept raw newlines inside strings and trailing text after the object."""
    decoder = json.JSONDecoder(strict=False)
    for text in replies:
        start = text.find("{")
        if start != -1:
            try:
                return decoder.raw_decode(text, start)[0]
            except ValueError:
                continue
    raise ValueError(f"no parseable JSON object in reply: {replies[0][:200]!r}")
