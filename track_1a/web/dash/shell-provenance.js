import {$, esc, short} from "./text.js";
import {selfJudgeNote} from "./graph.js";
import {here, view} from "./shell-state.js";
import {fullDate, runRow} from "./shell-runs.js";

// Where a run's answers came from. The word "live" is left out: it read both as "the real model"
// and as "still going", which a separate badge says.
const BACKENDS = {
  vllm: {text: "real model answers", style: "be-real",
         tip: "Every answer came from the model endpoint (vLLM) while the run was made; this page shows " +
              "the recorded log."},
  replay: {text: "replay of cached answers", style: "be-replay", glossary: "replay",
           tip: "No model was asked: the answers come from the cache of an earlier run, so the numbers " +
                "repeat it."},
  MOCK: {text: "mock: canned answers", style: "be-mock", glossary: "mock",
         tip: "No model answered: canned answers that test the harness and say nothing about Apertus."},
};
const UNKNOWN = {style: "", tip: "The run's log does not say where its answers came from."};
const RUNNING = {text: "running now", style: "be-going",
                 tip: "The run is still writing its log; its numbers change as it goes."};

export function runMeta(s) {
  const first = s.events[0] || {}, row = runRow(s.run_id);
  return {name: row?.name || "", label: row?.label || first.data?.label || "", target: first.model || "",
          judge: first.data?.red_model || "", backend: first.backend || "", system: first.data?.system || ""};
}

// A badge says what it is in a tip; the replay and mock badges also open their glossary entry.
function badge({text, style, tip, glossary}) {
  const attrs = `class="backend ${style}${glossary ? " term" : ""}" data-tip="${esc(tip)}"`;
  return glossary ? `<a ${attrs} href="#g-${glossary}">${esc(text)}</a>`
                  : `<span ${attrs} tabindex="0">${esc(text)}</span>`;
}

function runLine(s, meta, live) {
  const date = fullDate(s.run_id);
  const title = meta.name ? `${meta.name} · ${date}` : date + (meta.label ? ` · ${meta.label}` : "");
  const source = BACKENDS[meta.backend] || {...UNKNOWN, text: meta.backend || "source not recorded"};
  return [`<b>${esc(title)}</b>`,
          `tested <b>${esc(short(meta.target))}</b>`,
          meta.judge && `judged by <b>${esc(short(meta.judge))}</b>`,
          badge(source) + (live ? " " + badge(RUNNING) : "")]
    .filter(Boolean).join(" · ");
}

// The endpoint is the one a new run would ask now (s.next_run), host and port only.
function mockHow(s) {
  const at = s.next_run?.endpoint;
  return at ? `Make vLLM answer at ${at}, directly or through an SSH tunnel, then start a new run.`
            : "Start vLLM, point LLM_BASE_URL at it, then start a new run.";
}

export function renderProvenance(s, meta, live) {
  $("#mockBanner").hidden = meta.backend !== "MOCK";
  $("#mockHow").textContent = mockHow(s);
  if (!s.run_id) {
    $("#provenance").textContent = view.run === "latest" ? `No run on ${here()} yet.` : "Run not found.";
    $("#system").innerHTML = "";
    return;
  }
  // Mock runs use one canned model for every role, which says nothing about grading oneself.
  const self = meta.backend === "MOCK" ? "" : selfJudgeNote(meta.target, meta.judge);
  const second = s.rejudge ? " How far a second judge agrees is on the Findings tab." : "";
  $("#provenance").innerHTML = `<p class="runline">${runLine(s, meta, live)}</p>` +
    (self ? `<p class="selfjudged">${esc(self + second)}</p>` : "");
  const files = `<details class="runfiles"><summary>Run id and folder</summary>` +
    `<p>run <code>${esc(s.run_id)}</code> in <code>${esc(s.run_folder)}</code></p></details>`;
  const system = meta.system ? `<details><summary>System prompt used in this run</summary>` +
                               `<blockquote>${esc(meta.system)}</blockquote></details>`
                             : '<p class="nosystem">No system prompt set</p>';
  $("#system").innerHTML = files + system;
}
