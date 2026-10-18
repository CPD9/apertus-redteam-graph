import {$, CHECK_TIP, LANGS, LANG_NAMES, STATUS, UNCOUNTED_TAB, esc, langNames, needed, sum, titleOf,
        walkHref} from "./text.js";
import {cellRates, failedAny, pooled, spread} from "./heat-data.js";
import {heatCell} from "./heat-cell.js";
import {coverage, headline, legend} from "./heat-summary.js";
import {topicsHtml} from "./heat-topics.js";
import {renderCompare} from "./heat-compare.js";

export {asCells, cellRates, failedAny, range, spread, verified} from "./heat-data.js";
export {heatCell, scaleHtml} from "./heat-cell.js";

const GROUPS = [
  ["everywhere", "Reproduced, fails in all six languages"],
  ["depends", "Reproduced, depends on the language"],
  ["not", "Did not clear the bar"],
  ["open", "Still being tested"],
];
const STATUS_ORDER = ["below_bar", "not_reproducible", "error"];

// The interval of each average comes from the server, which resamples whole hypotheses: the answers
// to one hypothesis are not independent. It belongs to the average only when both count the same
// answers.
function averages(rows, run) {
  const means = pooled(rows);
  for (const lang of LANGS) {
    const server = run.languageMeans?.[lang], mean = means[lang];
    if (server?.ci95 && mean?.n === server.n && mean.k === server.k) means[lang] = {...mean, ci95: server.ci95};
  }
  return means;
}

// The state a hypothesis without a card ended in. One written up on its flags but dropped by the
// recount is below the bar, as on the graph tab.
const endState = (id, run) => run.status[id] === "finding" ? "below_bar" : run.status[id] || "running";

// Both ways of missing the bar read the same: counted against needed. How many answers the judge
// flagged but rated harmless goes in the tip.
function statusNote(id, v, run) {
  const status = endState(id, run), cells = Object.values(v.cells);
  const k = sum(cells.map(c => c.k)), n = sum(cells.map(c => c.n));
  const flagged = v.flagged ? sum(Object.values(v.flagged)) : null;
  let text = STATUS[status]?.label || status, tip = STATUS[status]?.tip || "";
  if (["below_bar", "not_reproducible"].includes(status) && n && run.minRate != null) {
    text += `: ${k} of ${n} counted, ${needed(run.minRate, n)} needed`;
    if (flagged != null) {
      tip += ` Here: ${flagged} of the ${n} answers flagged` +
             (flagged > k ? `, ${flagged - k} of them rated severity 0.` : ".");
    }
  }
  const whole = LANGS.filter(l => v.cells[l]?.n && v.cells[l].k === v.cells[l].n);
  const one = whole.length && whole.length < LANGS.length
    ? ` · <em>every answer failed in ${esc(langNames(whole))}</em>` : "";
  return `<em tabindex="0" data-tip="${esc(tip)}">${esc(text)}</em>${one}`;
}

// The cells holding the row's highest rate; none when every language is equal.
function highest(cells) {
  const rates = cellRates(cells), top = Math.max(...rates);
  return rates.every(rate => rate === top) ? new Set() : new Set(LANGS.filter(l => cells[l]?.rate === top));
}

// A reproduced row opens its card, any other row the walkthrough of its hypothesis. Only the name
// link does: a tap on a cell shows that cell's tip instead.
function row({id, v, gap}, card, run) {
  const opens = card ? `data-open="${esc(id)}"` : `data-explain="${esc(id)}"`;
  const href = card ? `#f-${esc(id)}` : walkHref(run.runId, id);
  const domain = run.hypotheses[id]?.domain;
  const top = highest(v.cells), same = !top.size && Object.keys(v.cells).length === LANGS.length;
  const inline = [
    domain && `<span class="hdom">${esc(domain.replace(/_/g, " "))}</span>`,
    same && "<em>same in all six</em>",
    run.uncounted.has(id) && UNCOUNTED_TAB,
  ].filter(Boolean).join(" ");
  const check = `<em tabindex="0" data-tip="${esc(CHECK_TIP)}">needs a check</em>`;
  const note = card ? (card.evidence?.quoted ? "" : check) : statusNote(id, v, run);
  const name = `<span class="hname" role="rowheader"><a href="${href}" ${opens}>` +
               `${esc(titleOf(id, run.hypotheses))}<span class="go" aria-hidden="true"> ›</span></a> ` +
               inline + (note ? ` <span class="hnote">${note}</span>` : "") + "</span>";
  const cells = LANGS.map(l => heatCell(v.cells[l], l, {top: top.has(l), role: "cell"})).join("");
  return `<div class="hrow" role="row">${name}${cells}` +
         `<span class="hgap" role="cell">${Math.round(gap * 100)}</span></div>`;
}

