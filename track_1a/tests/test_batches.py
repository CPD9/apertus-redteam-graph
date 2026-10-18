"""infra/runpod/batches.sh morning: as --dry-run prints it, the checks that stop it before any GPU
time, and its live waiting, switching and stopping with curl, ssh and the pod's tools replaced; and
the opt-in bank of invented persons that its third step runs."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
RUNPOD = TRACK / "infra" / "runpod"
SRC = TRACK / "src" / "redteam"
sys.path.insert(0, str(TRACK / "src"))

from redteam.group import THEMES, subject  # noqa: E402
from redteam.llm import MODELS_FILE  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

CANONICAL, RUN70 = "20261016-172309-1f71", "20261017-140533-a21a"
TARGET, RED = "http://127.0.0.1:8000/v1", "http://127.0.0.1:8002/v1"
APERTUS_8B, JUDGE = "swiss-ai/Apertus-v1.5-8B", "apertus-70b-fp8"
BASELINE_URL, BASELINE = "http://127.0.0.1:8001/v1", "Qwen/Qwen2.5-7B-Instruct"
SSH = ["ssh", "-p", "2222", "root@pod.test"]
INVENTED = json.loads((SRC / "invented_persons.json").read_text())
SLEEP = shutil.which("sleep")


def guard(verb: str, url: str, model: str) -> list[str]:
    return ["check", "that", url, "serves", model] if verb == "check" else \
           ["wait", "until", url, "serves", model]


def run(label: str, ids: list[str]) -> list[str]:
    return ["python3", "-m", "redteam.run", "--label", label, "--parallel", "8", "--only", *ids]


def stub(path: Path, body: str):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@unittest.skipUnless(RUNPOD.is_dir(), "infra/ is not part of this copy (Docker image)")
class MorningTest(unittest.TestCase):
    """The batch runs in a copy of the files it reads. curl answers with the model lists of the file
    `replies` in turn ("-" when nothing answers), ssh exits with the codes of `ssh_codes` in turn,
    and both note every call in `calls`."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = root = Path(d.name)
        (root / "infra" / "runpod").mkdir(parents=True)
        shutil.copy(RUNPOD / "batches.sh", root / "infra" / "runpod")
        self.pin("0" * 40)
        (root / "src" / "redteam" / "hypotheses").mkdir(parents=True)
        shutil.copy(SRC / "hypotheses" / "bank2.json", root / "src" / "redteam" / "hypotheses")
        shutil.copy(SRC / "neutral_questions.json", root / "src" / "redteam")
        self.bank3 = root / "src" / "redteam" / "hypotheses" / "bank3.json"
        shutil.copy(SRC / "invented_persons.json", self.bank3)
        log = root / "data" / "runs" / CANONICAL / "events.jsonl"
        log.parent.mkdir(parents=True)
        with (TRACK / "data" / "runs" / CANONICAL / "events.jsonl").open() as f:
            log.write_text(f.readline())
        (root / "bin").mkdir()
        stub(root / "bin" / "curl", f"""echo "curl $*" >> '{root}/calls'
n=$(grep -c '^curl' '{root}/calls')
reply=$(sed -n "${{n}}p" '{root}/replies' 2> /dev/null)
[ -n "$reply" ] || reply=$(tail -n 1 '{root}/replies' 2> /dev/null)
[ -n "$reply" ] && [ "$reply" != - ] || exit 7
echo "$reply"
""")
        stub(root / "bin" / "ssh", f"""echo "ssh $*" >> '{root}/calls'
n=$(grep -c '^ssh' '{root}/calls')
exit $(sed -n "${{n}}p" '{root}/ssh_codes' 2> /dev/null | grep . || echo 0)
""")
        self.git(0)

    def pin(self, revision: str):
        script = (RUNPOD / "serve_baseline.sh").read_text()
        (self.root / "infra" / "runpod" / "serve_baseline.sh").write_text(
            re.sub(r"(?m)^REVISION=.*$", f"REVISION={revision}", script))

    def git(self, code: int):  # whether docs/PREREGISTRATION.md is committed as it stands
        stub(self.root / "bin" / "git", f"exit {code}\n")

    def replies(self, *models: str):
        (self.root / "replies").write_text("".join(
            "-\n" if m == "-" else json.dumps({"data": [{"id": m}]}) + "\n" for m in models))

    def ssh_codes(self, *codes: int):
        (self.root / "ssh_codes").write_text("".join(f"{c}\n" for c in codes))

    def calls(self, tool: str) -> list[str]:
        calls = self.root / "calls"
        lines = calls.read_text().splitlines() if calls.exists() else []
        return [line[len(tool) + 1:] for line in lines if line.startswith(tool + " ")]

    def bash(self, *argv, **env) -> subprocess.CompletedProcess:
        unset = {"LLM_BASE_URL", "RED_LLM_BASE_URL", "BASELINE_URL", "CANONICAL_RUN", "KEEP_POD"}
        environ = {k: v for k, v in os.environ.items() if k not in unset}
        environ.update({"PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
                        "POD_HOST": "root@pod.test", "POD_PORT": "2222", **env})
        return subprocess.run(["bash", *argv], cwd=self.root, env=environ, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)

    def batch(self, *argv, **env) -> subprocess.CompletedProcess:
        done = self.bash("infra/runpod/batches.sh", *argv, **env)
        if "--dry-run" in argv:
            self.assertEqual(self.calls("curl") + self.calls("ssh"), [])
        return done

    def call(self, *argv) -> subprocess.CompletedProcess:
        """One function of the script, live; each round of waiting moves the clock 10 minutes."""
        script = 'source infra/runpod/batches.sh; sleep() { SECONDS=$((SECONDS + 600)); }; "$@"'
        return self.bash("-c", script, "_", *argv)

    @staticmethod
    def steps(done) -> list[list[str]]:
        return [shlex.split(line[2:]) for line in done.stdout.splitlines() if line.startswith("+ ")]

    def test_the_plan_of_the_preregistration_in_order(self):
        done = self.batch("--dry-run", "morning")
        self.assertEqual(done.returncode, 0, done.stderr)
        canonical = json.loads(MODELS_FILE.read_text())["hypotheses"]
        bank2 = [h["id"] for h in json.loads((SRC / "hypotheses" / "bank2.json").read_text())]
        rejudge = ["python3", "-m", "redteam.rejudge", "--judge-url", BASELINE_URL,
                   "--judge-name", BASELINE]
        steps = self.steps(done)
        self.assertEqual(steps, [
            SSH + ["bash", "-s"],
            SSH + ["bash", "-s", "--", "serve_baseline.sh"], guard("wait", BASELINE_URL, BASELINE),
            rejudge[:3] + ["--run", CANONICAL] + rejudge[3:],
            rejudge[:3] + ["--run", RUN70] + rejudge[3:],
            SSH + ["bash", "-s", "--", "serve_8b.sh"],
            guard("wait", TARGET, APERTUS_8B), guard("wait", RED, JUDGE),
            ["python3", "-m", "redteam.control", "--run", CANONICAL,
             "--neutral", "src/redteam/neutral_questions.json"],
            guard("check", TARGET, APERTUS_8B), guard("check", RED, JUDGE),
            run("8B invented persons", [h["id"] for h in INVENTED]),
            guard("check", TARGET, APERTUS_8B), guard("check", RED, JUDGE),
            run("8B bank 2", bank2),
            SSH + ["bash", "-s", "--", "serve_baseline.sh"], guard("wait", BASELINE_URL, BASELINE),
            guard("check", RED, JUDGE),
            ["env", f"LLM_BASE_URL={BASELINE_URL}", *run(f"baseline {BASELINE}", canonical)],
            SSH + ["bash", "/workspace/stop_pod.sh"]])
        self.assertEqual(len(canonical), 41)

    def assert_stops_before_anything_runs(self, done, says: str):
        self.assertEqual(done.returncode, 1)
        self.assertIn(says, done.stderr)
        self.assertEqual(self.steps(done), [])

    def test_each_check_before_gpu_time_stops_the_batch(self):
        cases = [("an uncommitted plan", lambda: self.git(1), "commit docs/PREREGISTRATION.md"),
                 ("an empty id list", lambda: self.bank3.write_text("[]"),
                  "no hypothesis ids in src/redteam/hypotheses/bank3"),
                 ("no opt-in bank", lambda: self.bank3.unlink(), "bank 3 is opt-in"),
                 ("no pinned commit", lambda: self.pin(""), "pin REVISION in infra/runpod/")]
        for case, spoil, says in cases:
            with self.subTest(case):
                self.setUp()
                spoil()
                self.assert_stops_before_anything_runs(self.batch("--dry-run", "morning"), says)

    def test_the_pod_must_be_named(self):
        done = self.batch("--dry-run", "morning", POD_HOST="")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("POD_HOST", done.stderr)
        self.assertEqual(self.steps(done), [])

    def test_a_dry_run_is_only_for_the_morning_and_an_unknown_batch_is_refused(self):
        for argv in (["--dry-run", "target70"], ["--dry-run", "all"], ["nightly"]):
            with self.subTest(argv=argv):
                done = self.batch(*argv)
                self.assertEqual(done.returncode, 2)
                self.assertIn("usage:", done.stderr)

    def test_a_failed_step_stops_the_pod_unless_it_is_kept(self):
        for keep, says, stopped in (("", "stopping the pod", True),
                                    ("1", "the pod runs until stop_pod.sh", False)):
            with self.subTest(KEEP_POD=keep):
                self.setUp()
                self.ssh_codes(255)  # the pod cannot be reached to start the red-team model
                done = self.batch("morning", KEEP_POD=keep)
                self.assertEqual(done.returncode, 255)
                self.assertIn(says, done.stderr)
                stop = "-p 2222 root@pod.test bash /workspace/stop_pod.sh"
                self.assertEqual(self.calls("ssh")[1:], [stop] if stopped else [])

    def test_waiting_ends_when_the_model_answers_and_an_ssh_that_fails_is_tried_again(self):
        self.replies("-", "-", BASELINE)
        self.ssh_codes(255, 0)
        done = self.call("await", BASELINE_URL, BASELINE, "8001", "serve_baseline.log")
        self.assertEqual(done.returncode, 0, done.stderr)
        alive = "-p 2222 root@pod.test bash -s -- 8001 serve_baseline.log"
        self.assertEqual(self.calls("ssh"), [alive, alive])

    def test_waiting_stops_on_another_model_an_exited_server_or_after_30_minutes(self):
        cases = [(["-", APERTUS_8B], [], f"serves '{APERTUS_8B}', not {BASELINE}", 1),
                 (["-"], [0, 3], "server for port 8001 exited on the pod", 2),
                 (["-"], [], "nothing answers on http://127.0.0.1:8001/v1 after 30 minutes", 4)]
        for replies, codes, says, rounds in cases:
            with self.subTest(says):
                self.setUp()
                self.replies(*replies)
                self.ssh_codes(*codes)
                done = self.call("await", BASELINE_URL, BASELINE, "8001", "serve_baseline.log")
                self.assertEqual(done.returncode, 1)
                self.assertIn(says, done.stderr)
                self.assertEqual(len(self.calls("ssh")), rounds)

    def test_gpu_0_switches_only_when_it_serves_another_model(self):
        self.replies(BASELINE)
        done = self.call("gpu0", "serve_baseline.sh", BASELINE_URL, BASELINE, "8001")
        self.assertEqual((done.returncode, self.calls("ssh")), (0, []))
        self.setUp()
        self.replies("-", "-", BASELINE)
        done = self.call("gpu0", "serve_baseline.sh", BASELINE_URL, BASELINE, "8001")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls("ssh"),
                         ["-p 2222 root@pod.test bash -s -- serve_baseline.sh",
                          "-p 2222 root@pod.test bash -s -- 8001 serve_baseline.log"])

    def test_the_scripts_parse(self):
        for script in ("batches.sh", "serve_baseline.sh"):
            with self.subTest(script=script):
                done = subprocess.run(["bash", "-n", str(RUNPOD / script)], capture_output=True,
                                      text=True)
                self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipUnless(RUNPOD.is_dir(), "infra/ is not part of this copy (Docker image)")
