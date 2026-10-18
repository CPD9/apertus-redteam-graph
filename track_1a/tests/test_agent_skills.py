"""The roster of characters: skills and learnings computed from a tiny recorded run."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK / "src"))

from helpers import LANGS, use_runs, write_run  # noqa: E402
from redteam import agent_skills, answers  # noqa: E402
from redteam.agent_facts import run_facts  # noqa: E402
from redteam.agents import LANG_NAMES  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

OLD, NEW = "20261016-120000-aaaa", "20261018-090000-bbbb"
REFS = {h["id"]: h for h in load_hypotheses()}
CHARACTERS = json.loads(agent_skills.CHARACTERS.read_text())
MITIGATION = {"mitigation": {"pairs": 6, "per_lang": {"en": {"without": 1, "with": 2},
                                                      "de": {"without": 3, "with": 0}}}}


def with_attacks(run_dir: Path) -> None:
    """Adds what helpers.write_run leaves out: two attempts per hypothesis, a code switch that
    lands nothing and then a false premise, the mutator's language check (German named wrong)
    and the judge's probe verdicts."""
    log = run_dir / "events.jsonl"
    events, out = [json.loads(line) for line in log.read_text().splitlines()], []
    for event in events:
        hyp = event["hypothesis"]
        if (event["node"], event["status"]) == ("mutator", "done"):
            event["data"]["detected"] = {lang: "English" if lang == "de" else LANG_NAMES[lang]
                                         for lang in LANGS}
            for attempt, strategy, severity in ((1, "code_switch", 0), (2, "false_premise", 7)):
                out += [dict(event, node="attacker", status="start", data={"attempt": attempt}),
                        dict(event, node="attacker", status="done", data={"strategy": strategy}),
                        dict(event, node="judge", status="done",
                             data={"lang": "en", "violation": bool(severity),
                                   "severity": severity})]
        out.append(event)
    log.write_text("".join(json.dumps(e) + "\n" for e in out))


class RosterTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs, self.cache = tmp / "runs", tmp / "cache"
        use_runs(self, self.runs)
        self.enterContext(mock.patch.object(answers, "CACHE_DIR", self.cache))
        self.enterContext(mock.patch.object(agent_skills, "ROSTER", tmp / "roster.json"))
        self.enterContext(mock.patch.object(agent_skills, "RECORDED", [OLD]))
        self.enterContext(mock.patch.object(agent_skills, "rebuilt", lambda: {"a": [], "b": ["x"]}))
        write_run(self.runs, self.cache, OLD)
        with_attacks(self.runs / OLD)

    def facts(self, run_id=OLD):
        return run_facts(self.runs / run_id, REFS)

    def agent(self, roster, agent_id):
        return next(a for a in roster if a["id"] == agent_id)

    def test_facts_follow_the_counting_rule(self):
        facts = self.facts()
        self.assertEqual((facts.hypotheses, facts.reproduced), (5, 4))  # one only corrects
        self.assertEqual((facts.counted.n, facts.date), (45, "2026-10-16"))
        premise, switch = facts.strategies["false_premise"], facts.strategies["code_switch"]
        self.assertEqual((premise.attempts, premise.landed, premise.verified), (5, 5, 5))
        self.assertEqual((switch.attempts, switch.landed, switch.verified), (5, 0, 0))
        self.assertEqual((facts.language_check["de"].k, facts.language_check["en"].k), (0, 5))

    def test_every_character_gets_its_fields_and_evidence(self):
        roster = agent_skills.roster(CHARACTERS, [self.facts()], [], {}, [], "2026-10-18")
        self.assertEqual([a["id"] for a in roster], [c["id"] for c in CHARACTERS])
        for agent in roster:
            self.assertEqual(agent["avatar"], f"avatars/{agent['id']}.png")
            for item in agent["skills"] + agent["learnings"]:
                self.assertTrue(item["evidence"] and item["since"], item)
        verifier = self.agent(roster, "verifier")["skills"]
        rule = next(s for s in verifier if s["id"] == "counting-rule")
        self.assertEqual(rule["evidence"][0]["value"], "4 of 5 hypotheses reproduced (80%)")
        self.assertEqual(rule["evidence"][0]["source"], f"{self.runs / OLD}/events.jsonl")
        attacker = self.agent(roster, "attacker")
        self.assertEqual([s["id"] for s in attacker["skills"]], ["strategy-false_premise"])
        self.assertIn("Code switch never produced an answer that counts: none in 5 attempts",
                      attacker["learnings"][0]["text"])

    def test_an_audit_skill_keeps_the_date_it_was_first_learned(self):
        previous = [{"id": "target", "skills": [{"id": "heeds-a-system-prompt",
                                                 "since": "2026-10-01"}]}]
        roster = agent_skills.roster(CHARACTERS, [self.facts()], [], {"stats": MITIGATION},
                                     previous, "2026-10-18")
        target = self.agent(roster, "target")
        heeds = next(s for s in target["skills"] if s["id"] == "heeds-a-system-prompt")
        self.assertEqual(heeds["since"], "2026-10-01")
        self.assertEqual(heeds["evidence"][0]["value"], "4 of 6 answers (67%)")
        rose = [l["text"] for l in target["learnings"] if "did not help" in l["text"]]
        self.assertEqual(rose, ["The mitigation prompt did not help in English: answers that "
                                "count rose from 1 of 3 (33%) to 2 of 3 (67%) on the same "
                                "prompts."])

    def test_a_new_run_adds_dated_changes_and_is_remembered(self):
        # A hypothesis the old run did not ask, so its cached answers are its own.
        write_run(self.runs, self.cache, NEW,
                  grid={"vote_initiative_signatures": {lang: "rrr" for lang in LANGS}})
        roster = agent_skills.roster(CHARACTERS, [self.facts()], [self.facts(NEW)], {}, [],
                                     "2026-10-18")
        verifier = self.agent(roster, "verifier")["learnings"]
        self.assertIn("2026-10-18, 8B run 20261018-090000-bbbb: reproduced: 0 of 1 hypotheses "
                      "(0%); in the 8B run 20261016-120000-aaaa: 4 of 5 hypotheses (80%).",
                      [l["text"] for l in verifier])
        self.assertTrue(all(any(l["source"] == NEW for l in a["learnings"]) for a in roster))
        self.assertEqual(agent_skills.remembered(roster), [NEW])

    def test_a_mock_run_teaches_nothing_about_apertus(self):
        write_run(self.runs, self.cache, NEW, backend="MOCK")
        roster = agent_skills.roster(CHARACTERS, [self.facts()], [self.facts(NEW)], {}, [],
                                     "2026-10-18")
        noted = [(a["id"], l["text"]) for a in roster for l in a["learnings"]
                 if l["source"] == NEW]
        self.assertEqual(len(noted), 1)
        self.assertEqual(noted[0][0], "verifier")
        self.assertIn("MOCK backend", noted[0][1])

    def test_learn_writes_the_roster_and_refuses_an_unknown_run(self):
        write_run(self.runs, self.cache, NEW)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(agent_skills.main(["--run", NEW]), 0)
            self.assertEqual(agent_skills.main([]), 0)  # keeps learning from NEW
        roster = json.loads(agent_skills.ROSTER.read_text())
        self.assertIn("learned from 2 runs", out.getvalue().splitlines()[-1])
        scribe = self.agent(roster, "scribe")["skills"]
        self.assertEqual(scribe[1]["evidence"][0]["value"], "1 of 2 files (50%)")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            agent_skills.main(["--run", "nope"])
        self.assertEqual(stop.exception.code, 2)


@unittest.skipUnless((TRACK / "docs").is_dir(), "docs/ is not part of this copy (Docker image)")
class ShippedRosterTest(unittest.TestCase):
    def test_the_roster_names_every_character_and_its_sources_exist(self):
        roster = json.loads(agent_skills.ROSTER.read_text())
        self.assertEqual([a["id"] for a in roster], [c["id"] for c in CHARACTERS])
        for agent in roster:
            for item in agent["skills"] + agent["learnings"]:
                for proof in item["evidence"]:
                    with self.subTest(agent=agent["id"], label=proof["label"]):
                        self.assertTrue((TRACK / proof["source"]).exists())


if __name__ == "__main__":
    unittest.main()
