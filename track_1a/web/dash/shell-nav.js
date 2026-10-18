import {$, esc} from "./text.js";
import {renderChips, renderFindings} from "./findings.js";
import {renderExplain} from "./explain.js";
import {loadStudio} from "./studio.js";
import {anchorFromUrl, fromUrl, page, scrollBehavior, setNotice, syncUrl, view} from "./shell-state.js";
import {hideTip, showTip} from "./shell-tip.js";

// Tabs, jumps to a card, a walkthrough or a glossary entry, and links that stay on the page.

let showRun = () => {};  // main.js: shows another run, as the picker does
const noHover = matchMedia("(hover: none)");

// The walkthrough applies a hypothesis the shell names only when it differs from the one named last
// time. A pick from its own list is named back right after, or a later link to the hypothesis named
// before the pick would look unchanged and be ignored.
export function drawExplain() {
  if (!page.latest) return;
  const {s, ver, status, meta} = page.latest;
  const onPick = id => {
    view.hypothesis = id;
    syncUrl();
    queueMicrotask(drawExplain);
  };
  renderExplain($("#explain"), s,
                {hypothesis: view.hypothesis, ver, status, minRate: s.min_rate, meta, onPick});
}

// ---- Tabs

const tabs = () => [...document.querySelectorAll('nav [role="tab"]')].filter(t => !t.hidden);
const available = name => tabs().some(t => t.dataset.tab === name);

// On a phone the tab bar scrolls sideways; the selected tab must not sit past its edge.
function keepInView(tab) {
  const bar = tab.parentElement;
  if (tab.offsetLeft < bar.scrollLeft || tab.offsetLeft + tab.offsetWidth > bar.scrollLeft + bar.clientWidth) {
    bar.scrollLeft = tab.offsetLeft - bar.clientWidth / 2 + tab.offsetWidth / 2;
  }
}

// Shows a tab without touching the URL; showTab also records it.
export function selectTab(name) {
  if (!available(name)) name = "overview";
  if (view.tab !== name) view.anchor = "";
  view.tab = name;
  for (const tab of document.querySelectorAll('nav [role="tab"]')) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    if (on) keepInView(tab);
  }
  document.querySelectorAll("main > section").forEach(s => s.hidden = s.id !== "tab-" + name);
  // The overview leads with the submission's own sentence; the run's would compete with it.
  $("#summary").hidden = name === "overview";
  hideTip();
  if (name === "studio") loadStudio();
}

// The walkthrough is drawn after the URL is recorded: drawing it can replace the URL's h with the
// hypothesis it picks, which must land on the new history entry and not on the one being left.
export function showTab(name, push = true) {
  selectTab(name);
  syncUrl(push);
  if (view.tab === "explain") drawExplain();
}

// Arrow keys move within the tab list, so they replace the history entry instead of adding one.
function onTabKey(e) {
  const list = tabs(), i = list.indexOf(e.target);
  const next = {ArrowLeft: i - 1, ArrowRight: i + 1, Home: 0, End: list.length - 1}[e.key];
  if (i < 0 || next == null) return;
  e.preventDefault();
  const tab = list[(next + list.length) % list.length];
  tab.focus();
  showTab(tab.dataset.tab, false);
}

// ---- Jumps

// A jump the reader clicks glides there; one that comes with the URL is already there on arrival.
function focusOn(el, highlight, instant) {
  if (!el.matches("a, button, input, select, summary, [tabindex]")) el.tabIndex = -1;
  el.scrollIntoView({behavior: instant ? "auto" : scrollBehavior(), block: "start"});
  el.focus({preventScroll: true});
  el.classList.add(highlight);
  setTimeout(() => el.classList.remove(highlight), 1600);
}

function focusCard(id, instant = false) {
  const el = document.getElementById("f-" + id);
  if (el) focusOn(el, "flash", instant);
  return Boolean(el);
}

function showAllCards() {
  view.domain = view.query = $("#search").value = "";
  renderChips(page.cards, view);
  renderFindings(page.cards, view);
}

export function openGlossary(key, instant = false) {
  const glossary = $("#glossary"), entry = key && document.getElementById("g-" + key);
  glossary.open = true;
  hideTip();
  focusOn(entry || glossary.querySelector("summary"), "lit", instant);
  view.anchor = entry ? "#g-" + key : "";
}

// A submitted finding's card, opened; the overview links to each.
function openSubmitted(key) {
  const card = document.getElementById("s-" + key);
  if (!card) return;
  card.open = true;
  focusOn(card.querySelector("summary"), "lit", true);
}

