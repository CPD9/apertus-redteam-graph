import {$, LANGS, LANG_NAMES, UNCOUNTED_TAB, clip, esc, flatten, langAttr, pct, strong, sum, term, titleOf,
        walkHref} from "./text.js";
import {excerptHtml, logCap, pickEvidence} from "./evidence.js";
import {asCells, cellRates, failedAny, heatCell, range, spread} from "./heat.js";
import {controlLine, premiseEffect} from "./cards-control.js";
import {factsHtml} from "./cards-facts.js";

export {renderSubmitted} from "./cards-submitted.js";

// renderFindings runs again on every filter change, without the run; it words its empty state by
// what the last renderFacts saw.
let progress = {planned: 0, finished: 0};

// Where the log cuts long answers, worked out once per run.
const caps = new WeakMap();
function capOf(attacksById) {
  if (!caps.has(attacksById)) caps.set(attacksById, logCap(attacksById));
  return caps.get(attacksById);
}

// Which submitted finding names this hypothesis. Only the run the submission rests on can say that a
// reproduced hypothesis was left out; leftOutOf is then how many findings were submitted.
function submission(id, run) {
  const submitted = run.submitted || [], cited = submitted.filter(e => e.run_id && e.run_id === run.runId);
  if (!cited.length) return {};
  const entry = cited.find(e => (e.variations || []).some(v => v.id === id));
  return entry ? {submittedIn: entry} : {leftOutOf: submitted.length};
}

// The numbers come from the verifier results, which the server recounts by the published rule. Older
// finding files counted every flagged answer, so their own numbers are only a fallback. The copies of
// the recorded runs in data/runs/ have no finding files: their cards come from the events alone.
export function cardModel(f, run) {
  const id = f.hypothesis, p = f.model?.parameters || {}, hyp = run.hypotheses[id] || {};
  const control = run.control[id], ver = run.ver[id], seeds = p.harness_seeds || run.seeds;
  const cells = ver?.cells || asCells(p.harness_reproduction_rates || {});
  const ci = ver?.ci95 || p.harness_overall_ci95;
  const attack = run.attacks[id], evidence = pickEvidence(attack);
  // Canned answers are short and alike, so they never show where the log cuts.
  if (evidence) evidence.cut = !run.mock && evidence.answer.length >= capOf(run.attacks);
  return {
    id, f, p, hyp, control, cells, ci, seeds, evidence,
    runId: run.runId, mock: Boolean(run.mock),
    title: titleOf(id, run.hypotheses),
    domain: hyp.domain || "",
    overall: ver?.overall ?? p.harness_overall_rate,
    gap: spread(cellRates(cells)),
    failed: Object.values(cells).every(c => c.n) ? sum(Object.values(cells).map(c => c.k)) : null,
    answers: sum(Object.values(cells).map(c => c.n ?? seeds.length)),
    uncounted: run.uncounted.has(id),
    effect: control ? premiseEffect(control, ci, run.minRate) : null,
    strategy: attack?.strategy,
    asked: Object.keys(attack?.answers || {}).length,
    ...submission(id, run),
  };
}

export const byStrength = (a, b) =>
  Boolean(b.evidence?.quoted) - Boolean(a.evidence?.quoted) || b.overall - a.overall || b.gap - a.gap;

function checkNote(x) {
  const ev = x.evidence, answer = x.mock ? "the canned answer" : "Apertus' answer";
  if (ev?.quoted) return "";
  if (!ev) return '<p class="check"><b>Needs a human check:</b> the run log has no judge record for it.</p>';
  const quoted = flatten(ev.verdict.evidence);
  const why = ev.quote ? "the judge flagged this answer but rated it severity 0"
    : quoted ? `the judge's quote, “${esc(clip(quoted, 160))}”, does not appear in ${answer}`
    : `the judge gave no quote from ${answer}`;
  return `<p class="check"><b>Needs a human check:</b> ${why}. ` +
         `Its reasoning: “${esc(clip(flatten(ev.verdict.reason), 200))}”</p>`;
}

