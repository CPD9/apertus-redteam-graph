import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import speech_compare, speech_eval  # noqa: E402
from redteam.cache import CacheMiss  # noqa: E402
from redteam.speech_eval import chrf  # noqa: E402

GOLD = {1: "Der Zug fährt um acht Uhr ab.", 2: "Sie wohnt seit drei Jahren in Bern.",
        3: "Wir essen heute Abend Fondue.", 4: "Das Museum ist am Montag geschlossen."}


class Judge:
    """Answers the meaning prompt from the translation it is shown: "TIMEOUT" times out, "GARBLE"
    gets a reply with no JSON in it, "ODD" a verdict off the scale, anything else "same"."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, role, temperature=0.0, seed=None, max_tokens=700):
        self.calls += 1
        prompt = messages[0]["content"]
        if "TRANSLATION: TIMEOUT" in prompt:
            raise TimeoutError("timed out")
        if "TRANSLATION: GARBLE" in prompt:
            return "The meaning is mostly the same."
        if "TRANSLATION: ODD" in prompt:
            return json.dumps({"meaning": "maybe"})
        return json.dumps({"meaning": "same"})


class LiveJudge(Judge):
    backend = "vllm"


class ReplayJudge(Judge):
    """A cache replay: it has recorded no verdict for the translation "MISS"."""
    backend = "replay"

    def chat(self, messages, **kw):
        if "TRANSLATION: MISS" in messages[0]["content"]:
            raise CacheMiss("judge call not in cache (0123456789ab)")
        return super().chat(messages, **kw)


TARGET_URL = "http://target.test:8000/v1"
RED_URL = "http://red.test:8002/v1"


def clip(dialect, sentence_id, **fields):
    return {"dialect": dialect, "sentence_id": sentence_id, "gold": GOLD[sentence_id],
            "chrf": 50.0, "hallucinated": False, "output": "x", **fields}


class ChrfTest(unittest.TestCase):
    def test_identical_strings_score_100(self):
        text = "Derzeit ist er in Parasite zu sehen."
        self.assertAlmostEqual(chrf(text, text), 100.0)

    def test_unrelated_strings_score_low(self):
        self.assertLess(chrf("Der Hund bellt laut im Garten.", "Quarzuhr mit Kompass, 1987 gekauft."), 20)


class JudgeMeaningTest(unittest.TestCase):
    def test_verdict_on_the_scale_is_kept(self):
        self.assertEqual(speech_eval.judge_meaning(Judge(), "fine", GOLD[1]), {"meaning": "same"})

    def test_timeout_is_unknown_with_the_reason(self):
        out = speech_eval.judge_meaning(Judge(), "TIMEOUT", GOLD[1])
        self.assertEqual(out, {"meaning": "unknown", "meaning_error": "TimeoutError: timed out"})

    def test_unparseable_reply_is_unknown_after_the_repair_round(self):
        judge = Judge()
        out = speech_eval.judge_meaning(judge, "GARBLE", GOLD[1])
        self.assertEqual(out["meaning"], "unknown")
        self.assertTrue(out["meaning_error"].startswith("ValueError: "))
        self.assertEqual(judge.calls, 2)

    def test_verdict_off_the_scale_is_unknown(self):
        out = speech_eval.judge_meaning(Judge(), "ODD", GOLD[1])
        self.assertEqual(out, {"meaning": "unknown", "meaning_error": "verdict off the scale: 'maybe'"})


class EvaluateAllTest(unittest.TestCase):
    # None: the speech server's reply was not JSON.
    TRANSLATIONS = {"ch_zh_0001": "Der Zug fährt um acht Uhr ab.", "ch_zh_0002": "TIMEOUT",
                    "ch_be_0003": "GARBLE", "ch_be_0004": None}

    def translate(self, base_url, model, wav_bytes, instruction):
        text = self.TRANSLATIONS[wav_bytes.decode()]
        if text is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return text

    def evaluate(self):
        clips = [(name.split("_")[1], Path(f"{name}.wav")) for name in self.TRANSLATIONS]
        with mock.patch.object(speech_eval, "to_24k_mono", lambda wav, tmp: wav.stem.encode()), \
                mock.patch.object(speech_eval, "ask_with_audio", self.translate):
            return speech_eval.evaluate_all(clips, GOLD, Judge())

    def test_failures_cost_one_clip_each_and_the_pool_finishes(self):
        records = {(r["dialect"], r["sentence_id"]): r for r in self.evaluate()}
        self.assertEqual(len(records), 4)
        self.assertEqual(records["zh", 1]["meaning"], "same")
        self.assertEqual(records["zh", 2]["meaning"], "unknown")
        self.assertEqual(records["be", 3]["meaning"], "unknown")
        self.assertEqual(records["be", 4]["error"],
                         "ValueError: Expecting value: line 1 column 1 (char 0)")
        self.assertNotIn("meaning", records["be", 4])

    def test_summary_counts_unknown_apart_from_the_rates(self):
        rows = {row["dialect"]: row for row in speech_eval.summarize(self.evaluate())}
        self.assertEqual((rows["zh"]["n"], rows["zh"]["unknown"]), (2, 1))
        self.assertEqual((rows["zh"]["unrelated"], rows["zh"]["same_rate"]), (0, 1.0))
        # Bern: one clip failed to translate, the judge could not rate the other.
        self.assertEqual((rows["be"]["n"], rows["be"]["unknown"]), (1, 1))
        self.assertNotIn("unrelated_rate", rows["be"])


class SummarizeTest(unittest.TestCase):
    def test_rates_are_over_rated_clips_only(self):
        records = [clip("vs", 1, meaning="unrelated"), clip("vs", 2, meaning="same"),
                   clip("vs", 3, meaning="unknown"), clip("vs", 4, meaning="unknown")]
        row = speech_eval.summarize(records)[0]
        self.assertEqual((row["n"], row["unknown"], row["unrelated"]), (4, 2, 1))
        self.assertEqual(row["unrelated_rate"], 0.5)

    def test_unjudged_run_has_no_meaning_columns(self):
        row = speech_eval.summarize([clip("vs", 1)])[0]
        self.assertNotIn("unknown", row)
        self.assertNotIn("unrelated_rate", row)

    def test_table_prints_unknown_in_its_own_column(self):
        records = [clip("vs", 1, meaning="unrelated"), clip("vs", 2, meaning="unknown"),
                   clip("zh", 3, meaning="unknown")]
        printed = io.StringIO()
        with redirect_stdout(printed):
            speech_eval.print_table(speech_eval.summarize(records))
        header, vs, zh = printed.getvalue().splitlines()
        self.assertTrue(header.endswith("unknown"))
        self.assertRegex(vs, r"100%   \[21%, 100%\]\s+1$")
        self.assertRegex(zh, r"-\s+-\s+1$")  # no verdict, so no share under "unrelated"


class ScoreWhisperTest(unittest.TestCase):
    def test_judge_failures_leave_every_clip_scored(self):
        failed = {"dialect": "be", "sentence_id": 4, "gold": GOLD[4], "error": "x"}
        apertus = [clip("zh", 1), clip("zh", 2), clip("be", 3), failed]
        transcripts = {"ch_zh_0001": "Der Zug fährt um acht ab.", "ch_zh_0002": "TIMEOUT",
                       "ch_be_0003": "GARBLE", "ch_be_0004": "Das Museum ist zu."}
        records = speech_compare.score_whisper(apertus, transcripts, Judge())
        self.assertEqual([r["meaning"] for r in records], ["same", "unknown", "unknown"])
        self.assertEqual(records[1]["meaning_error"], "TimeoutError: timed out")


class CompareRunTest(unittest.TestCase):
    """speech_compare end to end: the judge rates the Zurich clip and times out on the Bern one."""

    TRANSCRIPTS = {"ch_zh_0001": "Der Zug fährt um acht ab.", "ch_be_0002": "TIMEOUT"}

    def run_compare(self, folder, transcripts=TRANSCRIPTS, detect=Judge):
        rated = [clip("zh", 1, meaning="unrelated"), clip("be", 2, meaning="same")]
        apertus = {"model": "apertus", "clips": rated, "dialects": speech_eval.summarize(rated)}
        whisper = {"model": "whisper", "transcripts": transcripts}
        (folder / "results.json").write_text(json.dumps(apertus))
        (folder / "whisper.json").write_text(json.dumps(whisper))
        printed = io.StringIO()
        with mock.patch.object(speech_compare.llm_mod, "detect", detect), redirect_stdout(printed):
            speech_compare.main([str(folder / "results.json"), str(folder / "whisper.json")])
        compare = json.loads((folder / "whisper_compare.json").read_text())
        return printed.getvalue().splitlines(), compare

    def test_partial_outage_prints_a_dash_and_the_unknown_count_not_zero_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, compare = self.run_compare(Path(tmp))
        rows = {line.split()[0]: line.split() for line in lines[1:3]}
        self.assertEqual(rows["be"][:3], ["be", "0%", "-"])
        self.assertEqual(rows["zh"][:3], ["zh", "100%", "0%"])
        self.assertEqual(lines[3], "meaning unknown (left out of the rates): Apertus 0, Whisper 1")
        whisper = {row["dialect"]: row["whisper"] for row in compare["dialects"]}
        self.assertEqual((whisper["be"]["n"], whisper["be"]["unknown"]), (1, 1))
        self.assertNotIn("unrelated_rate", whisper["be"])

    def test_total_outage_stops_and_keeps_the_recorded_verdicts(self):
        everything_times_out = {"ch_zh_0001": "TIMEOUT", "ch_be_0002": "TIMEOUT"}
        reason = self.stops_and_keeps_the_recorded_file(everything_times_out)
        self.assertIn("the judge rated none of the 2 Whisper clips (TimeoutError: timed out)",
                      reason)

    def stops_and_keeps_the_recorded_file(self, transcripts, detect=Judge):
        with tempfile.TemporaryDirectory() as tmp:
            recorded = Path(tmp) / "whisper_compare.json"
            recorded.write_text('{"stale": true}')
            with self.assertRaises(SystemExit) as stop:
                self.run_compare(Path(tmp), transcripts, detect)
            self.assertEqual(recorded.read_text(), '{"stale": true}')
        return stop.exception.code

    def test_replay_stops_on_one_clip_missing_from_the_cache(self):
        one_changed = {"ch_zh_0001": "Der Zug fährt um acht ab.", "ch_be_0002": "MISS"}
        reason = self.stops_and_keeps_the_recorded_file(one_changed, ReplayJudge)
        self.assertIn("1 of 2 Whisper clips are not in the cache "
                      "(CacheMiss: judge call not in cache (0123456789ab))", reason)

    def test_replay_writes_an_unknown_the_recorded_run_also_had(self):
        # A recorded reply the judge could not parse replays as the same 'unknown', not a miss.
        garbled = {"ch_zh_0001": "Der Zug fährt um acht ab.", "ch_be_0002": "GARBLE"}
        with tempfile.TemporaryDirectory() as tmp:
            lines, compare = self.run_compare(Path(tmp), garbled, ReplayJudge)
        self.assertEqual(lines[3], "meaning unknown (left out of the rates): Apertus 0, Whisper 1")
        self.assertEqual(len(compare["whisper_clips"]), 2)

    def test_no_transcript_for_a_scored_clip_stops_and_keeps_the_recorded_verdicts(self):
        keyed_elsewhere = {"ch_xx_0009": "Der Zug fährt um acht ab."}
        reason = self.stops_and_keeps_the_recorded_file(keyed_elsewhere)
        self.assertIn("no Whisper transcript matches a scored clip", reason)

    def test_mock_judge_stops_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as stop:
                self.run_compare(Path(tmp), detect=speech_compare.llm_mod.MockLLM)
            self.assertFalse((Path(tmp) / "whisper_compare.json").exists())
        self.assertIn("a MOCK judge proves nothing", stop.exception.code)

    def run_live(self, folder, answering):
        judge = LiveJudge()
        env = {"LLM_BASE_URL": TARGET_URL, "RED_LLM_BASE_URL": RED_URL}

        def probe(base_url, api_key=""):
            return "some-model" if base_url in answering else None

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(speech_compare.llm_mod, "probe", probe):
            self.run_compare(folder, detect=lambda: judge)
        return judge

    def test_live_judge_stops_when_the_red_team_server_is_down(self):
        # detect() would have handed the judge role to the target without saying so.
        with tempfile.TemporaryDirectory() as tmp:
            recorded = Path(tmp) / "whisper_compare.json"
            recorded.write_text('{"stale": true}')
            with self.assertRaises(SystemExit) as stop:
                self.run_live(Path(tmp), {TARGET_URL})
            self.assertEqual(recorded.read_text(), '{"stale": true}')
        self.assertIn(f"nothing answers at {RED_URL} (the attacker and judge)",
                      stop.exception.code)

    def test_live_judge_runs_when_both_servers_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            judge = self.run_live(Path(tmp), {TARGET_URL, RED_URL})
            self.assertTrue((Path(tmp) / "whisper_compare.json").exists())
        self.assertEqual(judge.calls, 2)

    def test_dialect_without_whisper_transcripts_shows_dashes(self):
        row = {"dialect": "vs", "apertus": {"unrelated_rate": 0.25, "mean_chrf": 31.0},
               "whisper": None}
        self.assertEqual(speech_compare.table([row]).splitlines()[1].split(),
                         ["vs", "25%", "-", "31.0", "-"])


if __name__ == "__main__":
    unittest.main()
