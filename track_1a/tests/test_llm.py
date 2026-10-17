import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import llm  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