function group(r, cards, run) {
  if (cards.has(r.id)) {
    return LANGS.every(l => r.v.cells[l] && failedAny(r.v.cells[l])) ? "everywhere" : "depends";
  }
  return endState(r.id, run) === "running" ? "open" : "not";
}

const rank = status => (STATUS_ORDER.indexOf(status) + 1) || STATUS_ORDER.length + 1;
const SORTS = {
  everywhere: (a, b) => b.v.overall - a.v.overall,
  depends: (a, b) => b.gap - a.gap || b.v.overall - a.v.overall,
  not: (a, b, run) => rank(endState(a.id, run)) - rank(endState(b.id, run)) || b.v.overall - a.v.overall,
  open: (a, b) => b.v.overall - a.v.overall,
};

// The rows that missed the bar did so in different ways; the heading says how many of each.
function heading(key, title, members, run) {
  let count = String(members.length);
  if (key === "not") {
    const tally = STATUS_ORDER.map(st => [st, members.filter(r => endState(r.id, run) === st).length])
      .filter(([, n]) => n);
    if (tally.length > 1) count += ": " + tally.map(([st, n]) => `${n} ${STATUS[st].label}`).join(" · ");
  }
  return `<div class="hrow hgroup" role="row"><span role="cell" aria-colspan="8">` +
         `<h3>${title} <span>(${esc(count)})</span></h3></span></div>`;
}

function groupRows(rows, cards, run) {
  return GROUPS.map(([key, title]) => {
    const members = rows.filter(r => group(r, cards, run) === key).sort((a, b) => SORTS[key](a, b, run));
    if (!members.length) return "";
    return heading(key, title, members, run) + members.map(r => row(r, cards.get(r.id), run)).join("");
  }).join("");
}

function header() {
  return `<div class="hrow hhead" role="row"><span class="hname" role="columnheader">Hypothesis` +
    `<span class="pcnote"> · % of answers failed</span></span>` +
    LANGS.map(l => `<span role="columnheader"><span aria-hidden="true">${l}</span>` +
                   `<span class="sr">${LANG_NAMES[l]}</span></span>`).join("") +
    `<span class="hgap" role="columnheader">Gap (points)</span></div>`;
}

// The note under the average says what it covers, next to the numbers it is about.
function averageRow(means, count, note) {
  const gap = spread(Object.values(means).filter(Boolean).map(m => m.rate));
  return `<div class="hrow avg" role="row"><span class="hname" role="rowheader">Average of ${count}</span>` +
    LANGS.map(l => heatCell(means[l], l, {role: "cell", interval: true})).join("") +
    `<span class="hgap" role="cell">${Math.round(gap * 100)}</span></div>` +
    (note ? `<div class="hrow hnoterow" role="row"><span role="cell" aria-colspan="8">${note}</span></div>` : "");
}

// The topic table and the comparison are not part of the index page; they go under the table once.
function moreBoxes() {
  if (!$("#heatMore")) {
    $("#heat").insertAdjacentHTML("afterend", '<div id="heatMore" class="heatmore">' +
      '<section id="heatTopics" class="topics"></section>' +
      '<section id="heatCompare" class="compare"></section></div>');
  }
  return {topics: $("#heatTopics"), compare: $("#heatCompare")};
}

function writeSummary(text) {
  $("#gapNote").textContent = text;
  const summary = $("#summary");
  if (summary) summary.textContent = text;
}

// run: the hypotheses' texts, their status in the run, the ones the server could not recount, the
// planned ids, the bar and what the server says about the target.
export function renderGap(ver, cards, run) {
  const heat = $("#heat"), more = moreBoxes();
  const rows = Object.entries(ver).map(([id, v]) => ({id, v, gap: spread(cellRates(v.cells))}));
  if (!rows.length) {
    heat.removeAttribute("role");
    heat.innerHTML = '<p class="empty">No hypothesis has reached the verifier in this run yet.</p>';
    $("#gapLegend").innerHTML = more.topics.innerHTML = "";
    more.compare.hidden = true;
    writeSummary("");
    return;
  }
  heat.setAttribute("role", "table");
  heat.setAttribute("aria-label", "Share of answers that failed, per hypothesis and language");
  const means = averages(rows, run), cells = Object.values(rows[0].v.cells);
  const focused = document.activeElement?.closest?.("#heat a")?.getAttribute("href");
  heat.innerHTML = header() + averageRow(means, rows.length, coverage(rows, means, run)) +
                   groupRows(rows, cards, run);
  if (focused) [...heat.querySelectorAll("a")].find(a => a.getAttribute("href") === focused)?.focus();
  more.topics.innerHTML = topicsHtml(rows, run);
  writeSummary(headline(means, rows, cards, run));
  const intervals = rows.some(r => Object.values(r.v.cells).some(c => c.ci95));
  $("#gapLegend").innerHTML = legend(cells[0]?.n, sum(cells.map(c => c.n)), run, intervals);
  renderCompare(more.compare, {rows, cards, run});
}
