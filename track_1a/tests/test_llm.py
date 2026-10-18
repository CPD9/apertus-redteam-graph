import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import llm  # noqa: E402
from redteam.llm_json import lenient_json, parse_json  # noqa: E402

TARGET = "http://target.test:8000/v1"
RED = "http://red.test:8002/v1"


class RequireServersTest(unittest.TestCase):
    """The check `make live` runs before a paid run."""

    def check(self, answering, **env):
        probed = []

        def probe(base_url, api_key=""):
            probed.append((base_url, api_key))
            return "some-model" if base_url in answering else None

        env = {"LLM_BASE_URL": TARGET, "RED_LLM_BASE_URL": RED, **env}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(llm, "probe", probe):
            llm.require_servers()
        return probed

    def test_passes_when_both_servers_answer(self):
        self.assertEqual(self.check({TARGET, RED}), [(TARGET, ""), (RED, "")])

    def test_stops_when_the_target_is_down(self):
        with self.assertRaises(SystemExit) as stop:
            self.check({RED})
        self.assertIn(f"nothing answers at {TARGET} (the target)", stop.exception.code)

    def test_stops_when_only_the_red_team_server_is_down(self):
        # detect() would hand the attacker and judge roles to the target here.
        with self.assertRaises(SystemExit) as stop:
            self.check({TARGET})
        self.assertIn(f"nothing answers at {RED} (the attacker and judge)", stop.exception.code)

    def test_each_server_is_asked_with_its_own_key(self):
        probed = self.check({TARGET, RED}, LLM_API_KEY="t-key", RED_LLM_API_KEY="r-key")
        self.assertEqual(probed, [(TARGET, "t-key"), (RED, "r-key")])

    def test_the_target_may_judge_itself_when_asked_to(self):
        self.check({TARGET}, RED_LLM_BASE_URL=TARGET)


class JsonReplyTest(unittest.TestCase):
    """Reading the JSON object out of a model's reply (redteam.llm_json)."""

    def test_parse_json_handles_prose_and_fences(self):
        self.assertEqual(parse_json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_lenient_json_accepts_raw_newlines_inside_strings(self):
        reply = '{"prompt": "line one\nline two"}'
        with self.assertRaises(ValueError):
            parse_json(reply)
        self.assertEqual(lenient_json(reply), {"prompt": "line one\nline two"})

    def test_lenient_json_reads_the_first_object_and_ignores_what_follows(self):
        reply = 'Here it is: {"a": 1} and a second one: {"b": 2}'
        with self.assertRaises(ValueError):
            parse_json(reply)
        self.assertEqual(lenient_json(reply), {"a": 1})

    def test_lenient_json_takes_the_first_reply_that_parses(self):
        self.assertEqual(lenient_json('{"a": 1}', '{"a": 2}'), {"a": 1})
        self.assertEqual(lenient_json('{"a": ', '{"a": 2}'), {"a": 2})
        self.assertEqual(lenient_json("no object here", '{"a": 3}'), {"a": 3})

    def test_lenient_json_rejects_replies_without_a_whole_object(self):
        for replies in (('{"prompt": "cut off',), ("Sorry, I cannot help with that.",),
                        ('{"prompt": "cut off', "no object here")):
            with self.subTest(replies=replies), self.assertRaises(ValueError):
                lenient_json(*replies)

    def test_lenient_json_only_tries_the_first_brace_of_a_reply(self):
        with self.assertRaises(ValueError):
            lenient_json('{draft} {"a": 1}')


if __name__ == "__main__":
    unittest.main()
