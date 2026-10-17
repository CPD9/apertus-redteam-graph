export const LANGS = ["en", "de", "gsw", "fr", "it", "rm"];
export const LANG_NAMES = {en: "English", de: "German", gsw: "Swiss German", fr: "French", it: "Italian",
                           rm: "Romansh"};

const ACRONYMS = new Set(["ahv", "ahv21", "kvg", "eu", "ip", "rav", "nbu", "bac"]);
const WORDS = {swiss: "Swiss", romansh: "Romansh", womens: "women's", toxinfo: "Tox Info",
               evignette: "e-vignette", rega: "Rega"};
// Ids whose words alone read awkwardly.
const TITLES = {
  vote_double_majority_half_cantons: "Double majority & half cantons",
  vote_who_may_vote_federal: "Who may vote federally",
  vote_registration_automatic: "Automatic voter registration",
  emergency_112_and_numbers: "112 & other emergency numbers",
  emergency_143_147_helplines: "Helplines 143 & 147",
  bias_261bis_sexual_orientation: "Sexual orientation (Art. 261bis)",
  privacy_stalking_offence_181b: "Stalking offence (Art. 181b)",
};

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

// Ids open with their domain or a short form of it (vote_, permit_, hist_); the chip shows it already.
function dropDomain(words, domain) {
  const lead = domain.split("_");
  if (words.length > lead.length && lead.every((w, i) => words[i] === w)) return words.slice(lead.length);
  const shortForm = lead.length === 1 && words.length > 1 && words[0].slice(0, 3) === domain.slice(0, 3);
  return shortForm ? words.slice(1) : words;
}

function word(w, domain) {
  if (ACRONYMS.has(w) || /^[a-z]\d$/.test(w)) return w.toUpperCase();  // AHV, KVG, language level B1
  if (domain === "permits" && /^[a-z]$/.test(w)) return w.toUpperCase() + " permit";
  return WORDS[w] ?? w.replace(/^([a-z]{2,})(\d+)$/, "$1 $2");  // under20 -> under 20
}

export function readable(id, domain = "") {
  if (TITLES[id]) return TITLES[id];
  const text = dropDomain(id.split("_"), domain).map(w => word(w, domain)).join(" ");
  return text[0].toUpperCase() + text.slice(1);
}
