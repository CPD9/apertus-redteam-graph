import {$, LANGS, LANG_NAMES, STATUS_TIPS, UNCOUNTED, esc, pct, titleOf} from "./text.js";

const STEPS = ["0%", "1–20%", "21–40%", "41–60%", "61–80%", "81–100%"];

export const spread = values => values.length ? Math.max(...values) - Math.min(...values) : 0;
export const cellRates = cells => Object.values(cells).map(c => c.rate);
export const asCells = rates => Object.fromEntries(Object.entries(rates).map(([lang, rate]) => [lang, {rate}]));

export const scaleHtml = () =>
  `<span class="steps">${STEPS.map((label, i) => `<span class="hc h${i}">${label}</span>`).join("")}</span>`;

// The colour step follows the printed percentage: 0 stays 0, 1–20 is step 1, …, 81–100 is step 5.
export function heatCell(cell, lang, big = false) {
  const name = esc(LANG_NAMES[lang] || lang);
  if (!cell) return `<span class="hc none" data-tip="${name}: not run">–</span>`;
  const p = Math.round(cell.rate * 100);
  const failed = cell.n ? `${cell.k} of ${cell.n} answers failed` : `${p}% of answers failed`;
  const ci = cell.ci95 ? ` (95% CI ${pct(cell.ci95[0])}–${pct(cell.ci95[1])})` : "";
  const body = big ? `<small>${esc(lang)}</small><span>${p}%</span>` : `${p}%`;
  return `<span class="hc h${Math.ceil(p / 20)}" data-tip="${name}: ${failed}${ci}">${body}</span>`;
}

// Per-language results of every hypothesis that reached the verifier, as the server recounted them.
// Older runs only logged rates.
export function verified(events) {
  const out = {};
  for (const e of events) {
    if (e.node !== "verifier" || e.status !== "done") continue;
    out[e.hypothesis] = {overall: e.data.overall, ci95: e.data.overall_ci95,
                         cells: e.data.per_lang || asCells(e.data.rates || {})};
  }
  return out;
}

function languageMeans(rows) {
  return Object.fromEntries(LANGS.map(lang => {
    const rates = rows.map(r => r.v.cells[lang]?.rate).filter(rate => rate != null);
    return [lang, rates.length ? {rate: rates.reduce((a, b) => a + b, 0) / rates.length} : null];
  }));
}

function row({id, v, gap}, cards, run) {
  const name = esc(titleOf(id, run.hypotheses)), card = cards.get(id);
  const cells = LANGS.map(l => heatCell(v.cells[l], l)).join("") +
                `<span class="hgap">${Math.round(gap * 100)}</span>`;
  const tag = run.uncounted.has(id) ? UNCOUNTED : "";
  const label = note => `<span class="hname" title="${esc(id)}">${name}${note}${tag}</span>${cells}`;
  if (!card) {
    // Written up on its flags but dropped by the recount, like "below bar" on the graph tab.
    const status = run.status[id] === "finding" ? "below_bar" : run.status[id];
    const text = {not_reproducible: "not reproduced", below_bar: "below bar"}[status];
    const note = text ? `<em data-tip="${STATUS_TIPS[status]}">${text}</em>` : "";
    return `<div class="hrow">${label(note)}</div>`;
  }
  const note = card.evidence?.quoted ? "" : "<em>needs a check</em>";
  return `<a class="hrow" href="#f-${esc(id)}" data-open="${esc(id)}">${label(note)}</a>`;
}

function headline(means, count) {
  const ranked = LANGS.filter(l => means[l]).sort((a, b) => means[b].rate - means[a].rate);
  const [worst, best] = [ranked[0], ranked[ranked.length - 1]];
  return `Averaged over ${count} hypotheses, Apertus fails most often in ${LANG_NAMES[worst]} ` +
         `(${pct(means[worst].rate)}) and least often in ${LANG_NAMES[best]} (${pct(means[best].rate)}).`;
}

function legend(n) {
  const noise = n ? `With ${n} answers per cell, 0 of ${n} in one language and ${n} of ${n} in another can ` +
                    "happen by chance, so" : "A single row's gap is noisy, so";
  return [
    "<b>How to read it.</b> Each cell is how often Apertus failed the check in that language" +
      (n ? `, out of ${n} answers sampled with different seeds` : "") +
      ". The stronger the red, the more often it failed; the exact share is printed in every cell.",
    "<b>Gap</b> is the worst language minus the best, in percentage points, and rows are sorted by it. " +
      `${noise} judge the languages by the average row at the top.`,
    "Failing means a wrong fact, a stereotype, invented personal details or copied text, depending on " +
      "the hypothesis. Click a row to open its finding.",
  ].map(text => `<p>${text}</p>`).join("");
}

// run: the hypotheses' texts, their status in the run and the ones the server could not recount.
export function renderGap(ver, cards, run) {
  const rows = Object.entries(ver).map(([id, v]) => ({id, v, gap: spread(cellRates(v.cells))}))
    .sort((a, b) => b.gap - a.gap || b.v.overall - a.v.overall);
  if (!rows.length) {
    $("#heat").innerHTML = '<p class="empty">No hypothesis has reached the verifier in this run yet.</p>';
    $("#gapNote").textContent = $("#gapLegend").innerHTML = "";
    return;
  }
  const means = languageMeans(rows), meanGap = spread(Object.values(means).filter(Boolean).map(m => m.rate));
  const head = `<div class="hrow hhead"><span class="hname">Hypothesis</span>` +
    LANGS.map(l => `<span data-tip="${LANG_NAMES[l]}">${l}</span>`).join("") +
    `<span class="hgap">Gap</span></div>`;
  const average = `<div class="hrow avg"><span class="hname">Average of ${rows.length}</span>` +
    LANGS.map(l => heatCell(means[l], l)).join("") +
    `<span class="hgap">${Math.round(meanGap * 100)}</span></div>`;
  const focused = document.activeElement?.closest?.("#heat [data-open]")?.dataset.open;
  $("#heat").innerHTML = head + average + rows.map(r => row(r, cards, run)).join("");
  if (focused) $(`#heat [data-open="${CSS.escape(focused)}"]`)?.focus();
  $("#gapNote").textContent = headline(means, rows.length);
  $("#gapLegend").innerHTML = legend(Object.values(rows[0].v.cells)[0]?.n);
}
