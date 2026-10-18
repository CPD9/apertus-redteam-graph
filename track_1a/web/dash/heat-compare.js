import {LANGS, LANG_NAMES, esc, pct, titleOf} from "./text.js";
import {pooled, pooledAll, verified} from "./heat-data.js";
import {heatCell} from "./heat-cell.js";

// Two runs side by side over the hypotheses both took to the verifier, and what each reproduced,
// verified or planned that the other did not. Another run's state is megabytes, so it is fetched
// only when picked, once.
const fetched = new Map();
let reportRuns = null, here = null, drawn = "";

const planOf = events => events.find(e => e.node === "graph" && e.status === "start")?.data?.hypotheses || [];

async function loadRuns() {
  if (reportRuns) return reportRuns;
  const list = await fetch("/api/runs").then(r => r.ok ? r.json() : []).catch(() => []);
  reportRuns = list.filter(r => r.report).sort((a, b) => a.id.localeCompare(b.id));
  return reportRuns;
}

async function stateOf(id) {
  if (!fetched.has(id)) {
    const s = await fetch(`/api/state?run=${encodeURIComponent(id)}`).then(r => r.ok ? r.json() : null)
      .catch(() => null);
    if (!s?.run_id) return null;
    fetched.set(id, s);
  }
  return fetched.get(id);
}

function averageRow(name, rows) {
  const means = pooled(rows), all = pooledAll(rows);
  return `<div class="hrow" role="row"><span class="hname" role="rowheader">${esc(name)}</span>` +
    LANGS.map(l => heatCell(means[l], l, {role: "cell"})).join("") +
    `<span class="hgap" role="cell">${all ? `${pct(all.rate)}<small aria-hidden="true">${all.k}<wbr>/${all.n}` +
      `</small><span class="sr">, ${all.k} of ${all.n} answers failed</span>` : "–"}</span></div>`;
}

function titles(ids, hypotheses) {
  return ids.length ? ids.map(id => esc(titleOf(id, hypotheses))).join(", ") : "none";
}

function table(shared, theirs, thisName, otherName) {
  if (!shared.length) return "<p>No hypothesis reached the verifier in both runs.</p>";
  const head = `<div class="hrow hhead" role="row"><span class="hname" role="columnheader">Run</span>` +
    LANGS.map(l => `<span role="columnheader"><span aria-hidden="true">${l}</span>` +
                   `<span class="sr">${LANG_NAMES[l]}</span></span>`).join("") +
    `<span class="hgap" role="columnheader">All</span></div>`;
  return `<p>Over the ${shared.length} hypotheses both runs took to the verifier, answers pooled per language:</p>
    <div class="heat" role="table" aria-label="Share of answers that failed in each run, per language">
      ${head}${averageRow(thisName, shared)}${averageRow(otherName, shared.map(r => ({v: theirs[r.id]})))}</div>
    <p class="heatnote">No intervals here: the server computes them over each run's whole set of
      hypotheses, not over the shared ones.</p>`;
}

// Each list runs over the whole run, not only the shared hypotheses: one reproduced here may not
// have reached the other run's verifier, which the next lists say.
function compareHtml(s, otherName) {
  const {rows, cards, run} = here;
  const theirs = verified(s.events), hypotheses = {...s.hypotheses, ...run.hypotheses};
  const thisName = run.meta?.name || run.runId, mineName = esc(thisName), theirName = esc(otherName);
  const ours = new Set(rows.map(r => r.id)), kept = new Set(s.findings.map(f => f.hypothesis));
  const mine = run.planned || [], their = planOf(s.events);
  const lists = [
    [`Reproduced only in ${mineName}`, [...cards.keys()].filter(id => !kept.has(id))],
    [`Reproduced only in ${theirName}`, [...kept].filter(id => !cards.has(id))],
    [`Reached the verifier only in ${mineName}`, [...ours].filter(id => !theirs[id])],
    [`Reached the verifier only in ${theirName}`, Object.keys(theirs).filter(id => !ours.has(id))],
    [`Planned only in ${mineName}`, mine.filter(id => !their.includes(id))],
    [`Planned only in ${theirName}`, their.filter(id => !mine.includes(id))],
  ];
  const both = [...cards.keys()].filter(id => kept.has(id)).length;
  return table(rows.filter(r => theirs[r.id]), theirs, thisName, otherName) +
    `<ul class="cmp"><li>Reproduced in both: ${both}.</li>` +
    lists.map(([what, ids]) => `<li>${what} (${ids.length}): ${titles(ids, hypotheses)}.</li>`).join("") +
    "</ul>";
}

// A live run redraws the comparison after every finished hypothesis. Only a pick is announced, in
// one sentence; the comparison itself is not a live region, or it would be read out again each time.
async function draw(box, picked = false) {
  const pick = box.querySelector("select"), out = box.querySelector(".cmpout"), id = pick.value;
  const status = box.querySelector(".cmpsay");
  if (!id || !here) {
    out.innerHTML = drawn = "";
    return;
  }
  if (!fetched.has(id)) {
    out.innerHTML = '<p class="heatnote">Loading that run…</p>';
    drawn = "";
  }
  const s = await stateOf(id);
  if (pick.value !== id) return;  // the reader picked again while this one loaded
  const name = reportRuns.find(r => r.id === id)?.name || id;
  const html = s ? compareHtml(s, name) : '<p class="heatnote">Could not load that run.</p>';
  if (html !== drawn) out.innerHTML = drawn = html;
  if (picked) status.textContent = s ? `Compared with ${name}, below.` : "Could not load that run.";
}

async function fillOptions(box) {
  const pick = box.querySelector("select"), was = pick.value;
  const others = (await loadRuns()).filter(r => r.id !== here?.run.runId);
  pick.innerHTML = '<option value="">Choose a run</option>' +
    others.map(r => `<option value="${esc(r.id)}">${esc(r.name || r.id)}</option>`).join("");
  pick.value = others.some(r => r.id === was) ? was : "";
  box.hidden = !others.length;
}

// context: the rows of the table above, the reproduced cards and the run model. The list of runs to
// pick from changes only with the run on screen; rebuilding it would close a picker in use. A run
// without rows hides the box, and the next one with rows fills it again.
export async function renderCompare(box, context) {
  const newRun = here?.run.runId !== context.run.runId;
  here = context;
  if (!box.querySelector("select")) {
    box.innerHTML = `<h3>Compare with another run</h3>
      <p class="heatnote">Runs plan different hypotheses; the table compares only the ones both took to
        the verifier.</p>
      <p class="cmppick"><label for="comparePick">Compare with</label>
        <select id="comparePick"></select></p>
      <p class="cmpsay sr" role="status"></p>
      <div class="cmpout"></div>`;
    box.querySelector("select").onchange = () => draw(box, true);
  }
  if (newRun || box.hidden) await fillOptions(box);
  draw(box);
}
