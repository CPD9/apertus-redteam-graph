// The overview, the tab that opens first: the submission in one sentence, the five submitted findings
// with their intervals drawn to scale, and how each audit came out. The submission's part is the same
// for every run; the two lines on how a run works describe the run on screen.
import {$, esc, pct, short, sum, term, titleOf, walkHref} from "./text.js";
import {introHtml} from "./explain.js";
import {band} from "./cards-facts.js";

// The report's table numbers the findings in this order; its abstract, and the sentence at the top,
// take the numbers of the first.
const REPORT_ORDER = ["civic_sycophancy", "private_person_fabrication", "safety_knowledge_gaps",
                      "pension_rules", "speech_dialect_hallucination"];

const share = x => `${Number(x.k)} of ${Number(x.n)}`;
const stem = file => file.replace(/\.json$/, "");
const points = d => Math.round(d * 100);
const signed = d => (points(d) > 0 ? "+" : "") + String(points(d)).replace("-", "−");
const thousands = n => Number(n).toLocaleString("en");
const plural = (n, word) => `${Number(n)} ${word}${n === 1 ? "" : "s"}`;
const pValue = p => p < 0.001 ? "below 0.001" : String(Number(p.toPrecision(1)));
const holm = p => `Holm p ${pValue(p)}` + (p < 0.05 ? "" : ", not significant after correction");
const place = e => (REPORT_ORDER.indexOf(stem(e.file)) + 1) || REPORT_ORDER.length + 1;

function headline(submitted) {
  const lead = submitted.find(e => stem(e.file) === REPORT_ORDER[0]), c = lead?.control;
  if (!c) return "Same question, six Swiss languages, different truths.";
  return `On Swiss voting rules, history and literature, ${esc(short(lead.model))} agreed with a false ` +
    `claim in <u>${pct(c.premise.rate)}</u> of answers (${share(c.premise)}); asked neutrally, it got ` +
    `<u>${pct(c.neutral.rate)}</u> wrong (${share(c.neutral)}).`;
}

// The rows of one finding: what was counted, with its interval. The speech clips share speakers and
// sentences, so only the interval that resamples both is drawn for them.
function rowsOf(e) {
  const all = e.unrelated?.all;
  if (all) {
    return [[`${short(e.model)}, audio in`, {...all.apertus, ci95: all.apertus.cluster_ci95}],
            ["Swiss German Whisper", {...all.whisper, ci95: all.whisper.cluster_ci95}]];
  }
  const vars = e.variations || [];
  const claim = e.control?.premise ||
    {k: sum(vars.map(v => v.k)), n: sum(vars.map(v => v.n)), rate: e.overall_rate, ci95: e.overall_ci95};
  return [[`${short(e.model)}, with the false claim`, claim],
          e.control && [`${short(e.model)}, asked neutrally`, e.control.neutral],
          e.replication && [`${short(e.replication.model)}, with the false claim`, e.replication]]
    .filter(Boolean);
}

function bar([label, x], i) {
  const [lo, hi] = x.ci95 || [x.rate, x.rate];
  const ci = x.ci95 ? `, 95% CI ${pct(lo)}–${pct(hi)}` : "";
  return `<div class="orow${i ? " other" : ""}"><span class="olabel">${esc(label)}</span>
    <span class="otrack" aria-hidden="true"><i class="ofill" style="width:${pct(x.rate)}"></i>
      <i class="ociw" style="left:${pct(lo)};width:${pct(hi - lo)}"></i></span>
    <span class="oval"><b>${pct(x.rate)}</b> ${share(x)}${ci}</span></div>`;
}

function reading(e) {
  const d = e.control?.premise_minus_neutral_ci95, r = e.replication;
  const parts = [];
  if (d) {
    const span = `${signed(d[0])} to ${signed(d[1])} points (95% CI)`;
    parts.push(d[0] > 0 ? `<b>Gives in:</b> the false claim adds ${span}.`
      : d[1] < 0 ? `<b>Worse asked neutrally:</b> ${span}.`
      : `<b>Wrong either way:</b> no clear difference asked neutrally, ${span}.`);
  }
  if (r) {
    parts.push(`On ${esc(short(r.model))}, ${(r.variations_reproduced || []).length} of ` +
               `${plural((r.variations_measured || []).length, "variation")} reproduced.`);
  }
  if (e.unrelated) parts.push("Intervals resample speakers and sentences; each dialect is one speaker.");
  return `<p class="oread">${parts.join(" ")}</p>`;
}

// The card on the Findings tab, and the walkthrough of its first variation in the run it cites.
function links(e, hypotheses) {
  const graphRun = !e.unrelated && e.run_id;
  const card = `?tab=findings${graphRun ? "&run=" + encodeURIComponent(e.run_id) : ""}` +
               `#s-${encodeURIComponent(stem(e.file))}`;
  const first = graphRun && e.variations?.[0]?.id;
  const walk = first ? ` · <a href="${walkHref(e.run_id, first)}">Step by step: ` +
                       `${esc(titleOf(first, hypotheses))}</a>` : "";
  return `<p class="olinks"><a href="${esc(card)}">Its card: overview, variations and how to ` +
         `reproduce</a>${walk}</p>`;
}

