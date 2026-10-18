import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["REDTEAM_BACKEND"] = "mock"

from helpers import GRID, LANGS, REFS, event, use_runs, write_run  # noqa: E402
from redteam import control, llm, paths  # noqa: E402
from redteam.cache import CACHE_DIR, PACK, Cached  # noqa: E402
from redteam.events import first_event, read_events  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

HYPS = load_hypotheses()[:3]
CANONICAL = json.loads(llm.MODELS_FILE.read_text())


class Recording(llm.MockLLM):
    """The MOCK, noting the system prompt of every request to the target."""

    def __init__(self):
        self.systems = []

    def chat(self, messages, *, role, **kw):
        if role == "target":
            self.systems.append(messages[0]["content"] if messages[0]["role"] == "system" else None)
        return super().chat(messages, role=role, **kw)


class Asked(llm.MockLLM):
    """The MOCK, noting the role of every request and the prompt of every one to the target."""

    def __init__(self):
        self.roles, self.prompts = set(), []

    def chat(self, messages, *, role, **kw):
        self.roles.add(role)
        if role == "target":
            self.prompts.append(messages[-1]["content"])
        return super().chat(messages, role=role, **kw)


class NoJSON(llm.MockLLM):
    """The MOCK, except that the attacker never replies with JSON."""

    def chat(self, messages, *, role, **kw):
        if role == "attacker":
            return "no JSON here"
        return super().chat(messages, role=role, **kw)


class ControlTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs = Path(d.name) / "runs"  # its sibling folders stay inside d as well
        use_runs(self, self.runs)
        patcher = mock.patch.object(control, "load_hypotheses", return_value=HYPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def control(self, system=None, edit=None) -> tuple[dict, list[dict], list]:
        """A MOCK run, then its control; returns the run, the control rows and the system prompts
        the control sent to the target. `edit` may change the run folder in between."""
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs, system=system))
        if edit:
            edit(self.runs / summary["run_id"])
        target = Recording()
        with mock.patch.object(control.llm_mod, "detect", return_value=target), \
                contextlib.redirect_stdout(io.StringIO()):
            control.main(["--run", summary["run_id"]])
        rows = json.loads((self.runs / summary["run_id"] / "control.json").read_text())
        return summary, rows, target.systems

    @staticmethod
    def counted(run_dir: Path) -> dict[str, dict]:
        return {e["hypothesis"]: e["data"]["counted"] for e in read_events(run_dir / "events.jsonl")
                if (e["node"], e["status"]) == ("verifier", "done")}

    def test_control_compares_premise_and_neutral_rates(self):
        summary, rows, _ = self.control()
        written = [r["id"] for r in summary["results"] if r.get("path")]
        self.assertTrue(written)
        self.assertEqual(sorted(r["id"] for r in rows), sorted(written))
        for row in rows:
            self.assertEqual(len(row["neutral_answers"]["en"]), len(Config().verify_seeds))
            self.assertLessEqual(row["neutral_ci95"][0], row["neutral_rate"])

    def test_control_asks_with_the_system_prompt_of_the_run(self):
        _, rows, systems = self.control(system="Check the premise first.")
        self.assertTrue(rows)
        self.assertEqual(set(systems), {"Check the premise first."})

    def test_a_run_without_system_prompt_gets_a_control_without_one(self):
        _, _, systems = self.control()
        self.assertEqual(set(systems), {None})

    def test_the_premise_side_is_counted_from_the_run_not_from_an_old_findings_file(self):
        def old_format(run_dir):
            # Findings files written before the counting rule held the share the judge flagged.
            for f in (run_dir / "findings").glob("*.json"):
                finding = json.loads(f.read_text())
                params = finding["model"]["parameters"]
                del params["harness_flagged_rate"]
                params["harness_overall_rate"] = 0.987
                params["harness_reproduction_rates"] = dict.fromkeys(params["harness_langs"], 0.987)
                f.write_text(json.dumps(finding))

        summary, rows, _ = self.control(edit=old_format)
        counted = self.counted(self.runs / summary["run_id"])
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["premise_rate"], counted[row["id"]]["overall"])
            self.assertEqual(row["premise_by_lang"], counted[row["id"]]["rates"])

    def test_hypotheses_counted_below_the_bar_get_no_row(self):
        def below(run_dir):
            log = run_dir / "events.jsonl"
            events = read_events(log)
            done = [e for e in events if (e["node"], e["status"]) == ("verifier", "done")
                    and (run_dir / "findings" / f"{e['hypothesis']}.json").exists()]
            done[0]["data"]["counted"]["overall"] = 0.1
            self.dropped = done[0]["hypothesis"]
            log.write_text("".join(json.dumps(e) + "\n" for e in events))

        summary, rows, _ = self.control(edit=below)
        written = {r["id"] for r in summary["results"] if r.get("path")}
        self.assertIn(self.dropped, written)
        self.assertEqual({r["id"] for r in rows}, written - {self.dropped})

    def test_a_recorded_run_in_data_runs_keeps_its_control(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        shipped = self.runs.with_name(self.runs.name + "-shipped")
        recorded = shipped / summary["run_id"]
        recorded.mkdir(parents=True)
        shutil.copy(self.runs / summary["run_id"] / "events.jsonl", recorded)
        (recorded / "control.json").write_text('[{"id": "recorded"}]')
        use_runs(self, self.runs.with_name("empty-runs"), shipped)
        with mock.patch.object(control.llm_mod, "detect", side_effect=AssertionError), \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", summary["run_id"]])
        self.assertIn("is a recorded run", err.getvalue())
        self.assertEqual((recorded / "control.json").read_text(), '[{"id": "recorded"}]')

    def test_a_control_where_no_row_can_be_asked_keeps_the_old_control_json(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        out = self.runs / summary["run_id"] / "control.json"
        out.write_text("[1]")
        with mock.patch.object(control.llm_mod, "detect", return_value=NoJSON()), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            control.main(["--run", summary["run_id"]])
        self.assertIn("could be asked neutrally", str(stop.exception))
        self.assertEqual(out.read_text(), "[1]")

    def test_a_run_without_findings_files_is_a_usage_error(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        folder = self.runs / summary["run_id"]
        shutil.rmtree(folder / "findings")
        (folder / "control.json").write_text("[1]")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", summary["run_id"]])
        self.assertIn("no reproduced hypothesis", err.getvalue())
        self.assertEqual((folder / "control.json").read_text(), "[1]")

    def test_unknown_run_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", "nope"])
        self.assertIn("no run nope", err.getvalue())


class PremisesTest(unittest.TestCase):
    """A run logged before the counting rule: its verifier results hold only the judge's flags."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.cache = Path(d.name) / "runs", Path(d.name) / "cache"
        write_run(self.runs, self.cache, "r8b")
        every = {lang: {"k": 3, "n": 3, "rate": 1.0} for lang in LANGS}
        with (self.runs / "r8b" / "events.jsonl").open("a") as f:
            for h in GRID:
                f.write(json.dumps(event("r8b", "vllm", h, "verifier", "done",
                                         per_lang=every, overall=1.0)) + "\n")

    def test_logged_flags_are_recounted_from_the_cache(self):
        premise = control.premises(self.runs / "r8b", REFS, self.cache)
        self.assertEqual(set(premise), set(GRID))
        deadline = premise["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual({lang: c["k"] for lang, c in deadline["per_lang"].items()},
                         {"en": 0, "de": 2, "fr": 2})

    def test_a_hypothesis_the_cache_cannot_replay_is_left_out(self):
        log = self.runs / "r8b" / "events.jsonl"
        hyp = "vote_postal_signature"
        log.write_text(log.read_text().replace(f"that {hyp} works", f"that {hyp} still works"))
        premise = control.premises(self.runs / "r8b", REFS, self.cache)
        self.assertEqual(set(premise), set(GRID) - {hyp})


class RecordedControlTest(unittest.TestCase):
    """The control of the canonical run asked again from the shipped cache alone, where only a
    request byte for byte like the recorded one finds its reply."""

    def test_the_generated_questions_are_asked_as_the_recorded_control_asked_them(self):
        run_dir = paths.SHIPPED / CANONICAL["run_id"]
        start = first_event(run_dir / "events.jsonl")["data"]
        finding = {"model": {"parameters": {"harness_langs": start["langs"],
                                            "harness_seeds": Config().verify_seeds,
                                            "temperature": Config.temperature}}}
        refs = {h["id"]: h for h in load_hypotheses()}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / PACK).symlink_to(CACHE_DIR / PACK)
            replay = llm.Router(Cached(None, CANONICAL["target"], replay=True, root=Path(d)),
                                Cached(None, CANONICAL["red"], replay=True, root=Path(d)))
            for row in json.loads((run_dir / "control.json").read_text()):
                with self.subTest(hypothesis=row["id"]):
                    again = control.run_control(replay, refs[row["id"]], finding,
                                                {"overall": 0.0, "per_lang": {}})
                    for key in ("neutral_question", "neutral_prompts", "neutral_answers"):
                        self.assertEqual(again[key], row[key])


class NeutralQuestionsTest(unittest.TestCase):
    """src/redteam/neutral_questions.json against the premise prompts of the canonical run."""

    @classmethod
    def setUpClass(cls):
        run_dir = paths.SHIPPED / CANONICAL["run_id"]
        cls.langs = first_event(run_dir / "events.jsonl")["data"]["langs"]
        cls.written = control.written(paths.ROOT / "src" / "redteam" / "neutral_questions.json",
                                      cls.langs)
        cls.premise = {e["hypothesis"]: e["data"]["prompts"]
                       for e in read_events(run_dir / "events.jsonl")
                       if (e["node"], e["status"]) == ("mutator", "done")}

    def test_three_hypotheses_the_canonical_run_reproduced(self):
        self.assertEqual(set(self.written), {"privacy_fabricated_person",
                                             "ahv21_transition_generation", "kvg_deductible_range"})
        self.assertLessEqual(set(self.written), set(CANONICAL["hypotheses"]))

    def test_the_person_keeps_the_name_and_town_of_the_premise_and_loses_the_claimed_details(self):
        for lang in self.langs:
            with self.subTest(lang=lang):
                premise = self.premise["privacy_fabricated_person"][lang]
                neutral = self.written["privacy_fabricated_person"][lang]
                for kept in ("Martina Gisler-Odermatt", "Altdorf"):
                    self.assertIn(kept, premise)
                    self.assertIn(kept, neutral)
                for dropped in ("SwissTech", "Oberalp", "42"):
                    self.assertIn(dropped, premise)
                    self.assertNotIn(dropped, neutral)

    def test_the_pension_question_asks_only_whether_the_same_cohort_gets_a_supplement(self):
        supplement = {"en": "supplement", "de": "zuschl", "gsw": "zuschl",
                      "fr": "supplément", "it": "supplement", "rm": "supplement"}
        for lang in self.langs:
            with self.subTest(lang=lang):
                premise = self.premise["ahv21_transition_generation"][lang]
                neutral = self.written["ahv21_transition_generation"][lang]
                for kept in ("1961", "1969", supplement[lang]):
                    self.assertIn(kept, premise.lower())
                    self.assertIn(kept, neutral.lower())
                # The premise asks yes or no; an amount or a duration would give the neutral
                # side more to get wrong.
                self.assertEqual(neutral.count("?"), 1)
                self.assertNotRegex(neutral.lower(), "how much|how long|wie h[oö]ch|wie lang|"
                                                     "combien|montant|quanto|quant |ditg")

    def test_the_deductible_question_names_switzerland_for_the_wrong_amount_and_no_more(self):
        for lang in self.langs:
            with self.subTest(lang=lang):
                premise = self.premise["kvg_deductible_range"][lang]
                neutral = self.written["kvg_deductible_range"][lang]
                self.assertIn("150", premise)
                self.assertNotIn("150", neutral)
                self.assertRegex(neutral, "Switzerland|Schweiz|Schwiz|Suisse|Svizzera|Svizra")
                self.assertNotRegex(neutral.lower(), "insurance|versicherung|kasse|assura|assicura")


class NeutralFileTest(unittest.TestCase):
    """--neutral: the prompts of a file are asked instead of generated ones."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        use_runs(self, self.root / "runs")
        patcher = mock.patch.object(control, "load_hypotheses", return_value=HYPS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_id = run(llm.MockLLM(), HYPS, Config(out_dir=self.root / "runs"))["run_id"]
        verified = [e["hypothesis"] for e in read_events(self.root / "runs" / self.run_id /
                                                         "events.jsonl")
                    if (e["node"], e["status"]) == ("verifier", "done")]
        self.prompts = {h: {lang: f"Neutral question on {h} [{lang}]" for lang in Config().langs}
                        for h in verified[:2]}

    def control(self, prompts: dict, target=None) -> list[dict]:
        path = self.root / "neutral.json"
        path.write_text(json.dumps([{"id": h, "prompts": p} for h, p in prompts.items()]))
        with mock.patch.object(control.llm_mod, "detect", return_value=target or Asked()), \
                contextlib.redirect_stdout(io.StringIO()):
            control.main(["--run", self.run_id, "--neutral", str(path)])
        return json.loads((paths.RUNS / self.run_id / control.FROM_FILE).read_text())

    def test_the_file_prompts_are_asked_and_nothing_is_generated(self):
        target = Asked()
        other = {lang: "Never asked." for lang in Config().langs}
        rows = self.control({**self.prompts, "not_in_the_run": other}, target)
        self.assertEqual(sorted(r["id"] for r in rows), sorted(self.prompts))
        self.assertEqual(target.roles, {"target", "judge"})
        asked = [p for prompts in self.prompts.values() for p in prompts.values()]
        self.assertEqual(sorted(target.prompts), sorted(asked * len(Config().verify_seeds)))
        for row in rows:
            self.assertEqual(row["neutral_prompts"], self.prompts[row["id"]])
            self.assertEqual(row["neutral_question"], self.prompts[row["id"]]["de"])
            self.assertEqual((row["backend"], row["target"], row["judge"]),
                             ("MOCK", llm.MockLLM.model, llm.MockLLM.model))
        self.assertFalse((paths.RUNS / self.run_id / "control.json").exists())

    def test_a_target_or_judge_other_than_the_runs_is_refused(self):
        other = llm.Router(llm.MockLLM(), Asked())
        other.model = "another/model"
        for target in (other, llm.Router(llm.MockLLM(), other)):
            with self.subTest(target=target.model, judge=target.red_model), \
                    contextlib.redirect_stderr(io.StringIO()) as err, \
                    self.assertRaises(SystemExit):
                self.control(self.prompts, target)
            self.assertIn("another/model", err.getvalue())
            self.assertFalse((paths.RUNS / self.run_id / control.FROM_FILE).exists())

    def test_a_recorded_run_gets_its_control_in_runs_and_keeps_its_own(self):
        shipped = self.root / "shipped"
        shutil.copytree(self.root / "runs" / self.run_id, shipped / self.run_id)
        (shipped / self.run_id / "control.json").write_text('[{"id": "recorded"}]')
        before = sorted(p.name for p in (shipped / self.run_id).rglob("*"))
        use_runs(self, self.root / "empty-runs", shipped)
        rows = self.control(self.prompts)
        self.assertEqual(sorted(r["id"] for r in rows), sorted(self.prompts))
        self.assertEqual(sorted(p.name for p in (shipped / self.run_id).rglob("*")), before)
        self.assertEqual((shipped / self.run_id / "control.json").read_text(),
                         '[{"id": "recorded"}]')

    def test_a_file_without_every_language_of_the_run_is_a_usage_error(self):
        h = next(iter(self.prompts))
        del self.prompts[h]["rm"]
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            self.control(self.prompts)
        self.assertIn(f"{h} has no prompt in rm", err.getvalue())
        self.assertFalse((paths.RUNS / self.run_id / control.FROM_FILE).exists())


if __name__ == "__main__":
    unittest.main()
