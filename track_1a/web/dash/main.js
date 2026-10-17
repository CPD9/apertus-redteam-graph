import {$, esc} from "./text.js";
import {attacks} from "./evidence.js";
import {byStrength, cardModel, renderChips, renderFacts, renderFindings} from "./findings.js";
import {renderGap, scaleHtml, verified} from "./heat.js";
import {drawAgents, hypothesisStatus, plannedHypotheses, renderGraphTab, renderLive} from "./graph.js";
import {loadStudio, offerStudio, saveAvatar} from "./studio.js";

const TABS = ["graph", "findings", "gap"];  // the studio tab only where offerStudio finds it
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const RECORDED = "20261016-172309-1f71";  // the canonical 8B run of the report
const params = new URLSearchParams(location.search);
const view = {tab: "graph", run: params.get("run") || "latest", domain: "", query: ""};
const shown = {graph: "", data: ""};
let cards = [], runList = [], pollId = 0, timer;

function renderData(s, {ver, status, finished}) {
  const seeds = s.events.find(e => e.node === "verifier" && e.status === "start")?.data.seeds || [];
  const run = {ver, status, seeds, hypotheses: s.hypotheses, uncounted: new Set(s.uncounted),
               control: Object.fromEntries(s.control.map(c => [c.id, c])), attacks: attacks(s.events)};
  cards = s.findings.map(f => cardModel(f, run)).sort(byStrength);
  if (!cards.some(x => x.domain === view.domain)) view.domain = "";
  $("#fcount").textContent = cards.length || "";
  renderFacts(cards, {planned: plannedHypotheses(s.events).length, finished, rejudge: s.rejudge});
  renderChips(cards, view);
  renderFindings(cards, view);
  renderGap(ver, new Map(cards.map(x => [x.id, x])), run);
}

// The findings and the heatmap change once per finished hypothesis, the graph tab with every event.
// Rebuilding each only when its own inputs change keeps a text selection or an open card in place.
function changed(part, ...inputs) {
  const key = inputs.join(":");
  if (shown[part] === key) return false;
  shown[part] = key;
  return true;
}

function update(s) {
  const ended = renderLive(s);
  const ver = verified(s.events), status = hypothesisStatus(s.events);
  const finished = Object.values(status).filter(v => v !== "running").length;
  if (changed("graph", s.run_id, s.events.length)) renderGraphTab(s, status);
  if (changed("data", s.run_id, s.findings.length, s.control.length, s.rejudge?.n, s.uncounted.length,
              finished)) {
    renderData(s, {ver, status, finished});
  }
  syncRunOption(s);
  $("#reviewLink").href = "review.html" + (s.run_id ? "?run=" + encodeURIComponent(s.run_id) : "");
  return s.running || (s.run_id && !ended);
}

// A fresh clone has no run of its own, only the recorded runs in data/runs/: show the canonical one
// (else the newest) instead of an empty page. Not while a run starts, which is the latest one.
function showRecorded(s) {
  if (s.run_id || s.running || view.run !== "latest" || !runList.length) return false;
  view.run = $("#runPick").value = (runList.find(r => r.id === RECORDED) || runList[0]).id;
  syncUrl();
  return true;
}

async function poll() {
  clearTimeout(timer);
  const id = ++pollId;
  const url = `/api/state?run=${encodeURIComponent(view.run)}`;
  const s = await fetch(url).then(r => r.json()).catch(() => null);
  // Switching runs starts a newer poll; this answer may belong to the run that was left.
  if (id !== pollId) return;
  if (s && showRecorded(s)) return poll();
  let live = false;
  try {
    if (s) live = update(s);
  } finally {
    // A finished run only changes when control or rejudge results land, so check it less often.
    timer = setTimeout(poll, live ? 700 : 5000);
  }
}

