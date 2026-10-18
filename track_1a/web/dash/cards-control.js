import {LANGS, LANG_NAMES, clip, esc, flatten, langAttr, pct, sum, term} from "./text.js";

const PLACEHOLDER = /\[[^\]]+\]/;  // a neutral question still holding e.g. "[Datum einfügen]"

// Compares the neutral control with the false-claim answers by their 95% intervals, not their rates:
// with 18 answers each, 17% against 39% is not a difference. When the two overlap and even the plain
// question's lower bound clears the bar, Apertus fails without the claim too.
export function premiseEffect(control, premiseCi, minRate) {
  if (PLACEHOLDER.test(control.neutral_question)) return "unusable";
  const [lo, hi] = control.neutral_ci95 || [control.neutral_rate, control.neutral_rate];
  const [premiseLo, premiseHi] = premiseCi || [control.premise_rate, control.premise_rate];
  if (hi < premiseLo) return "premise";
  if (lo > premiseHi) return "neutral";
  return minRate != null && lo >= minRate ? "unknown" : "unclear";
}

// What the attack adds to the plain question. Most attacks build in a false claim; a few frame the
// question another way (a practical need, a role) and have none.
export const framing = strategy => strategy === "false_premise" ? "the false claim" : "the attack's framing";

// How the reproduced cards came out against the neutral question, for the lines above them.
export function controlTally(cards) {
  const checked = cards.filter(x => x.effect && x.effect !== "unusable");
  const count = effect => checked.filter(x => x.effect === effect).length;
  const premise = checked.every(x => x.strategy === "false_premise");
  return {checked: checked.length, worse: count("premise"), without: count("unknown"),
          what: premise ? "the false claim" : "the attack's framing"};
}

// Two ranges whose facing ends round to the same percent look as if they touch; one decimal tells
// them apart.
function ranges(a, b) {
  const whole = x => Math.round(x * 100);
  const close = whole(a[1]) === whole(b[0]) || whole(a[0]) === whole(b[1]);
  const show = x => close ? (x * 100).toFixed(1) : String(whole(x));
  return `${show(a[0])}–${show(a[1])}% vs ${show(b[0])}–${show(b[1])}%`;
}

// The neutral question in English, and as it was first written when that is another language.
function neutralAsked(c) {
  const original = flatten(c.neutral_question), english = flatten(c.neutral_prompts?.en);
  const lang = LANGS.find(l => flatten(c.neutral_prompts?.[l]) === original);
  const first = `<q${lang ? " " + langAttr(lang) : ""}>${esc(original)}</q>`;
  if (!english || lang === "en") return first;
  const how = lang ? `first written in ${esc(LANG_NAMES[lang])}` : "as first written";
  return `<q>${esc(english)}</q> (${how}: ${first})`;
}

// One plain answer from a language where the judge flagged all of them. neutral_by_lang is the
// flagged share, from before the recount drops answers rated severity 0, so "counted" holds only
// when the flags add up to the counted total.
function plainExample(c) {
  const answers = c.neutral_answers || {}, flagged = c.neutral_by_lang || {};
  const all = LANGS.filter(l => flagged[l] === 1 && answers[l]?.length);
  const lang = all.includes("en") ? "en" : all[0];
  if (!lang) return "";
  const flags = sum(LANGS.map(l => Math.round((flagged[l] || 0) * (answers[l]?.length || 0))));
  const name = esc(LANG_NAMES[lang]);
  const lead = flags === c.neutral_k ? `Every plain answer in ${name} counted as wrong`
    : `The judge flagged every plain answer in ${name}`;
  return `<p class="plain">${lead}, for example: ` +
         `<q ${langAttr(lang)}>${esc(clip(flatten(answers[lang][0]), 260))}</q></p>`;
}

export function controlLine(x) {
  const c = x.control;
  if (!c) return "";
  const asked = `<p class="asked">${term("neutral", "Asked plainly")}: ${neutralAsked(c)}</p>`;
  if (x.effect === "unusable") {
    return `<div class="ctl"><p><b>Neutral question unusable:</b> it still holds a placeholder.</p>` +
           `${asked}</div>`;
  }
  const counted = c.neutral_n && c.premise_n;
  const plain = counted ? `${Number(c.neutral_k)} of ${Number(c.neutral_n)}` : pct(c.neutral_rate);
  const claim = counted ? `${Number(c.premise_k)} of ${Number(c.premise_n)}` : pct(x.overall);
  const noun = counted ? "answers" : "of answers";
  const both = c.neutral_ci95 && x.ci ? ranges(c.neutral_ci95, x.ci) : "";
  const ci = both ? ` (${term("ci", "95% CI")} ${both})` : "";
  const what = framing(x.strategy);
  // A plain question can leave out what the attack named (a country, a year), so failing it does
  // not prove that Apertus lacks the fact: the line gives the numbers and the question, not a cause.
  const text = {
    premise: `<b>Gives in to ${what}:</b> asked plainly, ${plain} ${noun} were wrong; with ${what}, ` +
             `${claim}${ci}.`,
    neutral: `<b>Worse when asked plainly:</b> ${plain} ${noun} wrong vs ${claim} with ${what}${ci}.`,
    unknown: `<b>Wrong without ${what} too:</b> ${plain} ${noun} wrong asked plainly, ${claim} with ` +
             `${what}${ci}.`,
    unclear: `<b>Not clearly different:</b> ${plain} ${noun} wrong asked plainly, ${claim} with ${what}. ` +
             (both ? `The ${term("ci", "95% ranges")}, ${both}, overlap, so the difference may be chance.`
                   : "The difference may be chance."),
  }[x.effect];
  return `<div class="ctl"><p>${text}</p>${asked}${x.effect === "unknown" ? plainExample(c) : ""}</div>`;
}
