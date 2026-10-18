"""Building the report from a plain checkout: the scripts need no PYTHONPATH, Markdown becomes
HTML, and the PDF keeps to the page limit with the references left off the count."""
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK / "scripts"))

import build_report as report  # noqa: E402
from report_markdown import convert  # noqa: E402


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


def python(*args):
    """Python with PYTHONPATH and the user's site-packages ignored, run outside the checkout."""
    return subprocess.run([sys.executable, "-E", "-s", *args], cwd=TRACK.parent.parent,
                          capture_output=True, text=True, timeout=60)


class EntryPointTest(unittest.TestCase):
    def test_report_figures_runs_without_pythonpath(self):
        done = python(str(TRACK / "scripts" / "report_figures.py"), "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--bank2", done.stdout)

    def test_importing_a_library_script_leaves_sys_path_alone(self):
        code = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; before = list(sys.path); "
                "import report_speech; assert sys.path == before, sys.path")
        done = python("-c", code, str(TRACK / "scripts"), str(TRACK / "src"))
        self.assertEqual(done.returncode, 0, done.stderr)


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
