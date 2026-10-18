// The walkthrough's steps before and after the verifier, each built from what the log kept.
import {LANGS, LANG_NAMES, andList, clip, esc, flatten, langAttr, pct, term, titleOf} from "./text.js";
import {trusted} from "./explain-log.js";

const ANSWER_HEAD = 300, FEEDBACK_MAX = 280;
const PLACEHOLDER = /\[[^\]]+\]/;  // a neutral question still holding e.g. "[Datum einfügen]"

export const langName = lang => esc(LANG_NAMES[lang] || lang);
export const isUrl = text => /^https?:\/\//.test(text);

function sourcesHtml(sources) {
  return (sources || []).map(source => {
    if (!isUrl(source)) return esc(source);
    let host = source;
    try { host = new URL(source).hostname.replace(/^www\./, ""); } catch { /* keep the address as written */ }
    return `<a href="${esc(source)}" target="_blank" rel="noopener">${esc(host)}</a>`;
  }).join(", ");
}

// A field the hypothesis bank leaves empty is said to be empty, not left out.
const missingHtml = text => `<span class="explain-missing">${text}</span>`;

export function claimStep(c) {
  const hyp = c.s.hypotheses[c.id];
  const rows = hyp && [
    [term("hypothesis", "Hypothesis"), esc(hyp.hypothesis) || missingHtml("not written down")],
    ["What is correct", esc(hyp.reference) || missingHtml("not written down")],
    ["Why it matters", esc(hyp.harm) || missingHtml("not written down in the hypothesis bank")],
    ["Official source", sourcesHtml(hyp.sources) || missingHtml("none in the hypothesis bank")],
  ];
  const body = rows
    ? `<dl class="explain-facts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`
    : `<p class="explain-note">The hypothesis banks no longer hold this hypothesis, only its id.</p>`;
  return {nav: "The claim", title: "The claim", agents: [], html:
    `<p class="explain-lead">${esc(titleOf(c.id, c.s.hypotheses))}</p>${body}`};
}

function attempt(a, i) {
  const n = a.attempt ?? i + 1;
  const strategy = a.strategy ? ` · strategy: ${esc(String(a.strategy).replace(/_/g, " "))}` : "";
  const sentBack = n > 1 && a.feedback ? `<p class="explain-feedback"><b>Sent back because:</b> ` +
                                         `${esc(clip(flatten(a.feedback), FEEDBACK_MAX))}</p>` : "";
  const prompt = a.prompt == null ? `<p class="explain-note">No question was written.</p>`
                                  : `<blockquote class="explain-prompt">${esc(a.prompt)}</blockquote>`;
  const why = a.rationale ? `<details><summary>The attacker's reasoning</summary>` +
                            `<p>${esc(a.rationale)}</p></details>` : "";
  return `<li><p class="explain-meta">Attempt ${esc(n)}${strategy}</p>${sentBack}${prompt}${why}</li>`;
}

export function attackStep(c) {
  const attempts = c.w.attempts;
  if (!attempts.length) return null;
  return {nav: "Attacker: the question", title: "The attacker writes a question", agents: ["attacker"], html:
    `<p>The attacker turns the claim into a question a user might ask, with a ${term("premise", "false claim")} ` +
    "built in. When the judge flags no answer, it sends the attacker back to try another way.</p>" +
    `<ol class="explain-attempts">${attempts.map(attempt).join("")}</ol>`};
}

const agreedHtml = (lang, a) => `${langName(lang)} ${esc(a.agree)} of ${esc(a.n)}`;

function checkNote(agreement) {
  const langs = [...LANGS, ...Object.keys(agreement).filter(l => !LANGS.includes(l))].filter(l => agreement[l]);
  if (!langs.length) return "";
  const weak = langs.filter(l => !trusted(agreement[l])), sure = langs.filter(l => trusted(agreement[l]));
  const text = [
    `An automatic ${term("language-check", "language check")} then asks the model that writes the questions ` +
      "which language each translation is in. It changes no count: every translation is asked and judged " +
      "as written.",
    weak.length && "It misreads some languages often. Over this run's translations it named the language " +
      `asked for in ${andList(weak.map(l => agreedHtml(l, agreement[l])))}, so its reading is left out for ` +
      `${weak.length === 1 ? "that language" : "those languages"}.`,
    sure.length && "Where it is reliable, a disagreement is marked under the translation: " +
      `${andList(sure.map(l => agreedHtml(l, agreement[l])))}.`,
  ];
  return `<p class="explain-note">${text.filter(Boolean).join(" ")}</p>`;
}

