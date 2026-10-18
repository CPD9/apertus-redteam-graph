import {$} from "./text.js";
import {scrollBehavior} from "./shell-state.js";
import {focusWalkthrough, openGlossary, showTab} from "./shell-nav.js";

// The orientation under the tabs: shown on the first visit, reopened from the header link.

const INTRO_SEEN = "intro-seen";

function readSeen() {
  try {
    return localStorage.getItem(INTRO_SEEN) === "1";
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    localStorage.setItem(INTRO_SEEN, "1");
  } catch {
    // Without storage the intro simply shows again next time.
  }
}

function setOpen(open) {
  $("#intro").hidden = !open;
  $("#introLink").setAttribute("aria-expanded", String(open));
}

function showIntro() {
  const intro = $("#intro");
  setOpen(true);
  intro.tabIndex = -1;
  intro.scrollIntoView({behavior: scrollBehavior(), block: "nearest"});
  intro.focus({preventScroll: true});
}

function onIntroClick(e) {
  const action = e.target.closest("[data-intro]")?.dataset.intro;
  if (action === "explain") {
    showTab("explain");
    focusWalkthrough();
  } else if (action === "glossary") {
    openGlossary("");
  } else if (action === "close") {
    setOpen(false);
    markSeen();
    $('nav [aria-selected="true"]').focus();
  }
}

export function wireIntro() {
  setOpen(!readSeen());
  $("#introLink").onclick = e => {
    e.preventDefault();
    showIntro();
  };
  $("#intro").onclick = onIntroClick;
}
