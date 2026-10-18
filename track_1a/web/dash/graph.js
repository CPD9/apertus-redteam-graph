import {$, STATUS, UNCOUNTED, esc, short, titleOf, walkHref} from "./text.js";
import {renderFeed} from "./graph-feed.js";

export const AGENTS = [
  ["attacker", "Attacker", "writes a question with a false claim built in"],
  ["mutator", "Mutator", "translates it into each language"],
  ["target", "Target", "the Apertus model being tested"],
  ["judge", "Judge", "checks each answer against the official source"],
  ["verifier", "Verifier", "asks again in every language with each seed"],
  ["scribe", "Scribe", "writes up each reproduced hypothesis"],
];
const ENDINGS = ["no_issue", "not_reproducible", "error"];
// The tally and the legend list the end states in this order.
const END_STATES = ["finding", "below_bar", "not_reproducible", "no_issue", "error"];

// The avatars carry a stamp so a page loaded before an avatar was saved does not show the old one.
let avatarStamp = "";
export const avatarSrc = id => `avatars/${id}.png?${avatarStamp}`;

export const plannedHypotheses = events =>
  events.find(e => e.node === "graph" && e.status === "start")?.data?.hypotheses || [];

export const runEnded = events => events.some(e => e.node === "graph" && e.status === "end");

export function hypothesisStatus(events) {
  const status = {};
  for (const e of events) {
    if (!e.hypothesis) continue;
    if (e.node === "scribe" && e.status === "done") status[e.hypothesis] = "finding";
    else if (e.node === "graph" && ENDINGS.includes(e.status)) status[e.hypothesis] = e.status;
    else status[e.hypothesis] ??= "running";
  }
  return status;
}

// Older runs wrote up every hypothesis flagged often enough; the recount can drop one below the bar.
export function endStates(s, status) {
  const kept = new Set(s.findings.map(f => f.hypothesis));
  return id => {
    const st = status[id] || "queued";
    return st === "finding" && !kept.has(id) ? "below_bar" : st;
  };
}

export const pillHtml = st =>
  `<span class="pill ${st}" data-tip="${esc(STATUS[st].tip)}">${esc(STATUS[st].label)}</span>`;

export function drawAgents(stamp) {
  avatarStamp = stamp;
  $("#graph").innerHTML = AGENTS.map(([id, name, desc]) => `<div class="node" id="n-${id}">` +
    `<img src="${avatarSrc(id)}" alt=""><b>${name}</b><span>${desc}</span></div>`).join("");
  $("#pick").innerHTML = AGENTS.map(([id, name], i) =>
    `<label><input type="radio" name="agent" value="${id}"${i === 0 ? " checked" : ""}>` +
    `<img src="${avatarSrc(id)}" alt="">${name}</label>`).join("");
}

// The run log names the target as the endpoint serves it ("onprem-ai/Apertus-v1.5-70B-FP8") and the
// judge by its short served name ("apertus-70b-fp8"). Without the organisation and the case, and
// with a version only one of them names set aside, the two name the same weights.
function modelParts(name) {
  const plain = short(name).toLowerCase(), version = /-v(\d+(?:\.\d+)*)/;
  return {base: plain.replace(version, ""), version: plain.match(version)?.[1] || ""};
}

function sameModel(target, judge) {
  if (!target || !judge) return false;
  const a = modelParts(target), b = modelParts(judge);
  return a.base === b.base && (!a.version || !b.version || a.version === b.version);
}

// A mock run logs its canned stand-in ("MOCK-no-model") as every model it names. Older mock runs
// name only the target, so the names are checked as well as the backend.
export const mockRun = ({target, judge, backend} = {}) =>
  backend === "MOCK" || [target, judge].some(model => /^mock/i.test(model || ""));

// Whether the model under test also judged its answers. Canned mock answers come from no model, so
// a mock run never did. Every note on self-grading asks this one question.
export const selfJudged = (meta = {}) => !mockRun(meta) && sameModel(meta.target, meta.judge);

const SELF_JUDGED = "The judge is the target model itself; self-grading may under-flag.";

// For the provenance line: empty unless the model under test also judged its answers.
export const selfJudgeNote = (target, judge, backend) =>
  selfJudged({target, judge, backend}) ? SELF_JUDGED : "";

