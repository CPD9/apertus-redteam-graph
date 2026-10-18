// How it works: one hypothesis replayed step by step from the run log. No model is called.
import {esc, term, titleOf} from "./text.js";
import {verified} from "./heat.js";
import {endStates, hypothesisStatus, plannedHypotheses, runEnded, selfJudged} from "./graph.js";
import {showFeedFor} from "./graph-feed.js";
import {checkAgreement, walk} from "./explain-log.js";
import {answerStep, attackStep, claimStep, controlStep, scribeStep, translateStep} from "./explain-steps.js";
import {fillGrid, stopFilling, verifierStep} from "./explain-grid.js";
import {ending, summaryHtml} from "./explain-end.js";
import {defaultPick, optionsHtml} from "./explain-pick.js";
import {frameHtml} from "./explain-frame.js";

export {introHtml, renderGlossary} from "./explain-glossary.js";

const PLAY_EVERY = 2500;
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// The reader's place survives polling: rebuilt only when the hypothesis or its part of the log changes.
// missing: a hypothesis the URL asked for that this run does not have. before: the one shown when
// the reader switched runs, so the same one in the new run opens at the same step.
const view = {root: null, last: null, run: null, asked: undefined, id: null, before: null, missing: "",
              step: 0, key: "", steps: [], picker: "", playing: 0};
const part = selector => view.root.querySelector(selector);

const stepsOf = c => [claimStep(c), attackStep(c), translateStep(c), answerStep(c), verifierStep(c),
                     scribeStep(c), controlStep(c)].filter(Boolean);

function stepHtml(step, i, steps, end) {
  const next = steps[i + 1];
  const tail = next ? `<button type="button" class="explain-next" data-act="next">Next: ${esc(next.nav)}</button>`
                    : end;
  return `<section class="explain-step" data-index="${i}" aria-labelledby="explain-h${i}">` +
         `<h3 id="explain-h${i}" tabindex="-1"><span class="explain-num">${i + 1}</span> ${esc(step.title)}</h3>` +
         `${step.html}${tail}</section>`;
}

function skeleton(root) {
  root.classList.add("explain");
  root.innerHTML = frameHtml();
  part("#explainPick").onchange = e => choose(e.target.value, true);
  part(".explain-nav").onclick = e => {
    const button = e.target.closest("button[data-step]");
    if (button) act(() => go(+button.dataset.step));
  };
  root.addEventListener("click", e => {
    // The shell follows the link to the graph tab; the feed there is narrowed to this hypothesis
    // first and brought into view after.
    const log = e.target.closest("a[data-feed]");
    if (log && e.button === 0 && !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) showFeedFor(log.dataset.feed);
    const button = e.target.closest("button[data-act]");
    if (!button) return;
    const what = button.dataset.act, last = view.steps.length - 1;
    if (what === "play") return view.playing ? stop() : play();
    act(() => what === "prev" ? go(view.step - 1)
      : what === "next" ? go(view.step + 1)
      : go(last, {focusAt: Math.min(view.step + 1, last)}));
  });
}

// Any step the reader picks by hand ends Play.
function act(move) {
  pause();
  move();
}

function show() {
  const last = view.steps.length - 1;
  view.root.querySelectorAll(".explain-step").forEach(el => el.hidden = +el.dataset.index > view.step);
  view.root.querySelectorAll(".explain-next").forEach(el =>
    el.hidden = +el.closest(".explain-step").dataset.index !== view.step);
  view.root.querySelectorAll(".explain-nav button").forEach(b => {
    const i = +b.dataset.step;
    b.classList.toggle("seen", i <= view.step);
    if (i === view.step) b.setAttribute("aria-current", "step");
    else b.removeAttribute("aria-current");
  });
  const lit = new Set(view.steps[view.step]?.agents || []);
  view.root.querySelectorAll(".explain-agents li").forEach(li => li.classList.toggle("on", lit.has(li.dataset.agent)));
  const button = what => part(`.explain-controls [data-act="${what}"]`);
  button("prev").disabled = view.step <= 0;
  button("next").disabled = button("all").disabled = view.step >= last;
  button("play").textContent = view.playing ? "Pause" : "Play";
  // The sticky bar grows with the summary and the step list; a step scrolls in just below it.
  const height = part(".explain-bar").offsetHeight;
  if (height) view.root.style.setProperty("--explain-bar", `${height}px`);
}

// keepFocus: Play moves on by itself, so the focus stays on its button, where the reader can pause,
// and the step is announced instead.
function go(i, {focusAt = null, keepFocus = false} = {}) {
  const from = view.step, last = view.steps.length - 1;
  view.step = Math.max(0, Math.min(i, last));
  // Only steps the reader brings in slide in; a redraw while a live run grows the log stays still.
  view.root.querySelectorAll(".explain-step").forEach(el => {
    if (+el.dataset.index > from && +el.dataset.index <= view.step) el.classList.add("reveal");
  });
  show();
  const grid = view.steps.findIndex(step => step.grid);
  if (grid >= 0 && from < grid && grid <= view.step) fillGrid(view.root);
  const heading = part(`#explain-h${focusAt ?? view.step}`);
  if (!heading) return;
  if (keepFocus) say(`Step ${view.step + 1} of ${view.steps.length}: ${view.steps[view.step].title}`);
  else heading.focus({preventScroll: true});
  heading.closest("section").scrollIntoView({block: "start", behavior: reducedMotion() ? "auto" : "smooth"});
}

function say(text) {
  part(".explain-live").textContent = text;
}