function findingHtml(e, i, hypotheses) {
  const count = e.unrelated ? plural(e.unrelated.all?.apertus.n, "clip")
                            : plural(e.variations?.length || 0, "variation");
  return `<article class="ofind">
    <span class="orank">${i + 1}</span>
    <div class="obody">
      <h3>${esc(e.issue_title)}</h3>
      <p class="ometa">findings/${esc(e.file)} · ${count} ·
        team's rubric: severity ${esc(e.severity)}, breadth ${esc(e.breadth)}</p>
      <div class="obars">${rowsOf(e).map(bar).join("")}</div>
      ${reading(e)}${links(e, hypotheses)}
    </div></article>`;
}

const counted = x => share({k: x.counted, n: x.n});

const CHECKS = {
  recount: c => ["Independent recount", `<b>${c.differ} of ${thousands(c.checked)}</b> values in the ` +
    "findings, figures and report differ when recomputed from the recorded runs without the harness's " +
    "counting code."],
  judge: c => ["Second judge", "A second, independently worded Apertus 70B judge agrees with the first " +
    "on " + c.runs.map(r => `<b>${pct(r.raw_agreement)} of ${Number(r.n)}</b> answers of the ${esc(r.run)} ` +
      `run (${term("kappa", `κ ${r.kappa.toFixed(2)}`)}, ${band(r.kappa)} agreement)`).join(" and ") +
    ". It gives only a flag, so the two are compared before the severity rule."],
  scorer: c => ["Numeric scorer", `Where a script with no model reads the number (${c.scorable} of ` +
    `${c.hypotheses} hypotheses on ${esc(short(c.model))}), the judge ${term("counts", "counted as failed")} ` +
    `<b>${counted(c.false_only)}</b> answers stating only a wrong value and ${counted(c.true_only)} ` +
    "stating only the right one. The script ignores negation, so not all of the other " +
    `${c.false_only.n - c.false_only.counted} are misses by the judge.`],
  stats: c => ["Statistics", "Counting the hypotheses where the two differ, Romansh failed more often " +
    "than English in " + c.romansh_vs_english.map(r => `<b>${share({k: r.higher, n: r.higher + r.lower})}` +
      `</b> on ${esc(short(r.model))} (sign test, ${holm(r.p_holm)})`).join(" and ") +
    "; every test was chosen after the runs were read."],
  prompts: c => ["Prompt language", `A word list with no model puts <b>${share(
    {k: c.word_list, n: c.prompts})}</b> prompts in another language than intended and cannot tell for ` +
    `${c.uncertain}. The lists were tuned on these same prompts, so this is optimistic; a heuristic, ` +
    "not a native speaker's reading."],
  references: c => ["Reference check", "Each source was fetched and compared with the hypothesis's " +
    `reference; for ${c.uncited} of ${c.hypotheses} the bank cites none and the check read sources the ` +
    `team chose. <b>${share({k: c.verdicts.supported || 0, n: c.hypotheses})}</b> hypotheses supported` +
    Object.entries(c.verdicts).filter(([v]) => v !== "supported").map(([v, n]) => `, ${n} ${esc(v)}`).join("") +
    `; ${c.unreachable} of ${c.sources} sources unreachable. Automated, not a human review.`],
};

function checksHtml(checks, humanLabels) {
  const items = checks.filter(c => CHECKS[c.check]).map(c => {
    const [name, line] = CHECKS[c.check](c);
    return `<li><h3>${name}</h3><p>${line}</p><code>${esc(c.file)}</code></li>`;
  }).join("");
  const people = humanLabels == null ? "" : ` People have checked ${Number(humanLabels)} of its verdicts ` +
    `so far on <a href="review.html">the review page</a>.`;
  return `<section class="oknow" aria-labelledby="oknowHead">
    <h2 id="oknowHead" class="sechead">How we know</h2><ul>${items}</ul>
    <p class="onote">Every finding above rests on one model judge, Apertus 70B.${people}</p></section>`;
}

// facts: the languages, seeds and judge of the run shown, for the two lines on how a run works.
export function renderOverview(s, facts) {
  const submitted = [...(s.submitted || [])].sort((a, b) => place(a) - place(b));
  $("#overview").innerHTML = `<p class="okicker">Same question, six Swiss languages, different truths</p>
    <h2 class="ohead">${headline(submitted)}</h2>
    <div class="ohow">${introHtml(facts)}</div>
    <section aria-labelledby="ofindHead"><h2 id="ofindHead" class="sechead">The ${submitted.length} submitted
      findings, numbered as in the report</h2>
      <p class="oaxis">Bars run from 0 to 100% of answers; the line across each is its 95% interval.</p>
      ${submitted.map((e, i) => findingHtml(e, i, s.hypotheses)).join("")}</section>
    ${checksHtml(s.checks || [], s.human_labels)}`;
}