function runName(r) {
  const [, mo, d, h, mi] = r.id.match(/^\d{4}(\d\d)(\d\d)-(\d\d)(\d\d)/) || [];
  const when = mo ? `${+d} ${MONTHS[mo - 1]} ${h}:${mi}` : r.id;
  const what = r.label || String(r.model ?? "").split("/").pop();
  const how = r.backend && r.backend !== "vllm" ? ` (${r.backend})` : "";
  // The copies of the recorded runs in data/runs/ ship without findings files: no count until shown.
  const count = r.findings != null ? ` · ${r.findings} findings` : r.written ? ` · ${r.written} written up` : "";
  return `${when} · ${what}${how}${count}`;
}

async function loadRuns() {
  const list = await fetch("/api/runs").then(r => r.json()).catch(() => null);
  if (!list) return;
  runList = list;
  $("#runPick").innerHTML = `<option value="latest">Latest run</option>` +
    runList.map(r => `<option value="${esc(r.id)}">${esc(runName(r))}</option>`).join("");
  if (!runList.some(r => r.id === view.run)) view.run = "latest";
  $("#runPick").value = view.run;
}

// The picker lists the findings files the harness wrote for each run until a run is shown: only then
// are its findings recounted. A live run keeps adding them.
function syncRunOption(s) {
  const r = runList.find(r => r.id === s.run_id);
  if (!r) {
    if (s.run_id) loadRuns();
    return;
  }
  if (r.findings === s.findings.length) return;
  r.findings = s.findings.length;
  const option = [...$("#runPick").options].find(o => o.value === r.id);
  if (option) option.textContent = runName(r);
}

function syncUrl() {
  const q = new URLSearchParams({tab: view.tab});
  if (view.run !== "latest") q.set("run", view.run);
  history.replaceState(null, "", "?" + q);
}

function showTab(name) {
  view.tab = name;
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("main > section").forEach(s => s.hidden = s.id !== "tab-" + name);
  if (name === "studio") loadStudio();
  syncUrl();
}

function openFinding(id) {
  view.domain = "";
  view.query = $("#search").value = "";
  renderChips(cards, view);
  renderFindings(cards, view);
  showTab("findings");
  const el = document.getElementById("f-" + id);
  if (!el) return;
  el.scrollIntoView({behavior: "smooth", block: "start"});
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 1600);
}

function placeTip(e) {
  const target = e.target.closest?.("[data-tip]"), tip = $("#tip");
  tip.hidden = !target;
  if (!target) return;
  tip.textContent = target.dataset.tip;
  const r = target.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2)) + "px";
  tip.style.top = (r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8) + "px";
}

async function startRun() {
  $("#runBtn").disabled = true;
  // Until the server has started the run, "latest" can still name no run; drop polls sent before.
  clearTimeout(timer);
  pollId++;
  view.run = $("#runPick").value = "latest";
  syncUrl();
  await fetch("/api/run", {method: "POST"});
  setTimeout(poll, 300);
}

drawAgents(Date.now());
document.querySelectorAll(".scale").forEach(el => el.insertAdjacentHTML("afterbegin", scaleHtml()));
document.querySelectorAll("nav button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
showTab(TABS.includes(params.get("tab")) ? params.get("tab") : "graph");
offerStudio().then(present => { if (present && params.get("tab") === "studio") showTab("studio"); });

$("#runPick").onchange = e => { view.run = e.target.value; syncUrl(); poll(); };
$("#domains").onclick = e => {
  const button = e.target.closest("button");
  if (!button) return;
  view.domain = button.dataset.domain;
  renderChips(cards, view);
  renderFindings(cards, view);
};
$("#search").oninput = e => { view.query = e.target.value; renderFindings(cards, view); };
$("#heat").onclick = e => {
  const row = e.target.closest("a[data-open]");
  if (!row) return;
  e.preventDefault();
  openFinding(row.dataset.open);
};
document.addEventListener("mouseover", placeTip);
addEventListener("scroll", () => $("#tip").hidden = true, {passive: true});
$("#runBtn").onclick = startRun;
$("#saveAvatar").onclick = saveAvatar;

loadRuns().then(poll);