// The example comes from the attack step, which only finds a failure; the counted answers are the
// verifier's reruns, which the log keeps as flags without text.
function said(x) {
  const ev = x.evidence;
  if (!ev) return "";
  const lang = esc(LANG_NAMES[ev.lang] || ev.lang);
  const english = ev.lang !== "en" && ev.english
    ? `<p class="english">In English: <q>${esc(flatten(ev.english))}</q></p>` : "";
  const key = ev.quote ? '<p class="mkey"><mark>Underlined</mark>: the passage the judge quoted.</p>' : "";
  return `<section class="said"><h4>${x.mock ? "Canned test answer" : `What Apertus said, in ${lang}`}</h4>
    <p class="from">Example from the ${term("attack-step", "attack step")} (not one of the ${x.answers}
      counted answers)</p>
    <p class="asked">Asked: <q ${langAttr(ev.lang)}>${esc(flatten(ev.prompt))}</q></p>${english}
    <p class="answer" ${langAttr(ev.lang)}>“${excerptHtml(ev.answer, ev.quote)}”</p>${key}</section>`;
}

function sources(urls) {
  const host = u => new URL(u).hostname.replace(/^www\./, "");
  const links = (urls || []).filter(u => /^https?:\/\//.test(u))
    .map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`);
  return links.length ? `<p class="sources">Source: ${links.join(", ")}</p>` : "";
}

// Every claim the judge settled, so a correct sentence on a flagged answer shows as correct.
function claimsHtml(ev) {
  const claims = (ev?.verdict.claims || []).filter(c => ["supported", "contradicted"].includes(c.verdict));
  return claims.length ? `<ul class="claims">` + claims.map(c =>
    `<li><span class="cv ${c.verdict}">${c.verdict}</span> ${esc(c.claim)}</li>`).join("") + "</ul>" : "";
}

function exchangeHtml(ev) {
  if (!ev) return "";
  const lang = langAttr(ev.lang), name = esc(LANG_NAMES[ev.lang] || ev.lang);
  return `<div class="exchange"><p class="label">Full exchange in ${name}` +
    `${ev.cut ? ", as far as the log keeps it" : ""}</p><p ${lang}>“${esc(ev.prompt)}”</p>` +
    `<pre ${lang} tabindex="0" aria-label="${ev.cut ? "Logged answer" : "Full answer"}">` +
    `${strong(esc(ev.answer))}${ev.cut ? "…" : ""}</pre>` +
    (ev.cut ? '<p class="cutnote">The log keeps only the start of a long answer.</p>' : "") + "</div>";
}

function details(x) {
  const s = x.f.issue_summary || {}, ci = x.ci, ev = x.evidence, cells = Object.values(x.cells);
  const langs = LANGS.filter(l => x.cells[l]?.n), withCi = langs.some(l => x.cells[l].ci95);
  const perLang = langs.map(l => `${l} ${Number(x.cells[l].k)} of ${Number(x.cells[l].n)}` +
                                 (x.cells[l].ci95 ? ` (${range(x.cells[l].ci95)})` : ""));
  const temperature = x.p.temperature == null ? "" : ` at temperature ${x.p.temperature}`;
  const overall = `${esc(pct(x.overall))} of ${Number(x.answers)} answers` +
                  (ci ? `, ${term("ci", "95% CI")} ${esc(range(ci))}` : "");
  const rows = [
    ["Why it matters", esc(x.hyp.harm)],
    ["Hypothesis", esc(x.hyp.hypothesis)],
    ["Hypothesis id", `<code>${esc(x.id)}</code>`],
    ["Judge's reasoning", esc(ev?.verdict.reason)],
    ["Claims the judge checked", claimsHtml(ev)],
    [withCi ? "Failed per language, with 95% CI" : "Failed per language", esc(perLang.join(" · "))],
    ["Overall", overall],
    ["Seeds", esc(x.seeds.length ? x.seeds.join(", ") + temperature : "")],
    ["Highest severity the judge gave one answer (0–10 scale)", esc(s.self_assessed_severity)],
    ["Breadth", cells.length
      ? `Fails at least once in ${cells.filter(failedAny).length} of ${cells.length} languages` : ""],
    ["Attack strategy", esc(x.strategy?.replace(/_/g, " "))],
  ].filter(([, v]) => v);
  return `<details><summary>Details<span class="sr"> for ${esc(x.title)}</span></summary>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>${exchangeHtml(ev)}</details>`;
}

// The tags explain themselves in a tip; they take the focus so the keyboard reaches it too.
function badges(x) {
  const entry = x.submittedIn;
  return [
    x.domain && `<span class="chip">${esc(x.domain.replace(/_/g, " "))}</span>`,
    x.uncounted && UNCOUNTED_TAB,
    entry && `<span class="subchip" tabindex="0" data-tip="One of the variations of this submitted ` +
             `finding.">Submitted in: ${esc(entry.issue_title)}</span>`,
    x.leftOutOf && `<span class="tag quiet" tabindex="0" data-tip="Reproduced here but left out of the ` +
                   `${x.leftOutOf} submitted findings; their notes say why.">not submitted</span>`,
  ].filter(Boolean).join(" ");
}

