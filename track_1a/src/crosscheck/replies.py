"""Recorded replies looked up in the LLM cache. Each call is rebuilt as the harness made it,
since the cache key hashes the model, the messages, the temperature, the seed and the token
limit, and any difference finds nothing. How the judge replies read is tallied, since a reading
rule the harness shares would not show in the counts."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from redteam.cache import _key, read_pack
from redteam.judge import CLAIMS_PROMPT, PREMISE_PROMPT

from .verdicts import SECOND_FLAGS, lenient_object, strict_object, typed

TARGET_TEMPERATURE = 0.7  # the verifier samples the target at this temperature
TARGET_MAX_TOKENS = 700  # the target is called without a limit, so the client's default applies
CLAIMS_MAX_TOKENS = 1500
PREMISE_MAX_TOKENS = 400
# The turn the harness adds when a judge reply is not valid JSON. The repaired reply is a call
# of its own, so the text must match to the character for its key to be found.
REPAIR = ("That was not valid JSON. Reply again with the same content as one valid JSON object, "
          "nothing else. Keep it short.")


class Missing(LookupError):
    """A call the run made has no reply in the cache."""


class Replies:
    def __init__(self, entries: dict[str, dict]):
        self.entries = entries
        self.tally: Counter[str] = Counter()

    @classmethod
    def read(cls, pack: Path) -> Replies:
        return cls(read_pack(pack))

    def reply(self, model: str, messages: list[dict], temperature: float, seed: int | None,
              max_tokens: int) -> str:
        key = _key(model, messages, temperature, seed, max_tokens)
        if key not in self.entries:
            raise Missing(f"no cached reply of {model} under {key[:12]}")
        return self.entries[key]["content"]

    def answer(self, model: str, prompt: str, seed: int, system: str | None) -> str:
        """The target's verified answer to a prompt with one sampling seed."""
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return self.reply(model, messages, TARGET_TEMPERATURE, seed, TARGET_MAX_TOKENS)

    def json_reply(self, model: str, text: str, max_tokens: int) -> dict:
        messages = [{"role": "user", "content": text}]
        first = self.reply(model, messages, 0.0, None, max_tokens)
        self.tally["judge replies"] += 1
        try:
            return strict_object(first)
        except ValueError:
            self.tally["took the repair turn"] += 1
        retry = messages + [{"role": "assistant", "content": first},
                            {"role": "user", "content": REPAIR}]
        repaired = self.reply(model, retry, 0.0, None, max_tokens)
        try:
            return strict_object(repaired)
        except ValueError:
            self.tally["then read leniently"] += 1
            return lenient_object(repaired, first)

    def claims(self, model: str, reference: str, prompt: str, answer: str) -> dict:
        """The main judge's reply: the answer's claims checked against the reference."""
        text = CLAIMS_PROMPT.format(reference=reference, prompt=prompt, answer=answer)
        reply = self.json_reply(model, text, CLAIMS_MAX_TOKENS)
        self.tally["claims replies"] += 1
        self.tally["claims replies with an int severity and a bool behaviour flag"] += typed(
            reply, {"severity": int, "behavior_violation": bool})
        return reply

    def premise(self, model: str, reference: str, prompt: str, answer: str) -> dict:
        """The second, independently worded judge's reply."""
        text = PREMISE_PROMPT.format(answer=answer, prompt=prompt, reference=reference)
        reply = self.json_reply(model, text, PREMISE_MAX_TOKENS)
        self.tally["second-judge replies"] += 1
        self.tally["second-judge replies with three bool answers"] += typed(
            reply, dict.fromkeys(SECOND_FLAGS, bool))
        return reply
