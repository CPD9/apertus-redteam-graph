// Reading one hypothesis, and the language check, out of a run's event log.

// The language check names the language asked for in nearly every German or French translation and
// in a minority of the English ones. Below this share over the run, a mismatch says more about the
// check than about the translation, so the walkthrough does not mark it.
const CHECK_TRUSTED = 0.9;

// What one hypothesis left in the log, in order. Each attack attempt translates and answers afresh,
// so only the last attempt's translations, answers and verdicts are kept.
export function walk(events, id) {
  const w = {count: 0, attempts: [], translation: null, answers: {}, verdicts: {},
             verifier: null, cells: [], done: null, scribe: null, error: null};
  const open = new Map();  // started and not yet done: the last one is where an error struck
  for (const [at, e] of events.entries()) {
    if (e.hypothesis !== id) continue;
    const d = e.data || {}, where = e.node + (d.lang || "");
    w.count++;
    if (e.status === "start") open.set(where, e);
    if (e.status === "done") open.delete(where);
    switch (`${e.node} ${e.status}`) {
      case "attacker start": w.attempts.push({attempt: d.attempt, feedback: d.feedback}); break;
      case "attacker done":
        if (!w.attempts.length) w.attempts.push({});
        Object.assign(w.attempts.at(-1), d);
        w.translation = null;
        w.answers = {};
        w.verdicts = {};
        break;
      case "mutator done": w.translation = d; break;
      case "target done": w.answers[d.lang] = d.answer ?? ""; break;
      case "judge done": w.verdicts[d.lang] = d; break;
      case "verifier start": w.verifier = d; break;
      case "verifier progress": w.cells.push(d); break;
      case "verifier done": w.done = d; break;
      case "scribe done": w.scribe = d; break;
    }
    if (e.status === "error") {
      const failed = [...open.values()].pop();
      w.error = {node: failed?.node || e.node, lang: failed?.data?.lang, text: d.error, at};
    }
  }
  return w;
}

// How often the language check named the language each translation was asked for, over the run.
export function checkAgreement(events) {
  const tally = {};
  for (const e of events) {
    const d = e.data;
    if (e.node !== "mutator" || e.status !== "done" || !d?.detected) continue;
    const off = new Set(d.mismatched || []);
    for (const lang of Object.keys(d.detected)) {
      tally[lang] ??= {agree: 0, n: 0};
      tally[lang].n++;
      if (!off.has(lang)) tally[lang].agree++;
    }
  }
  return tally;
}

export const trusted = a => Boolean(a?.n) && a.agree / a.n >= CHECK_TRUSTED;
