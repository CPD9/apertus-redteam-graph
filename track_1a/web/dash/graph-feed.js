// The graph tab's event log: the whole run, or the events of one hypothesis.
import {$, STATUS, esc, langAttr, pct, sum, titleOf} from "./text.js";

const FEED_SIZE = 80;

// The last payload is kept to redraw the feed when the reader picks a hypothesis.
const feed = {s: null, hyps: [], live: false, only: "", options: ""};

const MARK = text => `<span class="v">${text}</span>`;
const inLang = (d, text) => d.lang ? `<span ${langAttr(d.lang)}>${text}</span>` : text;

// A verifier result is the number of answers that count (flagged with severity above 0) unless the
// server could not recount it; runs that logged only rates fall back to the share.
function verifierResult(d, uncounted) {
  const cells = Object.values(d.per_lang || {}), word = uncounted ? "flagged " : "counted ";
  if (!cells.length || cells.some(c => c.n == null)) return word + pct(d.overall);
  return `${word}${sum(cells.map(c => c.k))} of ${sum(cells.map(c => c.n))}`;
}

// What the feed prints after the node and status of each kind of event.
const DESCRIBE = {
  "graph start": d => `${(d.hypotheses || []).length} hypotheses · ${esc((d.langs || []).join(" "))}`,
  "attacker done": d => esc(d.prompt),
  "judge done": d => (d.violation ? MARK("flagged") + " " : "ok ") + esc(d.reason),
  "target done": d => inLang(d, esc(String(d.answer ?? "").slice(0, 160))),
  "verifier done": verifierResult,
  "verifier progress": d => `seed ${esc(d.seed)}: ` +
    (!d.violation ? "clean" : d.counted === false ? MARK("flagged") + " at severity 0" : MARK("flagged")),
  "scribe done": d => d.path ? "wrote " + esc(d.path.split("/").pop())
                             : "no findings file: the counted share is below the bar",
};

function feedLine(e, s, uncounted) {
  const d = e.data || {}, lang = d.lang ? `[${esc(d.lang)}] ` : "";
  const describe = DESCRIBE[`${e.node} ${e.status}`] || (e.status === "error" ? x => esc(x.error) : () => "");
  const status = e.node === "graph" && STATUS[e.status] ? STATUS[e.status].label : e.status;
  // A feed of one hypothesis does not repeat its name on every line.
  const about = e.hypothesis && !feed.only ? ` · <small>${esc(titleOf(e.hypothesis, s.hypotheses))}</small>` : "";
  return `<div class="ev"><span class="n">${esc(e.node)}</span> ${esc(status)}${about} ` +
         `${lang}${describe(d, uncounted.has(e.hypothesis))}</div>`;
}

// The picker sits above the feed; index.html has no place for it, so it is added on first use.
function feedPicker() {
  if (!$("#feedPick")) {
    $("#feed").insertAdjacentHTML("beforebegin", '<div class="feedpick"><label for="feedPick">Events of</label>' +
                                                 '<select id="feedPick"></select></div>');
    $("#feedPick").onchange = e => {
      feed.only = e.target.value;
      drawFeed();
    };
  }
  return $("#feedPick");
}

function drawFeed() {
  const {s, hyps, live} = feed;
  if (!s) return;
  if (!hyps.includes(feed.only)) feed.only = "";
  const select = feedPicker(), options = '<option value="">All hypotheses</option>' +
    hyps.map(h => `<option value="${esc(h)}">${esc(titleOf(h, s.hypotheses))}</option>`).join("");
  // Rebuilt only when the list changes: a live run redraws the feed with every event.
  if (options !== feed.options) select.innerHTML = feed.options = options;
  select.value = feed.only;
  select.closest(".feedpick").hidden = !hyps.length;

  const events = feed.only ? s.events.filter(e => e.hypothesis === feed.only) : s.events;
  // One hypothesis leaves a few dozen events, so its feed shows them all.
  const shown = feed.only ? events : events.slice(-FEED_SIZE), uncounted = new Set(s.uncounted);
  const about = feed.only ? ` · ${titleOf(feed.only, s.hypotheses)}` : "";
  $("#feedHead").textContent = live ? `Live event feed${about}` : events.length > shown.length
    ? `Event log${about} · last ${shown.length} of ${events.length} events`
    : `Event log${about} · all ${events.length} events`;
  $("#feed").innerHTML = [...shown].reverse().map(e => feedLine(e, s, uncounted)).join("");
}

// hyps: the run's planned hypotheses; live: whether the run is still going.
export function renderFeed(s, hyps, live) {
  // Another run may plan a hypothesis with the same id; the pick belonged to the run it was made in.
  if (feed.s && feed.s.run_id !== s.run_id) feed.only = "";
  Object.assign(feed, {s, hyps, live});
  drawFeed();
}

const scrollBehavior = () => matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

// The walkthrough's link to the log of the hypothesis it shows. The log sits below the agents, a
// screen or more down, so once the shell has shown the graph tab and focused its tab button, the
// log is brought into view and takes the focus. The shell does that within the same click, so the
// timer runs after it.
export function showFeedFor(id) {
  feed.only = id;
  drawFeed();
  setTimeout(() => {
    if ($("#tab-graph").hidden) return;
    $("#feedHead").scrollIntoView({block: "start", behavior: scrollBehavior()});
    $("#feed").focus({preventScroll: true});
  });
}
