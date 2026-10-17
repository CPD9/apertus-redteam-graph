import {$, LANGS, LANG_NAMES, UNCOUNTED, clip, esc, flatten, pct, titleOf} from "./text.js";
import {excerptHtml, pickEvidence} from "./evidence.js";
import {asCells, cellRates, heatCell, spread} from "./heat.js";

const PLACEHOLDER = /\[[^\]]+\]/;  // a neutral question still holding e.g. "[Datum einfügen]"
const EFFECTS = {
  premise: "Clearly worse with the false premise",
  neutral: "Worse when asked neutrally",
  same: "No clear difference from a neutral question",
};

// Compares the neutral control with the false-premise answers by their 95% intervals, not their
// rates: with 18 answers each, 17% against 39% is not a difference.
function premiseEffect(control, premiseCi) {
  if (PLACEHOLDER.test(control.neutral_question)) return "unusable";
  const [lo, hi] = control.neutral_ci95 || [control.neutral_rate, control.neutral_rate];
  const [premiseLo, premiseHi] = premiseCi || [control.premise_rate, control.premise_rate];
  return hi < premiseLo ? "premise" : lo > premiseHi ? "neutral" : "same";
}

// The numbers come from the verifier results, which the server recounts by the published rule. Older
// finding files counted every flagged answer, so their own numbers are only a fallback. The copies of
// the recorded runs in data/runs/ have no finding files: their cards come from the events alone.
export function cardModel(f, run) {
  const id = f.hypothesis, p = f.model?.parameters || {}, hyp = run.hypotheses[id] || {};
  const control = run.control[id], ver = run.ver[id], seeds = p.harness_seeds || run.seeds;
  const cells = ver?.cells || asCells(p.harness_reproduction_rates || {});
  const ci = ver?.ci95 || p.harness_overall_ci95;
  return {
    id, f, p, hyp, control, cells, ci, seeds,
    title: titleOf(id, run.hypotheses),
    domain: hyp.domain || "",
    overall: ver?.overall ?? p.harness_overall_rate,
    gap: spread(cellRates(cells)),
    answers: Object.values(cells).reduce((sum, c) => sum + (c.n ?? seeds.length), 0),
    uncounted: run.uncounted.has(id),
    effect: control ? premiseEffect(control, ci) : null,
    strategy: run.attacks[id]?.strategy,
    evidence: pickEvidence(run.attacks[id]),
  };
}

export const byStrength = (a, b) =>
  Boolean(b.evidence?.quoted) - Boolean(a.evidence?.quoted) || b.overall - a.overall || b.gap - a.gap;

function controlLine(x) {
  if (!x.control) return "";
  const c = x.control, asked = `“${esc(clip(flatten(c.neutral_question), 90))}”`;
  if (x.effect === "unusable") {
    return `<p class="ctl"><b>Neutral control unusable:</b> its question still holds a placeholder, ` +
           `${asked}.</p>`;
  }
  return `<p class="ctl"><b>${EFFECTS[x.effect]}.</b> Asked neutrally (${asked}), ` +
         `${pct(c.neutral_rate)} of its answers failed; with the false premise, ${pct(x.overall)}.</p>`;
}

function checkNote(ev) {
  if (ev?.quoted) return "";
  if (!ev) return '<p class="check"><b>Needs a human check:</b> the run log has no judge record for it.</p>';
  const why = ev.quote ? "the judge flagged this answer but rated it severity 0"
                       : "the judge's quote does not appear in Apertus' answer";
  return `<p class="check"><b>Needs a human check:</b> ${why}. ` +
         `Its reasoning: “${esc(clip(flatten(ev.verdict.reason), 200))}”</p>`;
}

function said(ev) {
  if (!ev) return "";
  return `<section class="said"><h4>What Apertus said <span>${esc(LANG_NAMES[ev.lang] || ev.lang)}</span></h4>
    <p class="asked">Asked: “${esc(clip(flatten(ev.prompt), 110))}”</p>
    <p>“${excerptHtml(ev.answer, ev.quote)}”</p></section>`;
}

