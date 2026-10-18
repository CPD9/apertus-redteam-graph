import {LANGS, pct, sum} from "./text.js";

export const spread = values => values.length ? Math.max(...values) - Math.min(...values) : 0;
export const cellRates = cells => Object.values(cells).map(c => c.rate);
export const asCells = rates =>
  Object.fromEntries(Object.entries(rates).map(([lang, rate]) => [lang, {rate}]));
export const range = ci => `${pct(ci[0])}–${pct(ci[1])}`;
export const failedAny = cell => cell.k != null ? cell.k > 0 : cell.rate > 0;

// Per-language results of every hypothesis that reached the verifier, as the server recounted them,
// and how many answers the judge flagged before the recount where the run logged it. Older runs
// only logged rates.
export function verified(events) {
  const out = {};
  for (const e of events) {
    if (e.node !== "verifier" || e.status !== "done") continue;
    out[e.hypothesis] = {overall: e.data.overall, ci95: e.data.overall_ci95, flagged: e.data.flagged,
                         cells: e.data.per_lang || asCells(e.data.rates || {})};
  }
  return out;
}

// One language pooled over rows {v: {cells}}: the answers summed when every cell has its counts.
// Older runs only logged rates, so theirs is the mean of the rates.
function poolCells(cells) {
  if (!cells.length) return null;
  if (!cells.every(c => c.n)) return {rate: sum(cells.map(c => c.rate)) / cells.length};
  const k = sum(cells.map(c => c.k)), n = sum(cells.map(c => c.n));
  return {k, n, rate: k / n};
}

export const pooled = rows =>
  Object.fromEntries(LANGS.map(lang => [lang, poolCells(rows.map(r => r.v.cells[lang]).filter(Boolean))]));

// Every language of every row in one share; null when a cell has no counts.
export function pooledAll(rows) {
  const cells = rows.flatMap(r => Object.values(r.v.cells));
  return cells.length && cells.every(c => c.n) ? poolCells(cells) : null;
}
