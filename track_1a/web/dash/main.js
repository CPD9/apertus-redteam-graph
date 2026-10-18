import {$} from "./text.js";
import {attacks} from "./evidence.js";
import {byStrength, cardModel, renderChips, renderFacts, renderFindings, renderSubmitted} from "./findings.js";
import {renderGap, scaleHtml, verified} from "./heat.js";
import {drawAgents, hypothesisStatus, plannedHypotheses, renderGraphTab, renderLive} from "./graph.js";
import {introHtml, renderGlossary} from "./explain.js";
import {offerStudio, saveAvatar} from "./studio.js";
import {anchorFromUrl, announce, fromUrl, onLoopback, page, setNotice, syncUrl, view} from "./shell-state.js";
import {drawPicker, listAllRuns, loadRuns, runRow, runTitle, startingRun, syncRunOption} from "./shell-runs.js";
import {renderProvenance, runMeta} from "./shell-provenance.js";
import {awaitingStart, followRun, renderRunTools, startRun} from "./shell-newrun.js";
import {wireTips} from "./shell-tip.js";
import {drawExplain, jumpTo, selectTab, showTab, wireNav} from "./shell-nav.js";
import {wireIntro} from "./shell-intro.js";

// A live run changes with every event. A finished run changes only when its neutral control or
// second judge lands, which are run from the command line; a reload shows them. It is not fetched
// again, not even on coming back to the tab: it is megabytes, and a phone comes back all the time.
// While the server runs something, a check every minute re-enables "Start a new run" when it ends.
const LIVE_POLL = 700, IDLE_POLL = 60000, RETRY_POLL = 5000;
// Arrow keys on a closed picker change the run with every press; wait until the reader settles.
const PICK_DELAY = 300;

const shown = {graph: "", data: "", info: ""};
let pollId = 0, timer, pickTimer, pendingAnchor = "", sayShowing = false;
// Whether the last poll asked for another: the tab coming back resumes only such polling.
let following = false;

// ---- Rendering a payload

function runModel(s, ver, status, meta, finished) {
  const seeds = s.events.find(e => e.node === "verifier" && e.status === "start")?.data.seeds || [];
  return {ver, status, seeds, hypotheses: s.hypotheses, uncounted: new Set(s.uncounted),
          control: Object.fromEntries(s.control.map(c => [c.id, c])), attacks: attacks(s.events),
          runId: s.run_id, runFolder: s.run_folder, minRate: s.min_rate, planned: plannedHypotheses(s.events), meta,
          submitted: s.submitted, mock: meta.backend === "MOCK", humanLabels: s.human_labels,
          languageMeans: s.language_means, rejudge: s.rejudge, finished};
}

function renderData(s, run) {
  page.cards = s.findings.map(f => cardModel(f, run)).sort(byStrength);
  if (!page.cards.some(x => x.domain === view.domain)) view.domain = "";
  renderSubmitted(s.submitted, run);
  renderFacts(page.cards, run);
  renderChips(page.cards, view);
  renderFindings(page.cards, view);
  renderGap(run.ver, new Map(page.cards.map(x => [x.id, x])), run);
}

function renderHelp(s, run) {
  const facts = {langs: s.events[0]?.data?.langs || [], seeds: run.seeds, planned: run.planned,
                 minRate: s.min_rate, judge: run.meta.judge, target: run.meta.target};
  renderGlossary($("#glossaryBody"), facts);
  $("#introBody").innerHTML = introHtml(facts);
}

// The findings and the heatmap change once per finished hypothesis, the graph tab with every event.
// Rebuilding each only when its own inputs change keeps a text selection or an open card in place.
function changed(part, ...inputs) {
  const key = inputs.join(":");
  if (shown[part] === key) return false;
  shown[part] = key;
  return true;
}

// The server's "running" is any run it started, not necessarily the one on screen, and a run
// without its end event that nothing writes to any more was killed. A run missing from the list
// started after the list was loaded.
function isLive(s, ended) {
  if (!s.run_id || ended) return false;
  const row = runRow(s.run_id);
  return !row || row.live || Boolean(s.running && row.latest);
}

function update(s) {
  const live = isLive(s, renderLive(s));
  const ver = verified(s.events), status = hypothesisStatus(s.events), meta = runMeta(s);
  const finished = Object.values(status).filter(v => v !== "running").length;
  page.latest = {s, ver, status, meta};
  if (changed("info", s.run_id, meta.name, live, Boolean(s.rejudge), s.next_run?.endpoint)) {
    renderProvenance(s, meta, live);
  }
  renderRunTools(s);
  const logGrew = changed("graph", s.run_id, s.events.length);
  if (logGrew) renderGraphTab(s, status);
  const dataChanged = changed("data", s.run_id, s.findings.length, s.control.length, s.rejudge?.n,
                              s.uncounted.length, finished, s.human_labels);
  if (dataChanged) {
    const run = runModel(s, ver, status, meta, finished);
    renderData(s, run);
    renderHelp(s, run);
    if (pendingAnchor) jumpTo(pendingAnchor);
    pendingAnchor = "";
  }
  // The neutral question and the recount reach the walkthrough without a new event in the log.
  if ((logGrew || dataChanged) && view.tab === "explain") drawExplain();
  syncRunOption(s);
  followRun(s, live, meta.backend === "MOCK");
  // "latest" names whatever run is newest when asked, so a link to it would later show another run:
  // the URL names the run instead. Right after "Start a new run" it may still name the run before.
  if (view.run === "latest" && s.run_id && !awaitingStart()) {
    view.run = s.run_id;
    drawPicker();
    syncUrl();
  }
  if (sayShowing && s.run_id) announce(`Showing ${runTitle(s.run_id)}`);
  sayShowing = false;
  $("#reviewLink").href = "review.html" + (s.run_id ? "?run=" + encodeURIComponent(s.run_id) : "");
  return live;
}