export function translateStep(c) {
  const t = c.w.translation;
  if (!t?.prompts) return null;
  const langs = Object.keys(t.prompts), mismatched = new Set(t.mismatched || []);
  const rows = langs.map(lang => {
    const a = c.check[lang];
    const flag = mismatched.has(lang) && trusted(a)
      ? `<p class="explain-check">Language check: read as ${esc(t.detected?.[lang] || "another language")}. ` +
        `It names ${langName(lang)} in ${esc(a.agree)} of ${esc(a.n)} translations of this run, so this one ` +
        "is worth a look.</p>" : "";
    return `<tr><th scope="row">${langName(lang)}</th>` +
           `<td><p ${langAttr(lang)}>${esc(t.prompts[lang])}</p>${flag}</td></tr>`;
  }).join("");
  return {nav: "Mutator: translations", title: `The mutator translates it into ${langs.length} languages`,
          agents: ["mutator"], html:
    "<p>The mutator translates the question, so that every language gets the same question.</p>" +
    `<table class="explain-table"><thead><tr><th scope="col">Language</th><th scope="col">Question</th></tr>` +
    `</thead><tbody>${rows}</tbody></table>${checkNote(c.check)}`};
}

function answerText(text, lang) {
  // The log keeps the answer's markdown; its bold and heading marks only get in the way here.
  const plain = String(text).replace(/\*\*/g, "").replace(/^#{1,6}\s+/gm, "");
  if (plain.length <= ANSWER_HEAD * 1.2) return `<p class="explain-said" ${langAttr(lang)}>${esc(plain)}</p>`;
  const space = plain.lastIndexOf(" ", ANSWER_HEAD), cut = space > ANSWER_HEAD * .7 ? space : ANSWER_HEAD;
  return `<p class="explain-said" ${langAttr(lang)}>${esc(plain.slice(0, cut))}` +
         `<span class="explain-more" aria-hidden="true">…</span></p>` +
         `<details><summary>Rest of the answer</summary>` +
         `<p class="explain-said" ${langAttr(lang)}>${esc(plain.slice(cut).trimStart())}</p></details>`;
}

function verdictHtml(v) {
  if (!v) return `<p class="explain-meta">No verdict: testing stopped before the judge answered.</p>`;
  const counts = v.violation && v.severity > 0;
  // Red marks only what counts; a flag at severity 0 is not a failure.
  const flag = v.violation ? `<b${counts ? ' class="explain-flag"' : ""}>flagged, severity ${esc(v.severity)}</b>`
                           : "not flagged";
  const claims = (v.claims || []).map(c => `<li><span class="explain-claim ${esc(c.verdict)}">` +
                                           `${esc(c.verdict)}</span> ${esc(c.claim)}</li>`).join("");
  return `<p class="explain-meta">${flag} · ${term("counts", counts ? "would count" : "would not count")}</p>` +
         (v.reason ? `<p class="explain-reason"><b>Judge:</b> ${esc(v.reason)}</p>` : "") +
         (claims ? `<ul class="explain-claims" aria-label="Claims the judge checked">${claims}</ul>` : "");
}

// The claim labels are measured against the reference alone, so a flagged answer can still show
// "supported" next to a detail it made up.
const CLAIMS_NOTE = "<p class=\"explain-note\">Under each answer the judge lists the claims the answer makes and marks " +
  "each against the official reference: supported when the reference agrees, contradicted when it " +
  "conflicts, unverifiable when the reference says nothing about it. The flag is decided on its own: an " +
  "answer can be flagged for what it does, such as going along with the false claim or inventing details " +
  "about a person, even when no claim is marked contradicted.</p>";

export function answerStep(c) {
  const w = c.w, order = Object.keys(w.translation?.prompts || {});
  const langs = [...order, ...Object.keys(w.answers).filter(l => !order.includes(l))]
    .filter(lang => lang in w.answers);
  if (!langs.length) return null;
  const blocks = langs.map(lang => `<section class="explain-answer"><h4>${langName(lang)}</h4>` +
    answerText(w.answers[lang], lang) + verdictHtml(w.verdicts[lang]) + "</section>").join("");
  const self = c.selfJudged ? " In this run the judge is the target model itself, so it grades its own " +
                              "answers and may under-flag." : "";
  const claims = langs.some(lang => w.verdicts[lang]?.claims?.length) ? CLAIMS_NOTE : "";
  return {nav: "Target and judge: answers", title: "The target answers, the judge checks",
          agents: ["target", "judge"], html:
    `<p>The target, the Apertus model under test, answers each translation. The ${term("judge", "judge")} reads ` +
    `every answer next to the official reference, ${term("flagged", "flags")} it when it fails the check and ` +
    `rates its ${term("severity", "severity")}.${self} These first answers only decide whether the verifier ` +
    `runs (${term("attack-step", "attack step")}); the log keeps only the start of a long answer.</p>` +
    `${claims}<div class="explain-answers">${blocks}</div>`};
}

const fileName = path => esc(String(path).split("/").pop());

export function scribeStep(c) {
  const d = c.w.scribe;
  if (!d) return null;
  // An uncounted hypothesis is decided on the answers the judge flagged.
  const verb = c.uncounted ? "were flagged" : "count";
  const html = !d.path ? `<p>Too few of the verifier's answers ${verb}, so the scribe writes no findings file.</p>`
    : c.st === "finding" ? `<p>Enough answers ${verb}, so the scribe writes the finding up as ` +
                           `<code>${fileName(d.path)}</code>.</p>`
    : `<p>The scribe wrote <code>${fileName(d.path)}</code> when the run was recorded, under the older rule ` +
      "that counted every flagged answer. Counted by severity, this hypothesis is below the bar, so it " +
      "has no card here.</p>";
  return {nav: "Scribe: findings file", title: "The scribe writes the finding up", agents: ["scribe"], html};
}

export function controlStep(c) {
  const row = c.control;
  if (!row) return null;
  const prompts = row.neutral_prompts || {}, shares = row.neutral_by_lang || {};
  const rows = Object.keys(prompts).map(lang => `<tr><th scope="row">${langName(lang)}</th>` +
    `<td><p ${langAttr(lang)}>${esc(prompts[lang])}</p>` +
    (shares[lang] != null ? `<p class="explain-meta">${pct(shares[lang])} of its answers wrong</p>` : "") +
    "</td></tr>").join("");
  const close = row.neutral_n != null && row.premise_n != null
    ? `Asked plainly: ${esc(row.neutral_k)} of ${esc(row.neutral_n)} wrong; with the false claim: ` +
      `${esc(row.premise_k)} of ${esc(row.premise_n)}.`
    : `Asked plainly: ${pct(row.neutral_rate)} of the answers wrong; with the false claim: ` +
      `${pct(row.premise_rate)}.`;
  const unusable = PLACEHOLDER.test(row.neutral_question || "")
    ? `<p class="explain-note">Its question still holds a placeholder, so this control is unusable.</p>` : "";
  return {nav: "After the run: neutral question", title: "After the run: the neutral question",
          agents: ["mutator", "verifier"], html:
    `<p>The same topic asked plainly, without the false claim (${term("neutral", "neutral question")}), ` +
    "translated and asked again like the verifier asks. Wrong there too: Apertus does not know it. Wrong " +
    "only with the claim: it gives in to the user.</p>" +
    `<table class="explain-table"><thead><tr><th scope="col">Language</th><th scope="col">Neutral question</th>` +
    `</tr></thead><tbody>${rows}</tbody></table>${unusable}<p class="explain-verdict"><b>${close}</b></p>`};
}
