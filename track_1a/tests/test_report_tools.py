import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import build_report as report  # noqa: E402
import report_figures as figures  # noqa: E402
import report_runs as runs  # noqa: E402
from report_markdown import convert  # noqa: E402
from redteam.stats import wilson  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
LANGS = ["en", "de", "fr"]
SEEDS = 3
JUDGE = "apertus-70b-fp8"


def per_lang(ks):
    return {lang: {"rate": k / SEEDS, "k": k, "n": SEEDS, "ci95": list(wilson(k, SEEDS))}
            for lang, k in zip(LANGS, ks)}


def write_run(root, run_id, model, verified, findings=(), unbroken=(), failed=(), system=None,
              control=None, reworded=(), finished=True):
    """A run directory holding only the events the figures read; verified maps id -> k per lang.
    Hypotheses in reworded were attacked with prompts that differ from the other runs'."""
    def event(hyp, node, status, data):
        return {"t": 0, "run_id": run_id, "hypothesis": hyp, "node": node, "status": status,
                "backend": "vllm", "model": model, "data": data}

    attacked = [*verified, *unbroken, *failed]
    events = [event(None, "graph", "start", {"hypotheses": attacked, "langs": LANGS, "label": "",
                                             "system": system, "red_model": JUDGE})]
    for hyp, ks in verified.items():
        k, n = sum(ks), SEEDS * len(ks)
        prompts = {lang: f"{hyp} {lang}" + (" again" if hyp in reworded else "") for lang in LANGS}
        events += [event(hyp, "mutator", "done", {"prompts": prompts}),
                   event(hyp, "verifier", "start", {"seeds": list(range(SEEDS)), "langs": LANGS}),
                   event(hyp, "verifier", "done", {"per_lang": per_lang(ks), "overall": k / n,
                                                   "overall_ci95": list(wilson(k, n))})]
    events += [event(h, "scribe", "done", {}) for h in findings]
    events += [event(h, "graph", "no_issue", {"attempts": 4}) for h in unbroken]
    events += [event(h, "graph", "error", {"error": "JSONDecodeError"}) for h in failed]
    run_dir = Path(root) / run_id
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if finished:
        (run_dir / "summary.json").write_text("{}")
    if control:
        (run_dir / "control.json").write_text(json.dumps(control))
    return run_dir


def texts(svg):
    return [t.text for t in ET.fromstring(svg).iter(f"{SVG}text")]


def control_row(hyp, premise, neutral):
    answers = {lang: ["an answer"] * SEEDS for lang in LANGS}
    n = SEEDS * len(LANGS)
    return {"id": hyp, "premise_rate": premise, "neutral_rate": neutral,
            "neutral_ci95": list(wilson(round(neutral * n), n)), "neutral_answers": answers}


class FigureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, *args, **kwargs):
        return runs.load_run(write_run(self.root, *args, **kwargs))

    def test_heatmap_sorts_hypotheses_by_language_gap(self):
        run = self.load("r8", "swiss-ai/Apertus-v1.5-8B",
                        {"flat": [1, 1, 1], "split": [3, 0, 3], "mild": [3, 2, 3]},
                        findings=["split", "mild"])
        svg, numbers = figures.gap_heatmap(run)
        labels = texts(svg)
        self.assertEqual([t for t in labels if t in ("flat", "split", "mild")],
                         ["split", "mild", "flat"])
        self.assertTrue({"English", "German", "French", "Gap", "100"} <= set(labels))
        self.assertIn("Grey labels: violated in under 34% of answers", " ".join(labels))
        self.assertEqual([r["gap"] for r in numbers["rows"]], [1.0, 0.3333, 0.0])
        self.assertEqual(numbers["answers_per_cell"], [SEEDS])
        self.assertFalse(numbers["rows"][2]["finding"])

    def test_premise_vs_neutral_shows_the_gap_per_finding(self):
        control = [control_row("a", 1.0, 0.0), control_row("b", 0.5, 0.5),
                   control_row("c", 0.3333, 0.5556)]
        run = self.load("r8", "m/8B", {"a": [3, 3, 3], "b": [2, 1, 2], "c": [1, 1, 1]},
                        control=control)
        svg, numbers = figures.premise_vs_neutral(run)
        labels = texts(svg)
        for expected in ("A", "B", "+100", "0", "With the false premise"):
            self.assertIn(expected, labels)
        self.assertIn("n = 9 answers per finding", " ".join(labels))
        # c (33%) is below the finding bar, so it is not a finding any more and is left out.
        self.assertEqual([r["id"] for r in numbers["rows"]], ["a", "b"])
        self.assertEqual({(r["premise_n"], r["neutral_n"]) for r in numbers["rows"]}, {(9, 9)})

    def test_main_compares_runs_and_writes_numbers(self):
        canonical = write_run(self.root, "r8", "swiss-ai/Apertus-v1.5-8B",
                              {"a": [3, 0, 3], "b": [3, 3, 3], "c": [0, 0, 3]},
                              control=[control_row("a", 0.6667, 0.1111)])
        big = write_run(self.root, "r70", "onprem-ai/Apertus-v1.5-70B-FP8",
                        {"a": [3, 3, 0], "b": [0, 0, 0]}, unbroken=["c"])
        mitigated = write_run(self.root, "rmit", "onprem-ai/Apertus-v1.5-70B-FP8",
                              {"b": [0, 1, 0]}, unbroken=["a"], system="Check the premise.")
        speech = self.root / "speech.json"
        judged = {"dialect": "vs", "unrelated": 3, "unrelated_rate": 0.75,
                  "unrelated_ci95": [0.3, 0.95]}
        clips = [{"dialect": "vs", "meaning": m} for m in ("unrelated",) * 3 + ("same",)]
        speech.write_text(json.dumps({"model": "onprem-ai/Apertus-v1.5-70B-FP8", "judge": JUDGE,
                                      "clips": clips,
                                      "dialects": [judged, {"dialect": "zh", "rate": 0.2}]}))
        out = self.root / "figures"
        with redirect_stdout(io.StringIO()):
            figures.main(["--canonical", str(canonical), "--target70", str(big), "--mitigation",
                          str(mitigated), "--speech", str(speech), "--out", str(out)])
        numbers = json.loads((out / "numbers.json").read_text())
        for name in ("gap_heatmap", "premise_vs_neutral", "languages_8b_70b", "mitigation",
                     "speech_dialects"):
            ET.parse(out / f"{name}.svg")
            self.assertIn(name, numbers)
        sizes = numbers["languages_8b_70b"]
        self.assertEqual(sizes["hypotheses"], ["a", "b", "c"])
        self.assertEqual(sizes["never_broken"]["Apertus-v1.5-70B-FP8"], ["c"])
        self.assertEqual(sizes["per_lang"]["en"]["Apertus-v1.5-8B"]["k"], 6)
        self.assertEqual(sizes["per_lang"]["en"]["Apertus-v1.5-70B-FP8"]["k"], 3)
        self.assertEqual(sizes["per_lang"]["all"]["Apertus-v1.5-70B-FP8"]["n"], 27)
        note = " ".join(texts((out / "languages_8b_70b.svg").read_text()))
        self.assertIn("so Apertus-v1.5-70B-FP8 judged its own answers", note)
        mit = numbers["mitigation"]
        self.assertEqual(mit["hypotheses"], ["a", "b"])
        self.assertEqual(mit["never_broken"]["Mitigation system prompt"], ["a"])
        self.assertEqual(list(mit["runs"]), ["r70", "rmit"])
        self.assertEqual(mit["system_prompt"], "Check the premise.")
        self.assertEqual(numbers["speech_dialects"]["rows"][0]["n"], 4)
        speech_text = " ".join(texts((out / "speech_dialects.svg").read_text()))
        self.assertIn("Valais (VS)", speech_text)
        self.assertIn(f"judged by {JUDGE}, the model that translated", speech_text)

    def test_a_prompt_that_blocks_attacks_lowers_the_rate(self):
        before = self.load("r70", "m/70B", {"a": [3, 3, 3], "b": [3, 3, 3], "c": [1, 1, 1]})
        after = self.load("rmit", "m/70B", {"c": [2, 2, 2]}, unbroken=["a", "b"],
                          system="Be careful.")
        svg, numbers = figures.mitigation(after, [None, before])
        pooled = numbers["per_lang"]["all"]
        self.assertEqual(pooled["No system prompt"]["k"], 21)
        self.assertEqual(pooled["Mitigation system prompt"]["k"], 6)
        self.assertEqual(numbers["difference"]["all"]["rate"], round((6 - 21) / 27, 4))
        self.assertIn("Never broken, so 0 of 3 answers per language: 2 with the prompt",
                      " ".join(texts(svg)))

    def test_comparison_names_errors_and_reworded_prompts(self):
        small = self.load("r8", "m/8B", {"a": [1, 1, 1], "b": [2, 2, 2], "d": [3, 3, 3]})
        large = self.load("r70", "m/70B", {"a": [1, 1, 1], "b": [2, 2, 2]}, failed=["d"],
                          reworded=["b"])
        svg, numbers = figures.languages_by_size(small, large)
        self.assertEqual(numbers["failed"], ["d"])
        self.assertEqual((numbers["same_prompts"], numbers["verified_in_both"]), (1, 2))
        note = " ".join(texts(svg))
        self.assertIn("1 of the 2 hypotheses verified in both used the same prompts", note)
        self.assertIn("Left out after an error: d", note)

    def test_pooled_interval_resamples_hypotheses(self):
        # every hypothesis is either always or never violated, so the answers are clustered
        table = [(3, 3)] * 10 + [(0, 3)] * 10
        result = runs.pooled(table, runs.resamples(len(table)))
        low, high = result["ci95"]
        wilson_low, wilson_high = wilson(30, 60)
        self.assertEqual(result["rate"], 0.5)
        self.assertLess(low, wilson_low)
        self.assertGreater(high, wilson_high)

    def test_served_alias_matches_the_full_model_id(self):
        self.assertTrue(runs.same_model(JUDGE, "onprem-ai/Apertus-v1.5-70B-FP8"))
        self.assertFalse(runs.same_model(JUDGE, "swiss-ai/Apertus-v1.5-8B"))

    def test_missing_inputs_are_skipped_and_stale_figures_removed(self):
        canonical = write_run(self.root, "r8", "m/8B", {"a": [1, 2, 3]})
        out = self.root / "figures"
        out.mkdir()
        (out / "mitigation.svg").write_text("<svg/>")
        printed = io.StringIO()
        with redirect_stdout(printed):
            figures.main(["--canonical", str(canonical), "--out", str(out)])
        skips = [line for line in printed.getvalue().splitlines() if line.startswith("skip")]
        self.assertEqual(len(skips), 4)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["gap_heatmap.svg", "numbers.json"])

    def test_mitigation_needs_a_baseline_with_the_same_target(self):
        canonical = self.load("r8", "m/8B", {"a": [1, 1, 1]})
        other = self.load("rx", "m/70B", {"a": [0, 0, 0]})
        with self.assertRaises(figures.Skip):
            figures.mitigation(other, [None, canonical])

    def test_run_in_progress_with_a_half_written_line(self):
        run = write_run(self.root, "r70", "m/70B", {"a": [3, 3, 3]}, finished=False)
        with (run / "events.jsonl").open("a") as f:
            f.write('{"t": 1, "run_id": "r70", "hyp')
        printed = io.StringIO()
        with redirect_stdout(printed):
            loaded = runs.load_run(run)
        self.assertEqual(list(loaded.verified), ["a"])
        self.assertIn("still in progress", printed.getvalue())


