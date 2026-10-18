import {clip, esc, flatten} from "./text.js";

const QUOTE_MARKS = /^[\s"'„“”«»‚‘’]+|[\s"'„“”«»‚‘’.]+$/g;

// The strategy of every hypothesis's last attack, and its prompt, answer and judge verdict per language.
export function attacks(events) {
  const out = {};
  for (const e of events) {
    const d = e.data || {}, attack = out[e.hypothesis];
    if (e.status !== "done") continue;
    if (e.node === "attacker") out[e.hypothesis] = {strategy: d.strategy, prompts: {}, answers: {}, verdicts: {}};
    else if (attack && e.node === "mutator") attack.prompts = d.prompts || {};
    else if (attack && e.node === "target") attack.answers[d.lang] = d.answer || "";
    else if (attack && e.node === "judge") attack.verdicts[d.lang] = d;
  }
  return out;
}

// The log cuts every long answer at the same length. Several different answers of exactly the
// longest length show where; one answer repeated, as canned ones are, shows nothing.
export function logCap(attacksById) {
  const texts = Object.values(attacksById).flatMap(a => Object.values(a.answers));
  const top = Math.max(0, ...texts.map(s => s.length));
  return new Set(texts.filter(s => s.length === top)).size > 1 ? top : Infinity;
}

// Answers and quotes differ in apostrophes and letter case more often than in words.
const loose = s => flatten(s).replace(/[‘’]/g, "'");
const pattern = quote => new RegExp(quote.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");

// The judge may quote several passages at once; short fragments match too easily to count.
function quotes(evidence) {
  return String(evidence || "").split(/;|…|\.\.\./)
    .map(q => loose(q).replace(QUOTE_MARKS, ""))
    .filter(q => q.length >= 12);
}

// A quote only counts when it is in the answer and is not the user's own wording repeated back.
function locate(prompt, answer, evidence) {
  const said = loose(answer), asked = loose(prompt);
  return quotes(evidence).find(q => pattern(q).test(said) && !pattern(q).test(asked)) || "";
}

// Picks the flagged answer that shows the problem best. It is "quoted" when the judge's quote is in
// the answer and the judge rated it above severity 0; anything else needs a human look. english is
// the same attack's question in English, for readers of the other five languages.
export function pickEvidence(attack) {
  const english = attack?.prompts.en || "";
  const flagged = Object.entries(attack?.verdicts || {}).filter(([, v]) => v.violation).map(([lang, v]) => {
    const prompt = attack.prompts[lang] || "", answer = attack.answers[lang] || "";
    const quote = locate(prompt, answer, v.evidence);
    return {lang, prompt, english, answer, verdict: v, quote, quoted: Boolean(quote) && v.severity > 0};
  });
  const severity = x => x.verdict.severity || 0;
  flagged.sort((a, b) => b.quoted - a.quoted || Boolean(b.quote) - Boolean(a.quote)
                         || severity(b) - severity(a));
  return flagged[0] || null;
}

// Escaped HTML: the sentence that leads into the quote, the quote marked, then the answer goes on.
export function excerptHtml(answer, quote) {
  const text = loose(answer), m = quote ? text.match(pattern(quote)) : null;
  if (!m) return esc(clip(text, 280));
  const dot = text.lastIndexOf(". ", m.index);
  const sentence = dot < 0 ? 0 : dot + 2;
  const from = m.index - sentence > 120 ? m.index : sentence;
  const before = text.slice(from, m.index), after = text.slice(m.index + m[0].length);
  return (from ? "…" : "") + esc(before) + `<mark>${esc(m[0])}</mark>`
    + esc(clip(after, Math.max(40, 280 - before.length - m[0].length)));
}