function card(x) {
  const strip = LANGS.filter(l => l in x.cells).map(l => heatCell(x.cells[l], l, {big: true})).join("");
  const truth = esc(x.hyp.reference || x.f.issue_summary?.desired_behavior);
  const failed = (x.failed != null ? `${x.failed} of ${x.answers}` : `of ${x.answers}`) +
                 " <span>answers failed</span>";
  const walk = "How this was tested, step by step";
  return `<article class="card fcard" id="f-${esc(x.id)}">
    <div class="fhead">
      <div>${badges(x)}<h3>${esc(x.title)}</h3></div>
      <div class="overall"><b>${pct(x.overall)}</b><small>${failed}</small></div>
    </div>
    <div class="strip" role="group" aria-label="Share of answers that failed, per language">${strip}</div>
    ${checkNote(x)}
    ${controlLine(x)}
    <div class="pair">${said(x)}
      <section class="truth"><h4>What is correct</h4>
        <p>${truth}</p>${sources(x.hyp.sources)}</section>
    </div>
    <a class="walk" href="${walkHref(x.runId, x.id)}" data-explain="${esc(x.id)}">${walk} ›</a>
    ${details(x)}
  </article>`;
}

export function renderChips(cards, view) {
  const counts = {};
  cards.forEach(x => counts[x.domain] = (counts[x.domain] || 0) + 1);
  // A hypothesis without a domain (older runs) is listed under All only.
  const named = Object.entries(counts).filter(([d]) => d).sort();
  const chips = [["", "All", cards.length], ...named.map(([d, n]) => [d, d.replace(/_/g, " "), n])];
  const chip = ([d, label, n]) => {
    const on = d === view.domain;
    return `<button class="${on ? "on" : ""}" aria-pressed="${on}" data-domain="${esc(d)}">` +
           `${esc(label)} <span>${Number(n)}</span></button>`;
  };
  $("#domains").innerHTML = cards.length ? chips.map(chip).join("") : "";
}

export function renderFindings(cards, view) {
  const open = [...document.querySelectorAll("#findings details[open]")].map(d => d.closest("article").id);
  const q = view.query.trim().toLowerCase();
  const text = x => [x.title, x.id, x.domain, x.hyp.hypothesis, x.hyp.reference].join(" ").toLowerCase();
  const shown = cards.filter(x => (!view.domain || x.domain === view.domain) && (!q || text(x).includes(q)));
  const done = progress.planned && progress.finished >= progress.planned;
  const empty = cards.length ? "No reproduced hypothesis matches this filter."
                             : done ? "Nothing reproduced in this run." : "Nothing reproduced yet.";
  $("#findings").innerHTML = shown.length ? shown.map(card).join("") : `<p class="empty">${empty}</p>`;
  open.forEach(id => document.getElementById(id)?.querySelector("details")?.setAttribute("open", ""));
}

// run: planned holds the ids of the run's hypotheses, finished how many of them have ended.
export function renderFacts(cards, run) {
  progress = {planned: run.planned.length, finished: run.finished};
  $("#facts").innerHTML = factsHtml(cards, run);
}
