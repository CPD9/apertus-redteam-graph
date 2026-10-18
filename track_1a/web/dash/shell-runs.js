import {$, esc, short} from "./text.js";
import {here, onLoopback, setNotice, view} from "./shell-state.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const RECORDED = "20261016-172309-1f71";  // the canonical 8B run of the report

// Rows of /api/runs, newest first. The server counts the reproduced hypotheses of the report's runs;
// any other run is counted here once it has been opened, since counting it costs the server a replay.
let runList = [];
// Folded, the picker lists the report's runs, the newest local run and the run on screen: a machine
// that has made many runs would otherwise bury the report's four among a hundred replays. A reader
// on another machine gets the report's runs and the run on screen only.
let showAll = false;

// Run ids start with the time the run started: 20261016-172309-1f71.
function startedAt(id) {
  const [, y, mo, d, h, mi] = id.match(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)/) || [];
  return mo ? {day: `${+d} ${MONTHS[mo - 1]}`, year: y, time: `${h}:${mi}`} : null;
}

const when = id => { const t = startedAt(id); return t ? `${t.day} ${t.time}` : id; };
export const fullDate = id => { const t = startedAt(id); return t ? `${t.day} ${t.year}, ${t.time}` : id; };

// The time of a logged event (seconds since 1970) on the reader's clock.
export const clock = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});

export const runRow = id => runList.find(r => r.id === id);
export const newestRun = () => runList.find(r => r.latest)?.id || "";
const localRuns = () => runList.filter(r => !r.report);

function runLabel(r) {
  const count = r.reproduced != null ? ` · ${r.reproduced} reproduced` : "";
  if (r.report) return `${r.name} · ${startedAt(r.id)?.day || r.id}${count}`;
  const what = r.label || short(r.model);
  const how = r.backend === "replay" ? " (replay)"
    : r.backend && !["vllm", "MOCK"].includes(r.backend) ? ` (${r.backend})` : "";
  return `${when(r.id)} · ${what}${how}${r.system ? " · system prompt" : ""}${count}`;
}

// What the notices and the provenance line call a run.
export function runTitle(id) {
  if (id === "latest") return `the newest run on ${here()}`;
  const r = runRow(id);
  return r?.name || `the run of ${fullDate(id)}`;
}

function optionsHtml() {
  const option = (value, text) => `<option value="${esc(value)}">${esc(text)}</option>`;
  const group = (label, options) =>
    options.length ? `<optgroup label="${label}">${options.join("")}</optgroup>` : "";
  const rows = list => list.map(r => option(r.id, runLabel(r)));
  const report = runList.filter(r => r.report).sort((a, b) => a.id.localeCompare(b.id));
  const listed = localRuns().filter(r => (showAll && onLoopback()) || r.id === view.run);
  // "latest" follows whatever run is made next, so it says which run it names right now.
  const newest = onLoopback() && runRow(newestRun());
  const latest = newest ? [option("latest", `Newest on this machine: ${runLabel(newest)}`)]
    : view.run === "latest" ? [option("latest", `Newest run on ${here()}`)] : [];
  return group("Runs in the report", rows(report)) +
    group(`Runs on ${here()}`, [...latest, ...rows(listed.filter(r => r.backend !== "MOCK"))]) +
    group("Mock runs", rows(listed.filter(r => r.backend === "MOCK")));
}

export function drawPicker() {
  const select = $("#runPick"), others = localRuns().length;
  select.innerHTML = optionsHtml();
  select.value = view.run;
  $("#allRunsBox").hidden = !others || !onLoopback();
  $("#allRunsText").textContent = others === 1 ? "List the 1 run made on this machine"
                                               : `List all ${others} runs on this machine`;
}

export function listAllRuns(all) {
  showAll = all;
  drawPicker();
}

export async function loadRuns() {
  const list = await fetch("/api/runs").then(r => r.ok ? r.json() : null).catch(() => null);
  if (!list) return false;
  const opened = new Map(runList.filter(r => r.reproduced != null).map(r => [r.id, r.reproduced]));
  runList = list.map(r => ({...r, reproduced: r.reproduced ?? opened.get(r.id)}));
  drawPicker();
  // A fresh clone has only the runs the report rests on; an operator should know why.
  setNotice("fresh", onLoopback() && !localRuns().length
    ? "No runs on this machine yet: the picker lists the recorded runs the report rests on. " +
      "Start a new run to make one." : "", "info");
  return true;
}

// Decided once at load: a run going on now, else the report's canonical run.
export function startingRun(asked) {
  const known = id => id === "latest" ? runList.some(r => r.latest) : runList.some(r => r.id === id);
  if (!runList.length) return asked || RECORDED;
  if (asked && known(asked)) return asked;
  const fallback = runList.some(r => r.live) ? "latest" : known(RECORDED) ? RECORDED : runList[0].id;
  const shown = runTitle(fallback);
  const why = asked === "latest" ? `There is no newest run on ${here()}` : `Run ${asked} not found`;
  if (asked) setNotice("missing", esc(`${why}; showing ${shown}.`));
  return fallback;
}

// Labels the run on screen with its count once opened, and lists a run started since the last load;
// a run the list leaves out (a folder starting with _) is asked about once, not on every poll.
let askedAbout = "";

export function syncRunOption(s) {
  const r = runRow(s.run_id);
  if (!r) {
    if (s.run_id && s.run_id !== askedAbout) loadRuns();
    askedAbout = s.run_id;
    return;
  }
  if (r.reproduced === s.findings.length && $("#runPick").value === view.run) return;
  r.reproduced = s.findings.length;
  drawPicker();
}
