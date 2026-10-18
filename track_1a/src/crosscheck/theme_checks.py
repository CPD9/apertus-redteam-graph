"""The model.parameters of a themed finding against the theme measured again."""
from __future__ import annotations

from .checks import Check, rounded, rounding
from .rates import by_lang, paired_difference, pooled_interval, share
from .replies import TARGET_MAX_TOKENS, TARGET_TEMPERATURE
from .themes import Theme, flagged_rate


def pooled(at: str, stated: dict, verdicts: list, langs: list[str]) -> list[Check]:
    """Rate, counts and the interval over hypotheses and languages of pooled answers."""
    s = share(verdicts)
    return [Check(f"{at}.rate", stated.get("rate"), round(s.rate, 3)),
            Check(f"{at}.k", stated.get("k"), s.k),
            Check(f"{at}.n", stated.get("n"), s.n),
            Check(f"{at}.ci95", stated.get("ci95"), list(pooled_interval(verdicts, langs)),
                  rounding(3))]


def rates(at: str, stated: dict, verdicts: list, langs: list[str]) -> list[Check]:
    return [Check(f"{at}.{lang}", stated.get(lang), round(s.rate, 3))
            for lang, s in by_lang(verdicts, langs).items()]


def variation(at: str, stated: dict, theme: Theme, hypothesis: str) -> list[Check]:
    verdicts = theme.run.of({hypothesis})
    s = share(verdicts)
    return [Check(f"{at}.rate", stated.get("rate"), round(s.rate, 3)),
            Check(f"{at}.ci95", stated.get("ci95"), rounded(s.wilson)),
            Check(f"{at}.k", stated.get("k"), s.k),
            Check(f"{at}.n", stated.get("n"), s.n),
            *rates(f"{at}.rates", stated.get("rates", {}), verdicts, theme.run.langs)]


def control(at: str, p: dict, theme: Theme) -> list[Check]:
    stated = p.get("harness_control")
    if not theme.premise or stated is None:
        return [Check(f"{at}.harness_control present", stated is not None, bool(theme.premise))]
    langs = theme.run.langs
    difference = paired_difference(theme.verdicts, theme.neutral, langs)
    return [Check(f"{at}.harness_control.run_id", stated.get("run_id"), theme.run.id),
            *pooled(f"{at}.harness_control.premise", stated.get("premise", {}), theme.premise,
                    langs),
            *pooled(f"{at}.harness_control.neutral", stated.get("neutral", {}), theme.neutral,
                    langs),
            Check(f"{at}.harness_control.premise_minus_neutral_ci95",
                  stated.get("premise_minus_neutral_ci95"), list(difference), rounding(3))]


def replication(at: str, p: dict, theme: Theme) -> list[Check]:
    r, stated = theme.replica, p.get("harness_replication")
    if r is None or stated is None:
        return [Check(f"{at}.harness_replication present", stated is not None, r is not None)]
    at = f"{at}.harness_replication"
    checks = [Check(f"{at}.model", stated.get("model"), r.run.model),
              Check(f"{at}.run_id", stated.get("run_id"), r.run.id),
              Check(f"{at}.variations_reproduced", stated.get("variations_reproduced"),
                    r.reproduced),
              Check(f"{at}.variations_measured", stated.get("variations_measured"), r.measured),
              Check(f"{at}.variations_failed", stated.get("variations_failed"), r.failed)]
    if r.verdicts:
        return checks + pooled(at, stated, r.verdicts, r.run.langs)
    return checks + [Check(f"{at}.n", stated.get("n"), 0)]


def parameter_checks(name: str, finding: dict, theme: Theme) -> list[Check]:
    p = finding["model"]["parameters"]
    at = f"findings/{name}.json model.parameters"
    run, verdicts = theme.run, theme.verdicts
    stated_variations = {v["id"]: v for v in p.get("harness_variations", [])}
    checks = [
        Check(f"{at}.temperature", p.get("temperature"), TARGET_TEMPERATURE, constant=True),
        Check(f"{at}.max_output_tokens", p.get("max_output_tokens"), TARGET_MAX_TOKENS,
              constant=True),
        Check(f"{at}.harness_run_id", p.get("harness_run_id"), run.id),
        Check(f"{at}.harness_system_prompt", p.get("harness_system_prompt"), run.system),
        Check(f"{at}.harness_langs", p.get("harness_langs"), run.langs),
        Check(f"{at}.harness_seeds", p.get("harness_seeds"), run.seeds),
        *rates(f"{at}.harness_reproduction_rates", p.get("harness_reproduction_rates", {}),
               verdicts, run.langs),
        Check(f"{at}.harness_overall_rate", p.get("harness_overall_rate"),
              round(share(verdicts).rate, 3)),
        Check(f"{at}.harness_overall_ci95", p.get("harness_overall_ci95"),
              list(pooled_interval(verdicts, run.langs)), rounding(3)),
        Check(f"{at}.harness_flagged_rate", p.get("harness_flagged_rate"),
              round(flagged_rate(verdicts), 3)),
        Check(f"{at}.harness_variations ids", list(stated_variations), theme.ids),
    ]
    for h in theme.ids:
        checks += variation(f"{at}.harness_variations[{h}]", stated_variations.get(h, {}), theme, h)
    return checks + control(at, p, theme) + replication(at, p, theme)
