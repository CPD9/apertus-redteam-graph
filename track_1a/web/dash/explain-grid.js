// The verifier step: every language asked again with each seed, and the count that decides the status.
import {LANGS, UNCOUNTED, esc, needed, pct, sum, term} from "./text.js";
import {pillHtml} from "./graph.js";
import {langName} from "./explain-steps.js";

// The recounted answers of a hypothesis over all languages; null for an older log that kept only rates.
export function answerCount(v) {
  const cells = Object.values(v?.cells || {});
  if (!cells.length || cells.some(x => x.n == null)) return null;
  return {k: sum(cells.map(x => x.k)), n: sum(cells.map(x => x.n))};
}

// Red marks only an answer that counts. A flag at severity 0, or one whose severity the log did not
// keep, is drawn without it, so the cells never show more failures than the row's count.
// The hatching of a cell whose severity was not logged is explained once under the grid; only
// screen readers hear it in every cell. stopped: testing ended on an error, so an empty cell will
// stay empty.
function cellHtml(cell, stopped) {
  if (!cell) {
    return `<td class="explain-cell">–<span class="sr"> ${stopped ? "not asked: testing stopped" : "not asked yet"}` +
           "</span></td>";
  }
  const [kind, word, how] = !cell.violation ? ["clean", "clean", ""]
    : cell.counted ? ["counts", "counts", cell.severity != null ? `<small>severity ${esc(cell.severity)}</small>` : ""]
    : cell.counted === false ? ["flagged", "flagged", "<small>severity 0</small>"]
    : ["flagged unrated", "flagged", '<span class="sr">, severity not logged</span>'];
  return `<td class="explain-cell ${kind}" data-order="${cell.order}"><span>${word}${how}</span></td>`;
}

// An uncounted hypothesis keeps the share the judge flagged, so its numbers say "flagged", not "count".
export const tallyVerb = c => c.uncounted ? "flagged" : "count";

function verdictLine(c) {
  const v = c.ver[c.id];
  if (!v || !c.w.done) return "";
  const count = answerCount(v), verb = tallyVerb(c);
  if (!count) {
    const share = c.minRate == null ? "" : `; the ${term("bar", "bar")} is ${pct(c.minRate)}`;
    return `<p class="explain-verdict"><b>${pct(v.overall)} of the answers ${verb}</b>${share}: ` +
           `${pillHtml(c.st)}</p>`;
  }
  const {k, n} = count;
  const bar = c.minRate == null ? "" : `; the ${term("bar", "bar")} is ${needed(c.minRate, n)} of ${n}`;
  return `<p class="explain-verdict"><b>${k} of ${n} answers ${verb} (${pct(k / n)})</b>${bar}: ` +
         `${pillHtml(c.st)}</p>`;
}

// done: the verifier finished, so each row starts with its number. gaps: cells testing never reached.
function gridKey(cells, {done, uncounted, gaps}) {
  const flags = cells.filter(cell => cell.violation);
  return [
    flags.some(cell => cell.counted) && "A red cell counts: the judge flagged it and rated it above severity 0.",
    flags.some(cell => cell.counted === false) && "An outlined cell was flagged at severity 0 and does not count.",
    flags.some(cell => cell.counted == null) && "This log did not keep the severity of each answer, so a " +
      "hatched cell shows only that the judge flagged it." + (done && !uncounted ? " The count at the start " +
      "of the row follows the rule: an answer counts when the judge flags it and rates it above severity 0." : ""),
    uncounted && `${UNCOUNTED} Its answers could not be replayed from the LLM cache, so the numbers at the ` +
      "start of the rows include every answer the judge flagged, also those it rated severity 0.",
    gaps && "A dash marks an answer that was never asked: testing stopped first.",
  ].filter(Boolean).map(text => `<p class="explain-note">${text}</p>`).join("");
}

export function verifierStep(c) {
  const w = c.w;
  if (!w.verifier) return null;
  const seeds = w.verifier.seeds || [], langs = w.verifier.langs || LANGS;
  const asked = new Map(w.cells.map((cell, order) => [`${cell.lang}|${cell.seed}`, {...cell, order}]));
  const counted = c.ver[c.id]?.cells || {}, stopped = Boolean(w.error);
  // Before the recount the judge may have flagged more; an uncounted row already shows the flags.
  const flagged = c.uncounted ? null : w.done?.flagged;
  const rows = langs.map(lang => {
    const x = counted[lang];
    const count = !w.done || !x ? "" : x.n == null ? pct(x.rate)
      : `${c.uncounted ? "flagged" : term("counts", "counts")} <b>${esc(x.k)} of ${esc(x.n)}</b>`;
    const before = flagged?.[lang] != null ? `<small>flagged ${esc(flagged[lang])}</small>` : "";
    return `<tr><th scope="row">${langName(lang)}</th><td class="explain-count">${count}${before}</td>` +
           seeds.map(seed => cellHtml(asked.get(`${lang}|${seed}`), stopped)).join("") + "</tr>";
  }).join("");
  const gaps = stopped && langs.some(lang => seeds.some(seed => !asked.has(`${lang}|${seed}`)));
  return {nav: "Verifier: reruns", title: "The verifier asks again", agents: ["verifier"], grid: true, html:
    `<p>The verifier asks the same questions again in ${langs.length} languages with ${seeds.length} ` +
    `${term("seed", seeds.length === 1 ? "seed" : "seeds")}: ${langs.length * seeds.length} answers, and only ` +
    "these are counted. Cells fill in the order the answers came in.</p>" +
    `<div class="explain-gridwrap"><table class="explain-grid"><caption class="sr">Verifier answers by ` +
    `language and seed</caption><thead><tr><th scope="col">Language</th><th scope="col">Result</th>` +
    seeds.map(seed => `<th scope="col">seed ${esc(seed)}</th>`).join("") +
    `</tr></thead><tbody>${rows}</tbody></table></div>` + verdictLine(c) +
    gridKey(w.cells, {done: Boolean(w.done), uncounted: c.uncounted, gaps})};
}

// The cells fill in the order the answers came in, once, as the reader reaches the step.
const CELL_EVERY = 80;
let filling = 0;

export const stopFilling = () => clearTimeout(filling);

export function fillGrid(root) {
  stopFilling();
  const cells = [...root.querySelectorAll(".explain-grid [data-order]")]
    .sort((a, b) => a.dataset.order - b.dataset.order);
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || !cells.length) return;
  cells.forEach(cell => cell.classList.add("pending"));
  const next = i => {
    cells[i].classList.remove("pending");
    if (i + 1 < cells.length) filling = setTimeout(next, CELL_EVERY, i + 1);
  };
  filling = setTimeout(next, CELL_EVERY, 0);
}
