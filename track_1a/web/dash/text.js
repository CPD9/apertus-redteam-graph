export const LANGS = ["en", "de", "gsw", "fr", "it", "rm"];
export const LANG_NAMES = {en: "English", de: "German", gsw: "Swiss German", fr: "French", it: "Italian",
                           rm: "Romansh"};

export const $ = selector => document.querySelector(selector);
export const pct = rate => Math.round(rate * 100) + "%";
export const flatten = s => String(s ?? "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();

const ENTITIES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"};
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ENTITIES[c]);

export function clip(s, max) {
  if (s.length <= max) return s;
  const cut = s.lastIndexOf(" ", max);
  return s.slice(0, cut > max * .7 ? cut : max).replace(/[\s,;:.]+$/, "") + "…";
}

// The banks give every hypothesis a short title; older runs may name one that has left the banks.
export function titleOf(id, hypotheses) {
  const words = String(id).replace(/_/g, " ");
  return hypotheses[id]?.title || words[0].toUpperCase() + words.slice(1);
}

// What the graph tab's status pills and the heatmap's row notes mean.
export const STATUS_TIPS = {
  no_issue: "The judge flagged no answer in any attempt.",
  not_reproducible: "Flagged once, but too few of the verifier's answers were flagged.",
  below_bar: "Enough answers were flagged, but too few count: the rest were rated severity 0.",
};

// Marks a hypothesis the server could not recount by the severity rule.
export const UNCOUNTED = '<span class="tag" data-tip="Its answers could not be replayed from the LLM cache, ' +
  'so its numbers count every answer the judge flagged, also those it rated severity 0.">uncounted</span>';