function sources(urls) {
  const host = u => new URL(u).hostname.replace(/^www\./, "");
  const links = (urls || []).filter(u => /^https?:\/\//.test(u))
    .map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`);
  return links.length ? `<p class="sources">Source: ${links.join(", ")}</p>` : "";
}

function details(x) {
  const s = x.f.issue_summary || {}, ci = x.ci, ev = x.evidence;
  const marked = (ev?.verdict.claims || []).filter(c => c.verdict === "contradicted").map(c => c.claim);
  const perLang = LANGS.filter(l => x.cells[l]?.n).map(l => `${l} ${x.cells[l].k} of ${x.cells[l].n}`);
  const temperature = x.p.temperature == null ? "" : ` at temperature ${x.p.temperature}`;
  const rows = [
    ["Why it matters", x.hyp.harm],
    ["Hypothesis", x.hyp.hypothesis],
    ["Judge's reasoning", ev?.verdict.reason],
    ["Claims it marked wrong", marked.join(" · ")],
    ["Failed per language", perLang.join(" · ")],
    ["Overall", `${pct(x.overall)} of ${x.answers} answers` + (ci ? `, 95% CI ${pct(ci[0])}–${pct(ci[1])}` : "")],
    ["Seeds", x.seeds.length ? x.seeds.join(", ") + temperature : ""],
    ["Judge's top severity", s.self_assessed_severity && `${s.self_assessed_severity} of 10`],
    ["Breadth", [s.self_assessed_breadth, s.self_assessed_breadth_justification].filter(Boolean).join(": ")],
    ["Attack strategy", x.strategy?.replace(/_/g, " ")],
    ["Neutral question", x.control?.neutral_question],
  ].filter(([, v]) => v);
  const exchange = ev ? `<div class="exchange"><p>Full exchange in ${esc(LANG_NAMES[ev.lang] || ev.lang)}: ` +
                        `“${esc(ev.prompt)}”</p><pre>${esc(ev.answer)}</pre></div>` : "";
  return `<details><summary>Details</summary>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>${exchange}</details>`;
}

function card(x) {
  const chip = x.domain ? `<span class="chip">${esc(x.domain.replace(/_/g, " "))}</span>` : "";
  const strip = LANGS.filter(l => l in x.cells).map(l => heatCell(x.cells[l], l, true)).join("");
  const truth = esc(x.hyp.reference || x.f.issue_summary?.desired_behavior);
  return `<article class="card fcard" id="f-${esc(x.id)}">
    <div class="fhead">
      <div>${chip}${x.uncounted ? UNCOUNTED : ""}<h3 title="${esc(x.id)}">${esc(x.title)}</h3></div>
      <div class="overall"><b>${pct(x.overall)}</b><small>of ${x.answers} answers failed</small></div>
    </div>
    <div class="strip">${strip}</div>
    ${checkNote(x.evidence)}
    ${controlLine(x)}
    <div class="pair">${said(x.evidence)}
      <section class="truth"><h4>What is correct</h4>
        <p>${truth}</p>${sources(x.hyp.sources)}</section>
    </div>
    ${details(x)}
  </article>`;
}

export function renderChips(cards, view) {
  const counts = {};
  cards.forEach(x => counts[x.domain] = (counts[x.domain] || 0) + 1);
  // A hypothesis without a domain (older runs) is listed under All only.
  const named = Object.entries(counts).filter(([d]) => d).sort();
  const chips = [["", "All", cards.length], ...named.map(([d, n]) => [d, d.replace(/_/g, " "), n])];
  const chip = ([d, label, n]) => `<button class="${d === view.domain ? "on" : ""}" data-domain="${esc(d)}">` +
                                  `${esc(label)}<span>${n}</span></button>`;
  $("#domains").innerHTML = cards.length ? chips.map(chip).join("") : "";
}

export function renderFindings(cards, view) {
  const open = [...document.querySelectorAll("#findings details[open]")].map(d => d.closest("article").id);
  const q = view.query.trim().toLowerCase();
  const text = x => [x.title, x.id, x.domain, x.hyp.hypothesis, x.hyp.reference].join(" ").toLowerCase();
  const shown = cards.filter(x => (!view.domain || x.domain === view.domain) && (!q || text(x).includes(q)));
  const empty = cards.length ? "No finding matches this filter." : "No findings in this run yet.";
  $("#findings").innerHTML = shown.length ? shown.map(card).join("") : `<p class="empty">${empty}</p>`;
  open.forEach(id => document.getElementById(id)?.querySelector("details")?.setAttribute("open", ""));
}

export function renderFacts(cards, {planned, finished, rejudge}) {
  const total = cards.length, quoted = cards.filter(x => x.evidence?.quoted).length;
  const parts = [finished < planned
    ? `<b>${total}</b> findings so far · ${finished} of ${planned} hypotheses tested`
    : `<b>${total}</b> findings from ${planned} hypotheses`];
  if (total) {
    const unchecked = total - quoted;
    parts.push(`<b>${quoted}</b> backed by a quote from Apertus' answer, ` +
               `${unchecked} ${unchecked === 1 ? "needs" : "need"} a human check`);
  }
  const controlled = cards.filter(x => x.effect && x.effect !== "unusable");
  const worse = controlled.filter(x => x.effect === "premise").length;
  if (controlled.length) {
    parts.push(`the false premise clearly makes it worse in <b>${worse}</b> of ${controlled.length} ` +
               "checked against a neutral question");
  }
  if (rejudge?.n) {
    const kappa = rejudge.kappa == null ? "n/a" : rejudge.kappa.toFixed(2);
    parts.push(`a second judge agrees on <b>${pct(rejudge.raw_agreement)}</b> of ${rejudge.n} answers ` +
               `(κ ${kappa})`);
  }
  $("#facts").innerHTML = parts.join(" · ");
}
