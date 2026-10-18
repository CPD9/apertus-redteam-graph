import {$} from "./text.js";

// One tooltip for every [data-tip], shown on hover, keyboard focus and tap, and hidden on Escape,
// scrolling away and tab changes. The tip itself can be hovered (WCAG 1.4.13).

let tipFor = null, tipHide;

export function showTip(target) {
  clearTimeout(tipHide);
  if (tipFor === target) return;
  hideTip();
  const tip = $("#tip");
  tip.textContent = target.dataset.tip;
  tip.hidden = false;
  tipFor = target;
  target.setAttribute("aria-describedby", "tip");
  placeTip();
}

function placeTip() {
  const tip = $("#tip"), r = tipFor.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2)) + "px";
  tip.style.top = (r.top - h - 6 < 8 ? r.bottom + 6 : r.top - h - 6) + "px";
}

export function hideTip() {
  clearTimeout(tipHide);
  $("#tip").hidden = true;
  tipFor?.removeAttribute("aria-describedby");
  tipFor = null;
}

function onMouseOver(e) {
  if (e.target.closest("#tip")) return clearTimeout(tipHide);
  const target = e.target.closest("[data-tip]");
  if (target) showTip(target);
}

function onMouseOut(e) {
  const to = e.relatedTarget;
  if (!tipFor || to?.closest?.("#tip") || tipFor.contains(to)) return;
  // A moment to cross the gap between the trigger and the tip.
  tipHide = setTimeout(hideTip, 150);
}

// A row link holds its status pill or tag, whose meaning would otherwise need a mouse. Only a link:
// <main> takes the focus from the skip link and from any click on its text, and holds every pill.
function onFocusIn(e) {
  const el = e.target;
  const target = el.closest?.("[data-tip]") ||
                 (el.matches?.("a[href]") ? el.querySelector(".pill[data-tip], .tag[data-tip]") : null);
  if (target) showTip(target);
  else if (tipFor) hideTip();
}

function onFocusOut(e) {
  if (tipFor && !tipFor.contains(e.relatedTarget)) hideTip();
}

// Moving the focus can scroll the page; a tip that belongs to the focused control follows it. The
// body and <main> hold every tip but are not controls: a tip opened by hover or tap hides.
function onScroll() {
  if (!tipFor) return;
  const f = document.activeElement;
  const owns = f && f !== document.body && f.id !== "main" &&
               (f === tipFor || f.contains(tipFor) || tipFor.contains(f));
  if (owns) placeTip();
  else hideTip();
}

export function wireTips() {
  document.addEventListener("mouseover", onMouseOver);
  document.addEventListener("mouseout", onMouseOut);
  document.addEventListener("focusin", onFocusIn);
  document.addEventListener("focusout", onFocusOut);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && tipFor) hideTip(); });
  addEventListener("scroll", onScroll, {passive: true});
}