class MarkdownTest(unittest.TestCase):
    def test_headings_paragraphs_and_inline_markup(self):
        html = convert("## Method & data\n\nSome **bold**, *italic*, _also_ and [a link]"
                       "(https://e.org/?a=1&b=2).\nvote_initiative_signatures stays.")
        self.assertIn('<h2 id="method-data">Method &amp; data</h2>', html)
        self.assertIn("<strong>bold</strong>, <em>italic</em>, <em>also</em>", html)
        self.assertIn('<a href="https://e.org/?a=1&amp;b=2">a link</a>', html)
        self.assertIn("vote_initiative_signatures stays.</p>", html)

    def test_inline_code_is_literal(self):
        html = convert("Run `**not bold** <b>` now, see [`make run`](https://x.y).")
        self.assertIn("<code>**not bold** &lt;b&gt;</code>", html)
        self.assertIn('<a href="https://x.y"><code>make run</code></a>', html)

    def test_hard_line_breaks(self):
        html = convert("**Track:** 1A  \n**Team:** X")
        self.assertIn("<strong>Track:</strong> 1A<br>", html)

    def test_images_become_figures_and_rows(self):
        single = convert("![**Figure 1.** Gap, see [2]](docs/figures/gap_heatmap.svg){width=60%}")
        self.assertIn('<figure style="width: 60%"><img src="docs/figures/gap_heatmap.svg" '
                      'alt="Figure 1. Gap, see [2]">', single)
        self.assertIn("<figcaption><strong>Figure 1.</strong> Gap, see [2]</figcaption>", single)
        row = convert("![A](a.svg){width=55%}\n![B](b.png)")
        self.assertTrue(row.startswith('<div class="figrow"><figure style="flex: 0 1 55%">'))
        self.assertEqual(row.count("<figure"), 2)

    def test_tables_with_alignment(self):
        html = convert("| Finding | Rate |\n|:--|--:|\n| `a_b` | 94% |\n| c | 6% |")
        self.assertIn("<th>Finding</th><th style=\"text-align: right\">Rate</th>", html)
        self.assertIn("<td><code>a_b</code></td><td style=\"text-align: right\">94%</td>", html)
        self.assertEqual(html.count("<tr>"), 3)

    def test_lists(self):
        html = convert("- one\n- two\n  continued\n\n3. three\n4. four\n   - nested")
        self.assertIn("<ul><li>one</li><li>two continued</li></ul>", html)
        self.assertIn('<ol start="3"><li>three</li><li>four<ul><li>nested</li></ul></li></ol>',
                      html)

    def test_code_inside_a_list_item(self):
        code = '<pre><code class="language-bash">make run</code></pre>'
        tight = convert("1. Run:\n   ```bash\n   make run\n   ```\n2. Next")
        self.assertEqual(tight, f"<ol><li>Run:{code}</li><li>Next</li></ol>")
        loose = convert("1. Run:\n\n   ```bash\n   make run\n   ```\n2. Next")
        self.assertEqual(loose, tight)

    def test_fenced_code_quote_and_rule(self):
        html = convert("```bash\nmake run <x> **y**\n```\n\n> quoted *text*\n\n----")
        self.assertIn('<pre><code class="language-bash">make run &lt;x&gt; **y**</code></pre>',
                      html)
        self.assertIn("<blockquote><p>quoted <em>text</em></p></blockquote>", html)
        self.assertTrue(html.endswith("<hr>"))