function nextPoll(s, live) {
  if (!s) return RETRY_POLL;
  if (live || (s.running && view.run === "latest")) return LIVE_POLL;
  return s.running || view.run === "latest" ? IDLE_POLL : 0;
}

async function poll() {
  clearTimeout(timer);
  const id = ++pollId;
  const s = await fetch(`/api/state?run=${encodeURIComponent(view.run)}`)
    .then(r => r.ok ? r.json() : null).catch(() => null);
  // Switching runs starts a newer poll; this answer may belong to the run that was left.
  if (id !== pollId) return;
  setNotice("offline", s ? "" : "Cannot reach the dashboard server; retrying.");
  let delay = RETRY_POLL;
  try {
    if (s) delay = nextPoll(s, update(s));
  } finally {
    following = Boolean(delay);
    if (delay) timer = setTimeout(() => { if (!document.hidden) poll(); }, delay);
  }
}

// opts.anchor: a card or glossary entry to show once the run is in; without one the page starts at
// its top, so a reader does not land in the middle of another run's card.
function switchRun(id, {push = false, anchor = ""} = {}) {
  clearTimeout(pickTimer);
  view.run = id;
  view.anchor = pendingAnchor = anchor;
  drawPicker();
  setNotice("missing");
  setNotice("nocard");
  setNotice("finished");
  $("#provenance").textContent = "Loading run…";
  $("#system").innerHTML = "";
  shown.info = "";  // "latest" can name the run already shown, which must not stay "Loading"
  if (!anchor && scrollY > 0) scrollTo({top: 0});
  syncUrl(push);
  poll();
}

// ---- Wiring

// The tab bar sticks to the top on phones; the heatmap's column header and jumps keep clear of it.
function trackNavHeight() {
  const nav = $("nav");
  const set = () => document.documentElement.style.setProperty("--nav-h", nav.offsetHeight + "px");
  new ResizeObserver(set).observe(nav);
}

function init() {
  const asked = fromUrl();
  Object.assign(view, {hypothesis: asked.hypothesis, domain: asked.domain, query: asked.query});
  $("#search").value = view.query;
  pendingAnchor = anchorFromUrl();

  drawAgents(Date.now());
  $("#introBody").innerHTML = introHtml({});
  renderGlossary($("#glossaryBody"), {});
  document.querySelectorAll(".scale").forEach(el => el.insertAdjacentHTML("afterbegin", scaleHtml()));
  selectTab(pendingAnchor.startsWith("#f-") ? "findings" : asked.tab);
  view.anchor = pendingAnchor;
  wireIntro();
  wireTips();
  wireNav(switchRun);
  trackNavHeight();
  if (onLoopback()) $("#runTools").hidden = false;
  offerStudio().then(present => {
    if (present && asked.tab === "studio" && view.tab === "findings") showTab("studio", false);
  });

  $("#runPick").onchange = e => {
    clearTimeout(timer);
    pollId++;  // drop an answer still on its way for the run being left
    clearTimeout(pickTimer);
    pickTimer = setTimeout(() => {
      sayShowing = true;
      switchRun(e.target.value, {push: true});
    }, PICK_DELAY);
  };
  $("#allRuns").onchange = e => listAllRuns(e.target.checked);
  $("#domains").onclick = e => {
    const button = e.target.closest("button[data-domain]");
    if (!button) return;
    view.domain = button.dataset.domain;
    renderChips(page.cards, view);
    renderFindings(page.cards, view);
    $(`#domains button[data-domain="${CSS.escape(view.domain)}"]`)?.focus();
    announce(`${document.querySelectorAll("#findings .fcard").length} shown`);
    syncUrl();
  };
  $("#search").oninput = e => {
    view.query = e.target.value;
    renderFindings(page.cards, view);
    syncUrl();
  };
  $("#runBtn").onclick = () => startRun(switchRun);
  $("#saveAvatar").onclick = saveAvatar;
  document.addEventListener("visibilitychange", () => { if (!document.hidden && following) poll(); });

  loadRuns().then(() => {
    view.run = startingRun(asked.run);
    drawPicker();
    syncUrl();
    poll();
  });
}

init();
