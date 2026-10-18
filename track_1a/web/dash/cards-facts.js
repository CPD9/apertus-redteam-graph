import {esc, pct, term} from "./text.js";
import {controlTally} from "./cards-control.js";

// Landis and Koch's words for bands of Cohen's kappa.
export function band(kappa) {
  if (kappa < 0) return "poor";
  return [[.2, "slight"], [.4, "fair"], [.6, "moderate"], [.8, "substantial"]]
    .find(([upTo]) => kappa <= upTo)?.[1] || "almost perfect";
}

// The intervals on the cards come from resampling answers; how far the judge itself can be trusted
// is a separate matter, which this says where it says how far a second judge agrees.
function judges(rejudge) {
  const kappa = rejudge.kappa;
  const chance = kappa == null ? "" : `; beyond chance that is ${band(kappa)} agreement ` +
                                      `(${term("kappa", `κ ${kappa.toFixed(2)}`)})`;
  return `a second ${term("judge", "judge")} agrees with the first on ${pct(rejudge.raw_agreement)} ` +
         `of ${Number(rejudge.n)} answers${chance}. The ${term("ci", "95% intervals")} cover sampling ` +
         "only, not the judge's own errors";
}

// A check the run has not had yet, and the command that adds it. Both commands refuse the recorded
// copies in data/runs/, which ship with the repository: the control runs only on a run made on this
// machine, and the second judge on a copy of the folder in runs/. folder is the server's run_folder;
// without it the command is left out, since it might fail.
function notYet(what, module, run) {
  const command = `<code>PYTHONPATH=src python3 -m redteam.${module} --run ${esc(run.runId)}</code>`;
  const folder = run.runFolder || "";
  if (folder.startsWith("runs/")) return `${what}: ${command}`;
  if (!folder.startsWith("data/runs/")) return what;
  return module === "rejudge"
    ? `${what}: copy <code>${esc(folder)}</code> to <code>runs/</code> first, then ${command}`
    : `${what}; it runs only on a run made on this machine, not on the recorded copy in ` +
      `<code>${esc(folder)}</code>`;
}

// The line above the cards. run: planned holds the ids of the run's hypotheses, finished how many of
// them have ended.
export function factsHtml(cards, run) {
  const planned = run.planned.length, finished = run.finished, done = finished >= planned;
  // The checks that come after a run only make sense once it has ended, and not on canned answers.
  const offer = done && run.runId && !run.mock;
  const total = cards.length, quoted = cards.filter(x => x.evidence?.quoted).length;
  const answer = run.mock ? "the canned answer" : "Apertus' answer";
  const parts = [done ? `<b>${total}</b> of ${planned} hypotheses reproduced`
    : `<b>${total}</b> reproduced so far · ${finished} of ${planned} hypotheses tested`];
  if (run.mock) parts.unshift("<b>Mock results</b>, not findings about Apertus");
  if (total) {
    const unchecked = total - quoted;
    const rest = !unchecked ? "none needs a human check"
      : `${unchecked} ${unchecked === 1 ? "needs" : "need"} a human check`;
    parts.push(`<b>${quoted}</b> with the judge's quote found in ${answer} (automatic match), ${rest}`);
  }
  const tally = controlTally(cards);
  if (tally.checked) {
    parts.push(`of ${tally.checked} checked against a ${term("neutral", "neutral question")}, ` +
               `${tally.what} clearly makes it worse in <b>${tally.worse}</b>; <b>${tally.without}</b> ` +
               `${tally.without === 1 ? "is" : "are"} wrong without it too`);
  } else if (offer && run.control && !Object.keys(run.control).length) {
    parts.push(notYet("No neutral-question check in this run yet", "control", run));
  }
  if (run.rejudge?.n) parts.push(judges(run.rejudge));
  else if (offer && run.rejudge === null) {
    parts.push(notYet("No second judge yet", "rejudge", run));
  }
  if (run.humanLabels === 0) {
    const review = "review.html" + (run.runId ? "?run=" + encodeURIComponent(run.runId) : "");
    parts.push(`<a href="${esc(review)}">No human labels yet</a>`);
  }
  return parts.filter(Boolean).join(" · ");
}