class OnThePodTest(unittest.TestCase):
    """What batches.sh runs on the pod, in a folder standing in for /workspace, with pkill, pgrep,
    nvidia-smi and sleep replaced: nvidia-smi reads the file `mib`, pgrep exits with `pgrep`."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.pod = pod = Path(d.name)
        (pod / "bin").mkdir()
        stub(pod / "bin" / "pkill", f"echo \"pkill $*\" >> '{pod}/calls'\n")
        stub(pod / "bin" / "pgrep", f"exit $(cat '{pod}/pgrep')\n")
        stub(pod / "bin" / "nvidia-smi", f"cat '{pod}/mib'\n")
        stub(pod / "bin" / "sleep", f'[ "$1" = 20 ] && exec {SLEEP} 1\nexit 0\n')

    def remote(self, name: str, *argv) -> subprocess.CompletedProcess:
        text = subprocess.run(["bash", "-c", f'source "$1"; printf %s "${name}"', "_",
                               str(RUNPOD / "batches.sh")], capture_output=True, text=True).stdout
        environ = {**os.environ, "PATH": f"{self.pod / 'bin'}{os.pathsep}{os.environ['PATH']}"}
        return subprocess.run(["bash", "-s", "--", *argv], cwd=self.pod, env=environ, timeout=60,
                              input=text.replace("cd /workspace", f"cd '{self.pod}'"),
                              capture_output=True, text=True)

    def serve(self, name: str, body: str):
        (self.pod / name).write_text(body)

    def test_the_switch_stops_gpu_0_and_starts_the_script_once_its_memory_is_free(self):
        (self.pod / "mib").write_text("300\n")
        self.serve("serve_up.sh", f"echo $$ > '{self.pod}/pid'\nexec {SLEEP} 30\n")
        done = self.remote("GPU0_SWITCH", "serve_up.sh")
        if (self.pod / "pid").exists():
            self.addCleanup(os.kill, int((self.pod / "pid").read_text()), 15)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.pod / "calls").read_text(),
                         "pkill -f [v]llm serve .*--port 800[01]\n")

    def test_the_switch_fails_with_the_log_of_a_script_that_exits_at_once(self):
        (self.pod / "mib").write_text("300\n")
        self.serve("serve_down.sh", "echo 'pin REVISION first' >&2\nexit 1\n")
        done = self.remote("GPU0_SWITCH", "serve_down.sh")
        self.assertEqual(done.returncode, 1)
        self.assertIn("pin REVISION first", done.stderr)

    def test_the_switch_starts_nothing_without_a_reading_or_while_gpu_0_stays_full(self):
        for mib, says in ((None, "nvidia-smi read no memory use of GPU 0"),
                          ("30000\n", "GPU 0 still holds 30000 MiB")):
            with self.subTest(says):
                if mib:
                    (self.pod / "mib").write_text(mib)
                self.serve("serve_up.sh", "exit 0\n")
                done = self.remote("GPU0_SWITCH", "serve_up.sh")
                self.assertEqual(done.returncode, 1)
                self.assertIn(says, done.stderr)
                self.assertFalse((self.pod / "serve_up.log").exists())

    def test_alive_passes_while_the_server_runs_and_shows_its_log_once_it_is_gone(self):
        (self.pod / "serve_8b.log").write_text("loading\nCUDA out of memory\n")
        for running, code in ((0, 0), (1, 3)):
            with self.subTest(running=running):
                (self.pod / "pgrep").write_text(str(running))
                done = self.remote("ALIVE", "8000", "serve_8b.log")
                self.assertEqual(done.returncode, code)
                self.assertEqual("CUDA out of memory" in done.stderr, bool(code))


class InventedPersonsTest(unittest.TestCase):
    """src/redteam/invented_persons.json, the bank the morning's third step runs once it is copied
    to src/redteam/hypotheses/bank3.json."""

    def test_entries_have_the_bank_format_and_titles_of_their_own(self):
        ids = {h["id"] for h in INVENTED}
        others = {h["title"] for h in load_hypotheses() if h["id"] not in ids}
        titles = [h["title"] for h in INVENTED]
        self.assertEqual(len(set(titles)), len(titles))
        for h in INVENTED:
            with self.subTest(hypothesis=h["id"]):
                self.assertEqual(set(h), {"id", "title", "topic_area", "domain", "hypothesis",
                                          "reference", "harm", "sources"})
                self.assertLessEqual(len(h["title"]), 40)
                self.assertNotIn(h["title"], others)

    def test_each_names_a_made_up_person_and_asks_not_to_vouch_for_details(self):
        for h in INVENTED:
            with self.subTest(hypothesis=h["id"]):
                name = re.search(r"'([^']+)'", h["hypothesis"]).group(1)
                self.assertIn(f"{name} of ", h["reference"])
                self.assertIn("is a name made up for this test", h["reference"])
                self.assertNotIn("no reliable source", h["reference"])
                self.assertIn("Desired: say there is no reliable information", h["reference"])

    def test_each_falls_into_the_private_person_theme_only(self):
        for h in INVENTED:
            with self.subTest(hypothesis=h["id"]):
                themes = [t["id"] for t in THEMES if subject(t, h["id"])]
                self.assertEqual(themes, ["private_person_fabrication"])


if __name__ == "__main__":
    unittest.main()
