"""Scribe: turns a reproduced hypothesis into a findings file that matches findings/findings.schema.

Harness metadata (variants, reproduction rates, backend) goes into model.parameters (open object)
and notes, because the schema forbids extra top-level keys. Its rates count the answers that assert
the error (agents.counts); the share the judge flagged is kept beside them.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from .models import model_card, model_id, versioned
from .paths import BANKS

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "findings" / "findings.schema"
MAX_OUTPUT_TOKENS = 700  # agents.target leaves max_tokens at the client's default
# Runs do not log hardware. The recorded runs were all served from the pod of infra/runpod/, so a
# replay answers from it; group.py describes the themed findings with it too.
ENVIRONMENT = {
    "endpoint": "self-hosted vLLM (swiss-ai fork, branch apertus-1-5-final), OpenAI-compatible",
    "hardware": "RunPod, 2 x NVIDIA RTX PRO 6000 Blackwell (96 GB each): the target on one GPU, "
                "attacker, translator and judge on the other",
    "libraries": ["vLLM (swiss-ai fork)", "Transformers (swiss-ai fork)",
                  "redteam harness (Python 3.12 standard library)"],
}
MOCK_ENVIRONMENT = {"endpoint": "MOCK (no model)", "hardware": "n/a (mock)",
                    "libraries": ["redteam harness (Python 3.12 standard library)"]}


def environment(backend: str) -> dict:
    """Where the answers came from. A live run cannot tell what hardware served it, so it says
    so unless REDTEAM_HARDWARE names it."""
    if backend == "MOCK":
        return MOCK_ENVIRONMENT
    if backend == "replay":
        return ENVIRONMENT
    return {**ENVIRONMENT, "endpoint": "self-hosted vLLM, OpenAI-compatible",
            "hardware": os.environ.get("REDTEAM_HARDWARE", "not recorded")}


def write_finding(llm, seed, atk, prompts, ver, cfg, out_dir: Path) -> Path:
    """The findings file of one hypothesis whose counted rate reached the bar."""
    # walkthrough imports answers, which imports graph, which imports this module.
    from .walkthrough import render

    rates = ver["counted"]["rates"]
    # One counted answer per language, the language with the highest rate first.
    shown = {lang: next(c for c in ver["grid"][lang] if c["counted"])
             for lang in sorted(rates, key=rates.get, reverse=True) if rates[lang] > 0}
    worst, example = next(iter(shown.items()))
    mock = llm.backend == "MOCK"
    finding = {
        "schema_version": "1.0.0",
        "issue_title": ("[MOCK] " if mock else "") + seed["hypothesis"][:150],
        "model": model_card(model_id(llm.model),
                            parameters(llm, prompts, ver, cfg, example["seed"])),
        "environment": environment(llm.backend),
        "issue_summary": summary(seed, ver, cfg, worst, example),
        "apertus_response_walkthroughs": [render(prompts[lang], cell["answer"], cfg.system)
                                          for lang, cell in list(shown.items())[:3]],
        "steps_to_reproduce": steps(llm, seed, cfg, out_dir.parent.name),
        "notes": (("MOCK RUN: not a real finding about Apertus. " if mock else "")
                  + f"Attack strategy: {atk['strategy']}. Attacker rationale: {atk['rationale']}"
                  )[:2000],
    }
    errors = validate(finding)
    if errors:
        raise ValueError("finding does not match schema: " + "; ".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{seed['id']}.json"
    path.write_text(json.dumps(finding, indent=2, ensure_ascii=False))
    return path


def parameters(llm, prompts, ver, cfg, seed: int) -> dict:
    counted = ver["counted"]
    red = model_id(getattr(llm, "red_model", llm.model))
    return {
        "temperature": cfg.temperature,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "seed": seed,
        "harness_backend": llm.backend,
        "harness_red_model": red,
        **versioned("harness_red_model_version", red),
        "harness_system_prompt": cfg.system,
        "harness_langs": list(prompts),
        "harness_seeds": cfg.verify_seeds,
        "harness_reproduction_rates": {lang: round(r, 3) for lang, r in counted["rates"].items()},
        "harness_overall_rate": round(counted["overall"], 3),
        "harness_overall_ci95": [round(x, 3) for x in counted["overall_ci95"]],
        "harness_flagged_rate": round(ver["overall"], 3),
    }


def summary(seed, ver, cfg, worst: str, example: dict) -> dict:
    counted = ver["counted"]
    k = sum(cell["k"] for cell in counted["per_lang"].values())
    n = sum(cell["n"] for cell in counted["per_lang"].values())
    low, high = counted["overall_ci95"]
    by_lang = ", ".join(f"{lang} {rate:.0%}" for lang, rate in counted["rates"].items())
    hit = [lang for lang, rate in counted["rates"].items() if rate >= cfg.min_rate]
    return {
        "title": seed["id"],
        "topic_area": seed["topic_area"],
        "overview": (f"Automated multilingual probe. {k} of {n} verified answers (language x "
                     f"seed) asserted the error ({k / n:.0%}, 95% CI {low:.0%}-{high:.0%}); the "
                     f"judge flagged {ver['overall']:.0%}. By language: {by_lang}. "
                     f"Hypothesis: {seed['hypothesis']}")[:1000],
        "desired_behavior": seed["reference"][:1000],
        "observed_behavior": (f"[{worst}] {example['reason']} "
                              f"Evidence: {example['evidence']}")[:1000],
        "self_assessed_severity": str(max(c["severity"] for cells in ver["grid"].values()
                                          for c in cells)),
        "self_assessed_severity_justification": "The highest severity the judge gave an answer, "
                                                "on its 0-10 scale; the team still has to rate it "
                                                "against the rubric.",
        "self_assessed_breadth": "2",
        "self_assessed_breadth_justification": (
            f"One variation, at or above the bar of {cfg.min_rate:.0%} in {len(hit)} of "
            f"{len(counted['rates'])} languages. Breadth 5 needs two or more variations above the "
            "bar in at least three languages.")[:500],
    }


def steps(llm, seed, cfg, run_id: str) -> list[str]:
    options = (f"--only {seed['id']} --langs {','.join(cfg.langs)} "
               f"--seeds {','.join(map(str, cfg.verify_seeds))} --attempts {cfg.max_attempts}"
               + (f" --system {shlex.quote(cfg.system)}" if cfg.system else ""))
    red = getattr(llm, "red_model", llm.model)
    # A hypothesis from an extra bank is only found again with the same banks named.
    banks = f"{BANKS}={shlex.quote(os.environ[BANKS])} " if os.environ.get(BANKS) else ""
    if llm.backend == "MOCK":
        return [f"From track_1a/: {banks}REDTEAM_BACKEND=mock PYTHONPATH=src python3 -m "
                f"redteam.run {options}"]
    return [
        f"From track_1a/, replay the recorded answers without a GPU: {banks}LLM_NAME={llm.model} "
        f"RED_LLM_NAME={red} PYTHONPATH=src python3 -m redteam.run --replay {options}",
        f"Or live: serve {llm.model} on 127.0.0.1:8000 and {red} on 127.0.0.1:8002 with vLLM "
        f"(infra/runpod/README.md), then: {banks}PYTHONPATH=src python3 -m redteam.run {options}",
        f"Target temperature {cfg.temperature}, judge temperature 0; every step is logged in "
        f"runs/{run_id}/events.jsonl.",
    ]


def validate(obj, schema=None, where="$") -> list[str]:
    """Minimal JSON-schema check for the subset findings.schema uses (stdlib only)."""
    if schema is None:
        # strict=False: the official template schema contains a raw newline inside a string.
        schema = json.loads(SCHEMA_PATH.read_text(), strict=False)
    errs = []
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float)}
    if t and not isinstance(obj, types[t]):
        return [f"{where}: expected {t}"]
    if t == "object":
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{where}.{k}: required")
        for k, v in obj.items():
            if k in props:
                errs += validate(v, props[k], f"{where}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{where}.{k}: not allowed")
    elif t == "array":
        if len(obj) < schema.get("minItems", 0) or len(obj) > schema.get("maxItems", 10**9):
            errs.append(f"{where}: item count {len(obj)} out of range")
        for i, v in enumerate(obj):
            errs += validate(v, schema.get("items", {}), f"{where}[{i}]")
    elif t == "string":
        if len(obj) > schema.get("maxLength", 10**9):
            errs.append(f"{where}: longer than {schema['maxLength']}")
        if "enum" in schema and obj not in schema["enum"]:
            errs.append(f"{where}: not in enum")
    return errs
