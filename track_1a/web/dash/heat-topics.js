import {LANGS, LANG_NAMES, esc, pct} from "./text.js";
import {pooled, pooledAll} from "./heat-data.js";
import {heatCell} from "./heat-cell.js";

// The same answers as the table above, pooled per topic: which kind of question fails where.
// Older runs logged only rates, and a mean of rates across topics would hide how many answers each
// holds, so they get no topic table.
export function topicsHtml(rows, run) {
  const byTopic = new Map();
  for (const r of rows) {
    const topic = run.hypotheses[r.id]?.domain || "other";
    byTopic.set(topic, [...(byTopic.get(topic) || []), r]);
  }
  if (byTopic.size < 2 || !pooledAll(rows)) return "";
  const topics = [...byTopic].map(([topic, members]) => ({topic, members, all: pooledAll(members)}))
    .sort((a, b) => b.all.rate - a.all.rate || a.topic.localeCompare(b.topic));
  const head = `<div class="hrow hhead" role="row"><span class="hname" role="columnheader">Topic</span>` +
    LANGS.map(l => `<span role="columnheader"><span aria-hidden="true">${l}</span>` +
                   `<span class="sr">${LANG_NAMES[l]}</span></span>`).join("") +
    `<span class="hgap" role="columnheader">All</span></div>`;
  const line = ({topic, members, all}) => {
    const means = pooled(members), count = members.length;
    return `<div class="hrow" role="row"><span class="hname" role="rowheader">` +
      `${esc(topic.replace(/_/g, " "))} <em>${count} ${count === 1 ? "hypothesis" : "hypotheses"}</em></span>` +
      LANGS.map(l => heatCell(means[l], l, {role: "cell"})).join("") +
      `<span class="hgap" role="cell">${pct(all.rate)}<small aria-hidden="true">${all.k}<wbr>/${all.n}</small>` +
      `<span class="sr">, ${all.k} of ${all.n} answers failed</span></span></div>`;
  };
  return `<h3>By topic</h3>
    <p class="heatnote">The rows above pooled by topic: each cell sums that topic's answers in one
      language; All sums its six languages. Riskiest topic first.</p>
    <div class="heat topics" role="table" aria-label="Share of answers that failed, per topic and language">
      ${head}${topics.map(line).join("")}</div>`;
}
