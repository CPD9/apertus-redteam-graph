import {clip, esc, flatten} from "./text.js";

const QUOTE_MARKS = /^[\s"'„“”«»‚‘’]+|[\s"'„“”«»‚‘’.]+$/g;

// The prompt, answer and judge verdict of every hypothesis's last attack, per language.
export function attacks(events) {
  const out = {};
  for (const e of events) {
    const d = e.data || {}, attack = out[e.hypothesis];
    if (e.status !== "done") continue;
    if (e.node === "mutator") out[e.hypothesis] = {prompts: d.prompts || {}, answers: {}, verdicts: {}};
    else if (attack && e.node === "target") attack.answers[d.lang] = d.answer || "";
    else if (attack && e.node === "judge") attack.verdicts[d.lang] = d;
  }
  return out;
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

// Picks the flagged answer that shows the problem best. It is "confirmed" when the judge's quote is
// in the answer and the judge rated it above severity 0; anything else needs a human look.
export function pickEvidence(attack) {
  const flagged = Object.entries(attack?.verdicts || {}).filter(([, v]) => v.violation).map(([lang, v]) => {
    const prompt = attack.prompts[lang] || "", answer = attack.answers[lang] || "";
    const quote = locate(prompt, answer, v.evidence);
    return {lang, prompt, answer, verdict: v, quote, confirmed: Boolean(quote) && v.severity > 0};
  });
  const severity = x => x.verdict.severity || 0;
  flagged.sort((a, b) => b.confirmed - a.confirmed || Boolean(b.quote) - Boolean(a.quote)
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