function play() {
  const last = view.steps.length - 1;
  if (view.step >= last) go(0, {keepFocus: true});
  view.playing = setInterval(() => {
    // A hidden tab has nothing to show; stop instead of scrolling behind the reader's back.
    if (!view.root.isConnected || view.root.closest("[hidden]")) return pause();
    go(view.step + 1, {keepFocus: true});
    if (view.step >= view.steps.length - 1) pause();
  }, PLAY_EVERY);
  show();
}

function pause() {
  clearInterval(view.playing);
  view.playing = 0;
  if (view.steps.length) show();
}

// The reader paused it: the button keeps the focus, so its new name may go unread.
function stop() {
  pause();
  say("Paused");
}

// Escape pauses Play wherever the focus is.
addEventListener("keydown", e => {
  if (e.key === "Escape" && view.playing) stop();
});

// byReader: picked in the list, so the shell is told; a hypothesis the shell named it knows already.
function choose(id, byReader = false) {
  if (id === view.id) return;
  pause();
  stopFilling();
  // build() keeps the step within the new run's steps.
  if (id !== view.before) view.step = 0;
  view.before = null;
  view.id = id;
  view.key = "";
  if (byReader) {
    view.missing = "";
    view.last[2].onPick?.(id);
    renderExplain(...view.last);
  }
}

function syncPicker(planned, states, hypotheses) {
  const html = optionsHtml(planned, states, hypotheses), select = part("#explainPick");
  if (html !== view.picker) select.innerHTML = view.picker = html;
  select.value = view.id;
}

function setNotice(text) {
  const notice = part(".explain-notice");
  if (notice.textContent === text) return;
  notice.textContent = text;
  notice.hidden = !text;
}

function build(c) {
  stopFilling();
  view.steps = stepsOf(c);
  view.step = Math.min(view.step, view.steps.length - 1);
  const end = ending(c);
  part(".explain-summary").innerHTML = summaryHtml(c);
  part(".explain-nav").innerHTML = view.steps.map((step, i) =>
    `<li><button type="button" data-step="${i}">${i + 1}. ${esc(step.nav)}</button></li>`).join("");
  part(".explain-steps").innerHTML = view.steps.map((step, i, all) =>
    stepHtml(step, i, all, i === all.length - 1 ? end : "")).join("");
  show();
}

// opts: {hypothesis, ver, status, minRate, meta, onPick}. status is the map hypothesisStatus returns;
// meta.target and meta.judge name the models, meta.system the run's system prompt.
export function renderExplain(root, s, opts = {}) {
  if (view.root !== root || !root.querySelector(".explain-steps")) {
    view.root = root;
    view.picker = view.key = "";
    skeleton(root);
  }
  view.last = [root, s, opts];
  const planned = plannedHypotheses(s.events);
  if (!planned.length) {
    part(".explain-source").textContent = "";
    setNotice("");
    part(".explain-bar").hidden = true;
    part(".explain-steps").innerHTML = '<p class="empty">No run to explain yet.</p>';
    view.key = "";
    return;
  }
  part(".explain-bar").hidden = false;
  if (s.run_id !== view.run) {
    view.run = s.run_id;
    view.asked = undefined;
    view.before = view.id;
    view.id = null;
    view.missing = "";
  }
  // A hypothesis the shell names (a link or ?h=) wins once; after that the reader's own pick stays.
  if (opts.hypothesis !== view.asked) {
    view.asked = opts.hypothesis;
    if (planned.includes(opts.hypothesis)) {
      view.missing = "";
      choose(opts.hypothesis);
    }
  }
  const status = opts.status || hypothesisStatus(s.events), states = endStates(s, status);
  const ver = opts.ver || verified(s.events), minRate = opts.minRate ?? s.min_rate;
  if (!planned.includes(view.id)) {
    // One the URL asks for but this run lacks stays in the URL, so going back to a run that has it
    // shows it again; the notice says what is shown instead.
    view.missing = opts.hypothesis && !planned.includes(opts.hypothesis) ? opts.hypothesis : "";
    choose(defaultPick(planned, states, ver, s.hypotheses));
    if (!view.missing) opts.onPick?.(view.id);
  }
  syncPicker(planned, states, s.hypotheses);
  const meta = opts.meta || {}, name = meta.name || s.run_id, live = s.running && !runEnded(s.events);
  const self = selfJudged(meta);
  part(".explain-source").innerHTML = live
    ? `Follows the log of <b>${esc(name)}</b> as it is written; this page sends nothing to a model.`
    : `${term("replay", "Replays")} the recorded log of <b>${esc(name)}</b>; nothing is sent to a model.`;
  // An id no bank knows has no title; it is quoted as the link gave it.
  const missing = s.hypotheses[view.missing] ? titleOf(view.missing, s.hypotheses) : `The hypothesis “${view.missing}”`;
  setNotice(view.missing ? `${missing} is not in ${name}; showing ${titleOf(view.id, s.hypotheses)}.` : "");

  const w = walk(s.events, view.id), control = (s.control || []).find(row => row.id === view.id);
  const key = [s.run_id, view.id, w.count, Boolean(control), states(view.id), ver[view.id]?.overall, minRate,
               self].join("|");
  if (key === view.key) return;
  view.key = key;
  build({s, id: view.id, st: states(view.id), w, ver, minRate, control, selfJudged: self, target: meta.target,
         judge: meta.judge, system: Boolean(meta.system), check: checkAgreement(s.events),
         uncounted: (s.uncounted || []).includes(view.id)});
}