class BuildTest(unittest.TestCase):
    def test_references_must_come_last(self):
        body = report.split_references("# T\n\n## Method\n\nx\n\n## References\n\n1. A\n")
        self.assertEqual(body, "# T\n\n## Method\n\nx\n")
        with self.assertRaises(SystemExit):
            report.split_references("## References\n\n1. A\n\n## Appendix\n")

    def test_numbered_references_heading(self):
        markdown = "# T\n\nx\n\n## 7. References\n\n1. A"
        self.assertEqual(report.split_references(markdown), "# T\n\nx\n")
        self.assertIn('<h2 id="references">7. References</h2>', convert(markdown))

    def test_missing_figure_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "report.md"
            (Path(tmp) / "here.svg").write_text("<svg/>")
            md.write_text("# R\n\n![Here](here.svg)\n\n![Gone](gone.svg)\n\n"
                          "![Web](https://e.org/x.png)")
            with self.assertRaises(SystemExit) as stopped:
                report.main(["--md", str(md), "--out", str(Path(tmp) / "r.pdf")])
        self.assertIn("gone.svg", str(stopped.exception))
        self.assertNotIn("here.svg", str(stopped.exception))

    def test_page_count_ignores_the_page_tree(self):
        pdf = b"<</Type /Pages /Count 2>> <</Type /Page>> <</Type/Page /Rotate 0>>"
        self.assertEqual(report.count_pages(pdf), 2)


def chrome_found():
    try:
        return bool(report.chrome())
    except SystemExit:
        return False


@unittest.skipUnless(chrome_found(), "needs Chrome or Chromium")
class PdfTest(unittest.TestCase):
    def build(self, markdown):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "report.md"
            md.write_text(markdown)
            with redirect_stdout(io.StringIO()) as printed, redirect_stderr(io.StringIO()):
                code = report.main(["--md", str(md), "--out", str(Path(tmp) / "report.pdf")])
            return code, printed.getvalue()

    def test_short_report_passes(self):
        code, printed = self.build("# Report\n\nOne page.\n\n## References\n\n1. A\n")
        self.assertEqual(code, 0)
        self.assertIn("1 without references", printed)

    def test_long_body_fails_the_page_limit(self):
        code, _ = self.build("# Report\n\n" + "A paragraph of text that fills pages.\n\n" * 600)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