// Under the agents, the note says which of them one model plays; the provenance line already says
// that it grades its own answers.
function renderSelfJudge(s) {
  const first = s.events[0] || {}, target = first.model || "", judge = first.data?.red_model || "";
  let note = $("#selfJudge");
  if (!note) {
    document.querySelector("#tab-graph .loop")?.insertAdjacentHTML("afterend",
      '<p id="selfJudge" class="selfjudge" hidden></p>');
    note = $("#selfJudge");
  }
  if (!note) return;
  note.hidden = !selfJudged({target, judge, backend: first.backend});
  note.innerHTML = note.hidden ? "" : `In this run one model plays every part: the target ` +
    `<code>${esc(short(target))}</code> is also the attacker, the mutator and the judge ` +
    `(<code>${esc(short(judge))}</code>).`;
}

const LOOP = "Judge finds nothing → <em>loop back to Attacker</em> with feedback, one attempt per attack " +
  "strategy · Judge finds a violation → Verifier reruns every language × seed.";
const hypotheses = n => `${n} ${n === 1 ? "hypothesis" : "hypotheses"}`;

// The neutral question and the second judge are commands of their own, run after a run or not at
// all, so the loop says which of them this run has had.
function afterRun(s) {
  const control = s.control?.length, rejudge = s.rejudge?.n;
  if (!s.events.length) return "After a run, a neutral question and a second judge can check it as separate steps.";
  if (control && rejudge) {
    return `Afterwards, as separate steps: a neutral question for ${hypotheses(control)} and a second judge ` +
           `on ${rejudge} answers.`;
  }
  if (control) return `Afterwards, as a separate step: a neutral question for ${hypotheses(control)}. ` +
                      "No second judge has checked this run.";
  if (rejudge) return `Afterwards, as a separate step: a second judge on ${rejudge} answers. ` +
                      "No neutral question has been asked for this run.";
  return "No neutral question and no second judge have checked this run; both are separate steps after a run.";
}

function renderLoop(s) {
  const loop = document.querySelector("#tab-graph .loop");
  if (loop) loop.innerHTML = `${LOOP} ${esc(afterRun(s))}`;
}

function tallyText(hyps, states, live) {
  const count = st => hyps.filter(h => states(h) === st).length;
  const parts = END_STATES.map(st => {
    const n = count(st), label = STATUS[st].label;
    return `${n} ${st === "error" && n !== 1 ? "errors" : label}`;
  });
  const done = hyps.filter(h => !["running", "queued"].includes(states(h))).length;
  const lead = live ? `${done} of ${hyps.length} hypotheses done` : `${hyps.length} planned`;
  return `${lead}: ${parts.join(" · ")}`;
}

// The tip is muted, not the row: a pill without a colour of its own takes the row's.
const legendHtml = () => `<ul class="hyp-legend">` + END_STATES.map(st =>
  `<li>${pillHtml(st)} <span class="hyp-tip">${esc(STATUS[st].tip)}</span></li>`).join("") + "</ul>";

export function renderGraphTab(s, status) {
  const hyps = plannedHypotheses(s.events), uncounted = new Set(s.uncounted);
  const states = endStates(s, status), live = s.running && !runEnded(s.events);
  $("#hyps").className = hyps.length ? "" : "empty";
  $("#hyps").innerHTML = hyps.length ? hyps.map(h => {
    const tag = uncounted.has(h) ? UNCOUNTED : "";
    return `<a class="hyp" href="${walkHref(s.run_id, h)}" data-explain="${esc(h)}">` +
           `<span title="${esc(h)}">${esc(titleOf(h, s.hypotheses))}</span>` +
           `<span class="pills">${tag}${pillHtml(states(h))}</span></a>`;
  }).join("") + legendHtml() : "Start a run to see progress.";
  $("#tally").textContent = hyps.length ? tallyText(hyps, states, live) : "";
  renderLoop(s);
  renderSelfJudge(s);
  renderFeed(s, hyps, live);
}

// The glowing agent; returns whether the run has ended.
export function renderLive(s) {
  const ended = runEnded(s.events);
  const lastStart = [...s.events].reverse().find(e => e.status === "start" && e.node !== "graph");
  AGENTS.forEach(([id]) => {
    const node = $("#n-" + id), active = !ended && lastStart?.node === id;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "step");
    else node.removeAttribute("aria-current");
  });
  return ended;
}
