// Where a hypothesis ended: the line above step 1, and what closes the last step.
import {STATUS, UNCOUNTED_TAB, esc, needed, pct, sum} from "./text.js";
import {pillHtml, runEnded} from "./graph.js";
import {answerCount, tallyVerb} from "./explain-grid.js";
import {langName} from "./explain-steps.js";

// Whose reply a node reads as JSON; the verifier reads the judge's verdict on each answer.
const JSON_READER = {attacker: "the attacker's", judge: "the judge's", verifier: "the judge's"};

// One sentence on where testing stopped and, for an unreadable reply, why.
function stoppedHtml(error) {
  const where = error.node === "graph" ? ""
    : ` in the ${esc(error.node)}` + (error.lang ? ` (${langName(error.lang)})` : "");
  const cause = /JSON/.test(error.text || "")
    ? `: ${JSON_READER[error.node] || "a model's"} reply could not be read as JSON` : "";
  return `Testing stopped for this hypothesis${where}${cause}.`;
}

// The command names the run's own models: without them the harness would test whatever the local
// settings name. It is not offered as a fresh test: every call goes through the LLM cache, which
// kept the unreadable reply before it was read, so a machine holding this run's cache gets it back.
function rerunHtml(c) {
  const models = [c.target && `LLM_NAME=${c.target}`, c.judge && `RED_LLM_NAME=${c.judge}`].filter(Boolean);
  const command = [...models, "PYTHONPATH=src python3 -m redteam.run --only", c.id].join(" ");
  const system = c.system ? " Add this run's system prompt as <code>--system</code>." : "";
  const unreadable = /JSON/.test(c.w.error.text || "") ? ", the unreadable one included" : "";
  return `<p>To run it again on its own, use this from <code>track_1a/</code>.${system} The harness ` +
         "answers from its LLM cache (<code>data/llm_cache</code>) first: where that cache holds this run's " +
         `calls, the same replies come back${unreadable}. Only calls the cache lacks reach a model.</p>` +
         `<pre class="explain-command"><code>${esc(command)}</code></pre>`;
}

function errorHtml(c) {
  const events = c.s.events, error = c.w.error;
  const wentOn = runEnded(events) || events.slice(error.at + 1).some(e => e.hypothesis && e.hypothesis !== c.id);
  return `<div class="explain-error"><p><b>${stoppedHtml(error)}</b>` +
         (wentOn ? " Only this hypothesis stopped; the run went on with the others." : "") + "</p>" +
         rerunHtml(c) +
         `<details><summary>The error as logged</summary><pre>${esc(error.text)}</pre></details></div>`;
}

const runParam = c => c.s.run_id ? "&amp;run=" + encodeURIComponent(c.s.run_id) : "";

// What closes the walkthrough: the error, the end state of a hypothesis that never reached the
// verifier, or a way on to the card or the heatmap.
export function ending(c) {
  const s = STATUS[c.st];
  if (c.w.error) return errorHtml(c);
  if (c.st === "running" || c.st === "queued") {
    return `<p class="explain-end">${pillHtml(c.st)} ${esc(s.tip)} The next steps appear as the log grows.</p>`;
  }
  const links = [
    c.st === "finding" && `<a class="explain-out" href="#f-${esc(c.id)}" data-open="${esc(c.id)}">Open its card</a>`,
    c.ver[c.id] && `<a class="explain-out" href="?tab=gap${runParam(c)}">See it in the language gap</a>`,
  ].filter(Boolean).join(" · ");
  const why = c.w.verifier ? "" : `<b>Ends here: ${esc(s.label)}.</b> ${esc(s.tip)} `;
  return why || links ? `<p class="explain-end">${why}${links}</p>` : "";
}

// The answer first: the status and the numbers behind it, before step 1.
function summaryText(c) {
  if (c.w.error) return stoppedHtml(c.w.error);
  const v = c.ver[c.id];
  if (!v) {
    const tried = c.w.attempts.length;
    return c.st === "no_issue" && tried
      ? `The judge flagged no answer in ${tried} attack ${tried === 1 ? "attempt" : "attempts"}.`
      : esc(STATUS[c.st].tip);
  }
  const count = answerCount(v), verb = tallyVerb(c);
  if (!count) {
    return `${pct(v.overall)} of the answers ${verb}` + (c.minRate == null ? "." : `; the bar is ${pct(c.minRate)}.`);
  }
  const {k, n} = count;
  const bar = c.minRate == null ? "" : `, ${needed(c.minRate, n)} needed`;
  const flagged = v.flagged && !c.uncounted ? sum(Object.values(v.flagged)) : null;
  if (c.st === "not_reproducible" && flagged != null) return `${flagged} of ${n} answers flagged${bar}.`;
  return `${k} of ${n} answers ${verb}${bar}` + (flagged != null && flagged !== k ? ` (${flagged} flagged).` : ".");
}

export function summaryHtml(c) {
  const log = `<a class="explain-log" href="?tab=graph${runParam(c)}" data-feed="${esc(c.id)}">` +
              `Its ${c.w.count} ${c.w.count === 1 ? "event" : "events"} in the log</a>`;
  return `${pillHtml(c.st)} ${c.uncounted ? UNCOUNTED_TAB + " " : ""}<span>${summaryText(c)}</span> ${log}`;
}
