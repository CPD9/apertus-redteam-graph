"""The dashboard's view of a run: events, findings, control and second judge, counted from the
LLM cache like the findings (redteam.dashboard), and what a new run would use (redteam.next_run)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import (GRID, HYP, LANGS, RUN, START, event, patch, use_runs,  # noqa: E402
                     write_control, write_json, write_run)
from redteam import answers, dashboard, next_run  # noqa: E402
from redteam.shares import Share  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs = Path(d.name)
        use_runs(self, self.runs)
        self.load = mock.Mock(return_value=[HYP])
        patch(self, mock.patch.object(dashboard, "CACHE_DIR", self.runs / "cache"),
              mock.patch.dict(dashboard._memo, clear=True),
              mock.patch.object(dashboard.run_mod, "load_hypotheses", self.load),
              mock.patch.object(next_run.llm, "probe", return_value=None))

    def make_run(self, run_id: str, events: str) -> Path:
        run = self.runs / run_id
        run.mkdir()
        (run / "events.jsonl").write_text(events)
        return run

    def test_latest_run_carries_control_rejudge_and_hypotheses(self):
        # The second line is cut off mid-write, as when a live run is read.
        run = self.make_run(RUN, json.dumps(START) + '\n{"node": "verif')
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": HYP["id"]}})
        write_json(run / "control.json", [{"id": HYP["id"], "neutral_rate": 0.5}])
        write_json(run / "rejudge.json", {"n": 2, "kappa": 1.0, "raw_agreement": 1.0, "cells": [{}, {}]})
        (self.runs / "latest").write_text(RUN + "\n")

        s = dashboard.state("latest")
        self.assertEqual(s["run_id"], RUN)
        self.assertEqual(len(s["events"]), 1)
        self.assertEqual(len(s["findings"]), 1)
        self.assertEqual(s["control"], [{"id": HYP["id"], "neutral_rate": 0.5}])
        self.assertEqual(s["rejudge"], {"n": 2, "kappa": 1.0, "raw_agreement": 1.0})
        self.assertEqual(s["hypotheses"], {HYP["id"]: {"title": "Initiative signatures",
                                                       "domain": "voting", "hypothesis": "h",
                                                       "reference": HYP["reference"], "harm": "x",
                                                       "sources": []}})

    def test_findings_are_named_by_their_file_whatever_their_title(self):
        run = self.make_run(RUN, json.dumps(START) + "\n")
        title = "Apertus confirms a wrong signature count"
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": title}})
        finding, = dashboard.state(RUN)["findings"]
        self.assertEqual((finding["hypothesis"], finding["issue_summary"]["title"]), (HYP["id"], title))

    def test_findings_below_the_bar_are_left_out_whatever_their_title(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.0, "de": 0.5}, "overall": 0.25}}
        run = self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": "a sentence"}})
        self.assertEqual(dashboard.state(RUN)["findings"], [])

    def test_shipped_copies_list_written_up_hypotheses_without_their_files(self):
        shipped = self.runs / "data-runs"
        use_runs(self, self.runs, shipped)
        kept, dropped = HYP["id"], "vote_postal_deadline"
        events = [START] + [
            {"node": "verifier", "status": "done", "hypothesis": h, "data": {"overall": rate}}
            for h, rate in ((kept, 0.5), (dropped, 0.2))] + [
            {"node": "scribe", "status": "done", "hypothesis": h, "data": {}} for h in (kept, dropped)]
        (shipped / RUN).mkdir(parents=True)
        (shipped / RUN / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        self.assertEqual(dashboard.state(RUN)["findings"], [{"hypothesis": kept}])

    def test_runs_that_log_their_counted_results_are_not_replayed(self):
        flagged = {"per_lang": {"en": {"k": 2, "n": 2, "rate": 1.0, "ci95": [0.34, 1.0]}},
                   "rates": {"en": 1.0}, "overall": 1.0, "overall_ci95": [0.34, 1.0]}
        counted = {"per_lang": {"en": {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.09, 0.91]}},
                   "rates": {"en": 0.5}, "overall": 0.5, "overall_ci95": [0.09, 0.91]}
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {**flagged, "counted": counted}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        with mock.patch.object(dashboard.answers, "load_run") as load_run:
            s = dashboard.state(RUN)
        self.assertFalse(load_run.called)
        self.assertEqual({k: s["events"][1]["data"][k] for k in counted}, counted)
        self.assertEqual(s["uncounted"], [])

    def test_state_names_the_bar_and_the_folder_of_the_run(self):
        self.make_run(RUN, json.dumps(START) + "\n")
        with mock.patch.object(dashboard.paths, "ROOT", self.runs.parent):
            s = dashboard.state(RUN)
        self.assertEqual(s["min_rate"], dashboard.Config.min_rate)
        self.assertEqual(s["run_folder"], f"{self.runs.name}/{RUN}")
        nothing = dashboard.state("nope")
        self.assertEqual((nothing["run_folder"], nothing["min_rate"], nothing["language_means"]),
                         (None, dashboard.Config.min_rate, {}))
        self.assertEqual(set(nothing) - {"running"}, set(s))

    def test_submitted_findings_are_trimmed_to_what_the_page_shows(self):
        findings = self.runs / "submitted"
        params = {"harness_run_id": RUN, "harness_variations": [{"id": HYP["id"], "k": 3, "n": 18}],
                  "harness_overall_rate": 0.5, "harness_overall_ci95": [0.3, 0.7],
                  "harness_control": {"neutral": {"k": 1, "n": 18}},
                  "harness_replication": {"run_id": "r2"}, "temperature": 0.7}
        write_json(findings / "civic.json", {
            "issue_title": "Confirms wrong rules", "steps_to_reproduce": ["make run"],
            "model": {"name": "swiss-ai/Apertus-v1.5-8B", "version": "abc", "parameters": params},
            "issue_summary": {"self_assessed_severity": 2, "self_assessed_breadth": 5,
                              "overview": "o", "observed_behavior": "left out"}})
        write_json(findings / "speech.json", {
            "issue_title": "Dialect", "model": {"name": "m70", "parameters": {
                "harness_run_id": "20261017-141121", "unrelated": {"ag": {"apertus": {"k": 41}}}}}})
        (findings / "broken.json").write_text("{")
        (findings / "findings.schema").write_text("{}")
        self.make_run(RUN, json.dumps(START) + "\n")
        with mock.patch.object(dashboard, "FINDINGS", findings):
            civic, speech = dashboard.state(RUN)["submitted"]
        self.assertEqual(civic, {
            "file": "civic.json", "issue_title": "Confirms wrong rules",
            "model": "swiss-ai/Apertus-v1.5-8B", "model_version": "abc", "run_id": RUN,
            "severity": 2, "breadth": 5, "overview": "o",
            "variations": params["harness_variations"], "overall_rate": 0.5,
            "overall_ci95": [0.3, 0.7], "control": params["harness_control"],
            "replication": {"run_id": "r2"}, "reproduce": ["make run"], "unrelated": None})
        self.assertEqual((speech["file"], speech["run_id"], speech["unrelated"]),
                         ("speech.json", "20261017-141121", {"ag": {"apertus": {"k": 41}}}))

    def test_submitted_findings_are_read_again_only_when_a_file_changes(self):
        findings = self.runs / "submitted"
        write_json(findings / "a.json", {"issue_title": "first"})
        self.make_run(RUN, json.dumps(START) + "\n")
        with mock.patch.object(dashboard, "FINDINGS", findings), \
                mock.patch.object(dashboard, "_json_file", wraps=dashboard._json_file) as read:
            for _ in range(3):
                dashboard.state(RUN)
            reads = [c for c in read.call_args_list if c.args[0].parent == findings]
            self.assertEqual(len(reads), 1)
            write_json(findings / "a.json", {"issue_title": "second"})
            os.utime(findings / "a.json", ns=(1, 1))
            self.assertEqual(dashboard.state(RUN)["submitted"][0]["issue_title"], "second")

    def test_state_counts_the_judge_verdicts_a_person_checked(self):
        labels = self.runs / "labels.jsonl"
        rows = [{"id": "a", "judge_violation": True, "human_violation": False},
                {"id": "b", "judge_violation": False, "human_violation": False},
                {"id": "seed:1", "judge_violation": None, "human_violation": True}]
        labels.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.make_run(RUN, json.dumps(START) + "\n")
        with mock.patch.object(dashboard.review, "LABELS", labels):
            self.assertEqual(dashboard.state(RUN)["human_labels"], 2)
            self.assertEqual(dashboard.state("nope")["human_labels"], 2)

    def test_runs_that_log_their_counted_results_keep_the_flags_of_per_lang(self):
        flagged = {"per_lang": {"en": {"k": 2, "n": 2, "rate": 1.0, "ci95": [0.34, 1.0]}},
                   "overall": 1.0}
        counted = {"per_lang": {"en": {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.09, 0.91]}},
                   "overall": 0.5}
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {**flagged, "counted": counted}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        for _ in range(2):  # the second answer comes from the memo
            data = dashboard.state(RUN)["events"][1]["data"]
            self.assertEqual((data["flagged"], data["per_lang"]["en"]["k"]), ({"en": 2}, 1))

    def test_results_that_logged_only_rates_have_no_flags_or_language_means(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5}, "overall": 0.5}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        s = dashboard.state(RUN)
        self.assertNotIn("flagged", s["events"][1]["data"])
        self.assertEqual(s["language_means"], {})

    def test_run_without_control_or_rejudge(self):
        self.make_run(RUN, json.dumps(START) + "\n")
        s = dashboard.state(RUN)
        self.assertEqual((s["control"], s["rejudge"], s["findings"], s["uncounted"]), ([], None, [], []))

    def test_runs_that_logged_only_rates_keep_them_and_are_marked_uncounted(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5, "de": 1.0}, "overall": 0.75}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        s = dashboard.state(RUN)
        self.assertEqual(s["events"][1]["data"], done["data"])
        self.assertEqual(s["uncounted"], [HYP["id"]])

    def test_unknown_or_unsafe_run_ids_resolve_to_nothing(self):
        self.make_run(RUN, "")
        for run_id in ("latest", "nope", "..", "../" + RUN, ""):
            s = dashboard.state(run_id)
            self.assertIsNone(s["run_id"], run_id)
            self.assertEqual((s["events"], s["uncounted"]), ([], []))

    def test_banks_are_read_again_only_when_a_bank_file_changes(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5}, "overall": 0.5}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        banks = self.runs / "hypotheses"
        write_json(banks / "bank.json", [HYP])
        with mock.patch.object(dashboard.run_mod, "HYPOTHESES", banks):
            for _ in range(3):
                dashboard.state(RUN)
            self.assertEqual(self.load.call_count, 1)
            os.utime(banks / "bank.json", ns=(0, 0))
            dashboard.state(RUN)
        self.assertEqual(self.load.call_count, 2)

    def test_runs_are_newest_first_with_labels(self):
        self.make_run("20261016-100000-aaaa", json.dumps({**START, "data": {}}) + "\n")
        self.make_run("20261017-100000-bbbb", json.dumps(START) + "\n")
        self.make_run("_aborted_20261017-110000-cccc", json.dumps(START) + "\n")
        (self.runs / "speech").mkdir()
        rows = dashboard.runs()
        self.assertEqual([r["id"] for r in rows], ["20261017-100000-bbbb", "20261016-100000-aaaa"])
        self.assertEqual([r["label"] for r in rows], ["8B target", ""])
        self.assertEqual(rows[0]["model"], "swiss-ai/Apertus-v1.5-8B")
        self.assertEqual(rows[0]["written"], 0)


    def test_runs_carry_the_report_name_and_the_system_prompt(self):
        system = {**START, "data": {"label": "mitigation", "system": "Check the premise."}}
        self.make_run("20261017-144423-5519", json.dumps(system) + "\n")
        self.make_run("20261017-150000-dddd", json.dumps({**START, "data": {"system": ""}}) + "\n")
        rows = {r["id"]: r for r in dashboard.runs()}
        report, other = rows["20261017-144423-5519"], rows["20261017-150000-dddd"]
        self.assertEqual((report["name"], report["report"], report["system"]),
                         ("Apertus 70B with a safety system prompt", True, True))
        self.assertEqual((other["name"], other["report"], other["system"]), ("", False, False))
        self.assertEqual((report["latest"], other["latest"]), (False, False))
        (self.runs / "latest").write_text("20261017-150000-dddd\n")
        self.assertTrue({r["id"]: r for r in dashboard.runs()}["20261017-150000-dddd"]["latest"])
        # Only the report runs are counted before they are opened; the others cost a replay each.
        self.assertEqual((report["reproduced"], other["reproduced"]), (0, None))

    def test_only_the_newest_run_without_its_end_and_written_to_lately_is_live(self):
        going, ended = "20261017-150000-dddd", "20261017-140000-eeee"
        self.make_run(going, json.dumps(START) + "\n")
        end = {"node": "graph", "status": "end", "hypothesis": None, "data": {}}
        self.make_run(ended, json.dumps(START) + "\n" + json.dumps(end) + "\n")
        live = lambda: {r["id"]: r["live"] for r in dashboard.runs()}  # noqa: E731
        (self.runs / "latest").write_text(ended + "\n")
        self.assertEqual(live(), {going: False, ended: False})
        (self.runs / "latest").write_text(going + "\n")
        self.assertEqual(live(), {going: True, ended: False})
        os.utime(self.runs / going / "events.jsonl", (0, 0))  # killed long ago
        self.assertEqual(live(), {going: False, ended: False})

class RecountTest(unittest.TestCase):
    """A run and its control replayed from the LLM cache (tests/helpers.py)."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, cache = Path(d.name) / "runs", Path(d.name) / "cache"
        use_runs(self, self.runs)
        patch(self, mock.patch.object(dashboard, "CACHE_DIR", cache),
              mock.patch.dict(dashboard._memo, clear=True),
              mock.patch.object(next_run.llm, "probe", return_value=None))
        write_run(self.runs, cache, RUN)
        write_control(self.runs, cache, RUN)
        self.log_rates(self.runs / RUN)

    @staticmethod
    def log_rates(run: Path):
        """Logged numbers that the recount has to replace: every answer counted as a failure."""
        every = {lang: {"k": 3, "n": 3, "rate": 1.0, "ci95": [0.44, 1.0]} for lang in LANGS}
        with (run / "events.jsonl").open("a") as f:
            for h in GRID:
                done = event(RUN, "vllm", h, "verifier", "done", per_lang=every, overall=1.0,
                             overall_ci95=[0.82, 1.0])
                f.write(json.dumps(done) + "\n")
        rows = json.loads((run / "control.json").read_text())
        for row in rows:
            row.update(neutral_rate=1.0, neutral_ci95=[0.82, 1.0], premise_rate=1.0)
        (run / "control.json").write_text(json.dumps(rows))

    def verified(self, s: dict) -> dict:
        return {e["hypothesis"]: e["data"] for e in s["events"]
                if e["node"] == "verifier" and e["status"] == "done"}

    def test_verifier_results_count_confirmed_answers_with_their_intervals(self):
        s = dashboard.state(RUN)
        deadline = self.verified(s)["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual(deadline["per_lang"]["en"]["k"], 0)
        self.assertEqual(deadline["per_lang"]["en"]["ci95"], list(Share(0, 3).ci95))
        self.assertAlmostEqual(self.verified(s)["vote_postal_signature"]["overall"], 1 / 9)
        self.assertEqual(s["uncounted"], [])

    def test_findings_the_recount_puts_below_the_bar_are_left_out(self):
        # Both were written up on their flags; only the deadline (4 of 9) still counts at 1 of 9.
        for h in ("vote_postal_signature", "vote_postal_deadline"):
            write_json(self.runs / RUN / "findings" / f"{h}.json", {"issue_summary": {"title": h}})
        s = dashboard.state(RUN)
        self.assertEqual([f["hypothesis"] for f in s["findings"]],
                         ["bias_tenant_selection_origin", "hist_womens_suffrage_1971",
                          "vote_mandatory_referendum", "vote_postal_deadline"])
        self.assertEqual(s["findings"][-1]["issue_summary"]["title"], "vote_postal_deadline")
        self.assertEqual(self.verified(s)["vote_postal_signature"]["per_lang"]["de"]["k"], 1)

    def test_a_hypothesis_the_cache_cannot_replay_keeps_its_flags_and_is_listed(self):
        # Its logged prompts no longer match the calls in the cache; the others still do.
        log = self.runs / RUN / "events.jsonl"
        hyp = "vote_postal_signature"
        log.write_text(log.read_text().replace(f"that {hyp} works", f"that {hyp} still works"))
        s = dashboard.state(RUN)
        self.assertEqual(s["uncounted"], [hyp])
        self.assertEqual(self.verified(s)[hyp]["overall"], 1.0)
        self.assertAlmostEqual(self.verified(s)["vote_postal_deadline"]["overall"], 4 / 9)

    def test_the_run_is_recounted_once_per_verified_hypothesis(self):
        with mock.patch.object(dashboard.answers, "recount", wraps=answers.recount) as recount:
            first, second = dashboard.state(RUN), dashboard.state(RUN)
            with (self.runs / RUN / "events.jsonl").open("a") as f:
                f.write(json.dumps(event(RUN, "vllm", "x", "attacker", "start")) + "\n")
            dashboard.state(RUN)
        self.assertEqual(recount.call_count, 1)
        self.assertEqual(self.verified(first), self.verified(second))

    def test_control_counts_neutral_answers_alike_and_takes_the_premise_from_the_run(self):
        control = {row["id"]: row for row in dashboard.state(RUN)["control"]}
        referendum = control["vote_mandatory_referendum"]  # neutral: one wrong answer in fr
        self.assertAlmostEqual(referendum["neutral_rate"], 1 / 9)
        self.assertEqual(referendum["neutral_ci95"], list(Share(1, 9).ci95))
        self.assertEqual(referendum["premise_rate"], 1.0)
        self.assertEqual(control["vote_postal_deadline"]["neutral_rate"], 0.0)
        self.assertAlmostEqual(control["vote_postal_deadline"]["premise_rate"], 4 / 9)

    def test_the_flags_before_the_recount_survive_it_and_later_polls(self):
        for _ in range(2):  # the second answer comes from the memo
            deadline = self.verified(dashboard.state(RUN))["vote_postal_deadline"]
            self.assertEqual(deadline["flagged"], {"en": 3, "de": 3, "fr": 3})
            self.assertEqual({lang: c["k"] for lang, c in deadline["per_lang"].items()},
                             {"en": 0, "de": 2, "fr": 2})

    def test_language_means_average_the_hypotheses_and_add_up_the_answers(self):
        means = dashboard.state(RUN)["language_means"]
        self.assertEqual(set(means), set(LANGS))
        en = means["en"]  # w: 3 + 0 + 0 + 3 + 3 of 15
        self.assertEqual((en["k"], en["n"]), (9, 15))
        self.assertAlmostEqual(en["rate"], 9 / 15)
        self.assertLessEqual(en["ci95"][0], en["rate"])
        self.assertGreaterEqual(en["ci95"][1], en["rate"])

    def test_control_rows_carry_their_counts(self):
        control = {row["id"]: row for row in dashboard.state(RUN)["control"]}
        referendum = control["vote_mandatory_referendum"]
        self.assertEqual({k: referendum[k] for k in ("premise_k", "premise_n", "neutral_k", "neutral_n")},
                         {"premise_k": 9, "premise_n": 9, "neutral_k": 1, "neutral_n": 9})
        with mock.patch.object(dashboard, "CACHE_DIR", self.runs / "no-cache"), \
                mock.patch.dict(dashboard._memo, clear=True):
            row = dashboard.state(RUN)["control"][0]
        self.assertNotIn("neutral_k", row)

    def test_control_keeps_the_logged_rates_when_the_cache_cannot_replay_it(self):
        with mock.patch.object(dashboard, "CACHE_DIR", self.runs / "no-cache"):
            row = dashboard.state(RUN)["control"][0]
        self.assertEqual((row["neutral_rate"], row["neutral_ci95"], row["premise_rate"]),
                         (1.0, [0.82, 1.0], 1.0))

    def test_report_runs_carry_the_number_of_findings_the_recount_leaves(self):
        for h in ("vote_postal_signature", "vote_postal_deadline"):
            write_json(self.runs / RUN / "findings" / f"{h}.json", {"issue_summary": {"title": h}})
        row, = [r for r in dashboard.runs() if r["id"] == RUN]
        self.assertEqual(row["reproduced"], 4)  # vote_postal_signature falls below the bar
        self.assertEqual(row["reproduced"], len(dashboard.state(RUN)["findings"]))

    def test_control_is_replayed_once_per_control_file(self):
        with mock.patch.object(dashboard.answers, "neutral_answers",
                               wraps=answers.neutral_answers) as replay:
            first, second = dashboard.state(RUN)["control"], dashboard.state(RUN)["control"]
            os.utime(self.runs / RUN / "control.json", ns=(0, 0))
            dashboard.state(RUN)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(first, second)


class NextRunTest(unittest.TestCase):
    """What "Start a new run" would use, decided as llm.detect() decides it."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.models = Path(d.name) / "models.json"
        self.probe = mock.Mock(return_value=None)
        env = {"LLM_BASE_URL": "http://user:secret@127.0.0.1:8000/v1", "REDTEAM_BACKEND": "",
               "LLM_NAME": "", "RED_LLM_NAME": ""}
        patch(self, mock.patch.object(next_run.llm, "MODELS_FILE", self.models),
              mock.patch.object(next_run.llm, "probe", self.probe), mock.patch.dict(os.environ, env))
        next_run._decide.cache_clear()
        self.addCleanup(next_run._decide.cache_clear)

    def test_an_endpoint_that_answers_is_used_and_named_without_its_credentials(self):
        self.probe.return_value = "swiss-ai/Apertus-v1.5-8B"
        self.assertEqual(next_run.plan(), {"backend": "vllm", "forced": False, "endpoint": "127.0.0.1:8000",
                                           "replays": None, "replay_model": None})

    def test_without_an_endpoint_the_cached_run_is_replayed(self):
        write_json(self.models, {"target": "t", "red": "r", "run_id": RUN})
        plan = next_run.plan()
        self.assertEqual((plan["backend"], plan["replays"], plan["replay_model"]), ("replay", RUN, "t"))

    def test_llm_name_replays_another_models_cache_and_not_the_named_run(self):
        # llm._replay() takes LLM_NAME over models.json, as the local 70B replays were made.
        write_json(self.models, {"target": "t", "red": "r", "run_id": RUN})
        os.environ["LLM_NAME"] = "onprem-ai/Apertus-v1.5-70B-FP8"
        plan = next_run.plan()
        self.assertEqual((plan["replays"], plan["replay_model"]), (None, "onprem-ai/Apertus-v1.5-70B-FP8"))

    def test_another_red_model_no_longer_repeats_the_named_run(self):
        write_json(self.models, {"target": "t", "red": "r", "run_id": RUN})
        os.environ["RED_LLM_NAME"] = "other-judge"
        plan = next_run.plan()
        self.assertEqual((plan["replays"], plan["replay_model"]), (None, "t"))

    def test_llm_name_equal_to_the_named_target_still_repeats_the_run(self):
        write_json(self.models, {"target": "t", "red": "r", "run_id": RUN})
        os.environ["LLM_NAME"] = "t"
        self.assertEqual(next_run.plan()["replays"], RUN)

    def test_a_cache_written_before_runs_were_named_replays_an_unnamed_run(self):
        write_json(self.models, {"target": "t", "red": "r"})
        plan = next_run.plan()
        self.assertEqual((plan["backend"], plan["replays"]), ("replay", None))

    def test_without_an_endpoint_or_a_cache_the_answers_are_mock(self):
        self.assertEqual(next_run.plan()["backend"], "MOCK")

    def test_redteam_backend_forces_mock_without_asking_the_endpoint(self):
        os.environ["REDTEAM_BACKEND"] = "mock"
        plan = next_run.plan()
        self.assertEqual((plan["backend"], plan["forced"]), ("MOCK", True))
        self.assertFalse(self.probe.called)

    def test_the_endpoint_is_asked_once_per_window(self):
        with mock.patch.object(next_run.time, "time", return_value=0.0) as now:
            next_run.plan(), next_run.plan()
            now.return_value = float(next_run.KEEP_S)
            next_run.plan()
        self.assertEqual(self.probe.call_count, 2)

    def test_every_state_carries_the_plan(self):
        self.assertEqual(dashboard.state("nope")["next_run"], next_run.plan())


if __name__ == "__main__":
    unittest.main()
