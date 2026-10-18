import {$, esc, short} from "./text.js";
import {plannedHypotheses} from "./graph.js";
import {onLoopback, setNotice} from "./shell-state.js";
import {clock, loadRuns, newestRun, runTitle} from "./shell-runs.js";

// Until the server has created the new run's folder, "latest" may still name the previous run.
const SETTLE = 300;
let plan = null;
// The run on screen at the last payload, and the newest run before "Start a new run" was pressed:
// a replay can end before the page ever sees it going.
let going = {run: null, live: false}, startedAfter = null;

// What the server says a new run would use now (s.next_run), in one sentence.
function planText(p) {
  const forced = p.forced ? " (REDTEAM_BACKEND forces it)" : "";
  const nobody = p.endpoint ? `nothing answers at ${p.endpoint}` : "no model endpoint answers";
  if (p.backend === "vllm") return `A new run asks the model at ${p.endpoint}.`;
  if (p.backend === "replay") {
    const why = forced || ` (${nobody})`;
    // LLM_NAME on the server can pick the cache of another model than the run models.json names.
    if (!p.replays && p.replay_model) {
      return `A new run replays the cached answers of ${short(p.replay_model)}${why}: no model is asked ` +
             "and it ends almost at once.";
    }
    const what = p.replays ? runTitle(p.replays) : "the cached run";
    return `A new run replays ${what} from the cache${why}: no model is asked, the ` +
           "numbers repeat that run and it ends almost at once.";
  }
  return `A new run uses canned mock answers${forced || ` (${nobody} and there is no cache)`}: ` +
         "nothing in it says anything about Apertus.";
}

export function renderRunTools(s) {
  if (!onLoopback()) return;
  plan = s.next_run || null;
  $("#nextRun").textContent = plan ? planText(plan) : "";
  const button = $("#runBtn");
  if (button.dataset.posting) return;
  button.disabled = Boolean(s.running);
  button.textContent = s.running ? "Running…" : "Start a new run";
}

// startRun(switchRun): switchRun shows a run by id, as the picker does.
export async function startRun(switchRun) {
  const what = plan ? planText(plan) : "It asks the model endpoints if they answer, else replays the cache " +
                                       "or uses canned mock answers.";
  if (!confirm(`Start a new run?\n\n${what}\n\nThe view then switches to the new run.`)) return;
  const button = $("#runBtn"), msg = $("#runMsg");
  button.disabled = true;
  button.dataset.posting = "1";
  msg.textContent = "";
  await loadRuns();
  const before = newestRun();
  const res = await fetch("/api/run", {method: "POST"}).catch(() => null);
  const body = await res?.json().catch(() => null);
  delete button.dataset.posting;
  if (!res?.ok) {
    msg.className = "runmsg error";
    msg.textContent = body?.error || "Cannot reach the dashboard server.";
    button.disabled = false;
    return;
  }
  msg.className = "runmsg";
  msg.textContent = "Run started.";
  startedAfter = before;
  setTimeout(() => switchRun("latest", {push: true}), SETTLE);
}

// Whether "Start a new run" was pressed and no payload has named the new run yet.
export const awaitingStart = () => startedAfter !== null;

// Called with every payload: says so when the run on screen, or the run just started, has ended.
export function followRun(s, live, mock) {
  const started = Boolean(startedAfter !== null && s.run_id && s.run_id !== startedAfter);
  if (started) startedAfter = null;
  if (s.run_id && !live && (started || (going.run === s.run_id && going.live))) sayFinished(s, mock);
  going = {run: s.run_id, live};
}

// Shown to every reader, and read out: #notices is a status region.
function sayFinished(s, mock) {
  const end = s.events.findLast(e => e.node === "graph" && e.status === "end");
  const at = end?.t ? ` at ${clock(end.t)}` : "";
  const planned = plannedHypotheses(s.events).length;
  const counted = planned ? `${s.findings.length} of ${planned} hypotheses reproduced`
                          : `${s.findings.length} reproduced`;
  const text = `Run finished${at}: ${counted}${mock ? " (mock data)" : ""}.`;
  const q = tab => `?tab=${tab}&run=${encodeURIComponent(s.run_id)}`;
  setNotice("finished", `${esc(text)} See <a href="${esc(q("findings"))}">Findings</a> or ` +
                        `<a href="${esc(q("gap"))}">Language gap</a>.`, "done");
  if (onLoopback()) $("#runMsg").textContent = "";
}