// An anchor from the URL waits for the first payload: the cards and the glossary come with it. A
// link to a card of another run, or a mistyped one, says so instead of landing at the top unexplained.
export function jumpTo(anchor) {
  const key = anchor.slice(3);
  if (anchor.startsWith("#g-")) {
    if (document.getElementById("g-" + key)) openGlossary(key, true);
    return;
  }
  if (anchor.startsWith("#s-")) {
    openSubmitted(key);
    return;
  }
  if (!focusCard(key, true) && page.cards.some(x => x.id === key)) {
    showAllCards();
    focusCard(key, true);
  }
  if (document.getElementById("f-" + key) || !page.latest) {
    setNotice("nocard");
    return;
  }
  setNotice("nocard", esc(`There is no finding card for ${key} in this run.`));
  view.anchor = "";
  syncUrl();
}

// Back returns to where a jump started, so the entry being left remembers what was clicked.
function rememberOrigin(link) {
  const attr = link.hasAttribute("data-open") ? "data-open" : "data-explain";
  history.replaceState({back: attr, id: link.getAttribute(attr)}, "", location.href);
}

function refocusOrigin() {
  const {back, id} = history.state || {};
  if (!back) return;
  const links = document.querySelectorAll(`#tab-${view.tab} [${back}="${CSS.escape(id)}"]`);
  [...links].find(el => el.matches("a[href], button"))?.focus({preventScroll: true});
}

function openFinding(id, from) {
  hideTip();
  rememberOrigin(from);
  showAllCards();
  selectTab("findings");
  view.anchor = "#f-" + id;
  syncUrl(true);
  focusCard(id);
}

// The link or button that opened the walkthrough is on a hidden tab now; the step the reader is on
// takes the focus, or the tab while the run is still loading.
export function focusWalkthrough() {
  const headings = document.querySelectorAll("#explain .explain-step:not([hidden]) h3");
  const heading = headings[headings.length - 1];
  if (!heading) {
    $("#t-explain").focus();
    return;
  }
  heading.closest("section").scrollIntoView({behavior: scrollBehavior(), block: "start"});
  heading.focus({preventScroll: true});
}

function openWalkthrough(id, from) {
  rememberOrigin(from);
  view.hypothesis = id;
  showTab("explain");
  focusWalkthrough();
}

// Shows what the URL asks for: on Back and Forward, and for a link to another tab or run.
function applyUrl() {
  const asked = fromUrl();
  Object.assign(view, {hypothesis: asked.hypothesis, domain: asked.domain, query: asked.query});
  $("#search").value = view.query;
  const anchor = anchorFromUrl();
  selectTab(/^#[fs]-/.test(anchor) ? "findings" : asked.tab);
  view.anchor = anchor;
  if (asked.run && asked.run !== view.run) {
    showRun(asked.run, {anchor});
    return;
  }
  if (view.tab === "explain") drawExplain();
  renderChips(page.cards, view);
  renderFindings(page.cards, view);
  if (anchor) jumpTo(anchor);
  else refocusOrigin();
}

// A link such as ?tab=gap&run=… is followed in place: loading the page again would fetch the run again.
function followLink(link) {
  hideTip();
  history.pushState(null, "", link.getAttribute("href"));
  applyUrl();
  if (!view.anchor) $('nav [aria-selected="true"]').focus();
}

// Plain clicks only: a middle or modified click opens the link's own URL in a new tab.
function onClick(e) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const tipped = e.target.closest("[data-tip]");
  const open = e.target.closest("[data-open]"), walk = e.target.closest("[data-explain]");
  const term = e.target.closest("a.term"), inPage = e.target.closest('a[href^="?"]');
  const row = open || walk, touch = e.pointerType ? e.pointerType !== "mouse" : noHover.matches;
  if (e.target.closest("a.skip")) {
    e.preventDefault();
    $("#main").focus();
  } else if (touch && tipped && row?.contains(tipped) && row !== tipped) {
    // A tap is the only way to read a cell's tip on a touch screen; the row's name still opens it.
    e.preventDefault();
    showTip(tipped);
  } else if (open) {
    e.preventDefault();
    openFinding(open.dataset.open, open);
  } else if (walk) {
    e.preventDefault();
    openWalkthrough(walk.dataset.explain, walk);
  } else if (term) {
    e.preventDefault();
    openGlossary(term.getAttribute("href").slice(3));
    syncUrl(true);
  } else if (inPage) {
    e.preventDefault();
    followLink(inPage);
  } else if (tipped) {
    showTip(tipped);
  } else if (!e.target.closest("#tip")) {
    hideTip();
  }
}

// showRunById(id, {push, anchor}) is how main.js shows another run.
export function wireNav(showRunById) {
  showRun = showRunById;
  document.querySelectorAll('nav [role="tab"]').forEach(tab => tab.onclick = () => showTab(tab.dataset.tab));
  $('nav[role="tablist"]').addEventListener("keydown", onTabKey);
  document.addEventListener("click", onClick);
  addEventListener("popstate", applyUrl);
}
