// The submitted findings: what the team sent in, from findings/*.json.
import {$, CHECK_TIP, esc, pct, short, sum, term, titleOf} from "./text.js";
import {pickEvidence} from "./evidence.js";
import {range} from "./heat.js";

const DIALECTS = {ag: "Aargau", be: "Bern", bs: "Basel", gr: "Graubünden", lu: "Lucerne", sg: "St. Gallen",
                  vs: "Valais", zh: "Zurich", all: "All dialects"};
// A step reads "<what to do>: <command>"; the command starts with a program or with the variables
// set for it. Only the command belongs on the clipboard.
const COMMAND = /(?:^|:\s)((?:[A-Z][A-Z_]*=\S+\s+)*(?:python3?|for|export)\s.*)$/;
// One step can hold two places to run something: "On the pod: …; locally: …".
const PLACES = /;\s+(?=\w+:\s)/;
// Some steps go on after the command with what it does: "… --judge writes runs/…".
const GOES_ON = /\s(?=(?:writes|recomputes)\s)/;

// A difference in percentage points; a range that crosses zero reads "−39 to +33", not "-39–33".
const points = d => Math.round(d * 100);
const signed = d => (points(d) > 0 ? "+" : "") + String(points(d)).replace("-", "−");
const pointRange = ([lo, hi]) =>
  points(lo) >= 0 ? `${points(lo)}–${points(hi)}` : `${signed(lo)} to ${signed(hi)}`;
const runLink = id => `<a href="?tab=findings&amp;run=${esc(encodeURIComponent(id))}">${esc(id)}</a>`;

// The closed card. A summary is one button, so these lines hold no links.
function submittedLines(e) {
  const vars = e.variations || [], c = e.control, r = e.replication, all = e.unrelated?.all;
  const version = String(e.model_version ?? "").slice(0, 7);
  const share = x => `${Number(x.k)} of ${Number(x.n)} (${pct(x.rate)}` +
                     (x.ci95 ? `, 95% CI ${range(x.ci95)})` : ")");
  // The speech answers share speakers and sentences, so they are not independent: an interval that
  // treats them so is too narrow. Only the one that resamples speakers and sentences is shown.
  const unrelated = x => `${Number(x.k)} of ${Number(x.n)} (${pct(x.rate)}` +
    (x.cluster_ci95 ? `, 95% CI ${range(x.cluster_ci95)} over speakers and sentences)` : ")");
  return [
    `<span class="subfile">findings/${esc(e.file)} · ${esc(short(e.model))} ${esc(version)}</span>`,
    vars.length && `<b>${sum(vars.map(v => v.k))} of ${sum(vars.map(v => v.n))}</b> answers failed ` +
                   `(${pct(e.overall_rate)}${e.overall_ci95 ? `, 95% CI ${range(e.overall_ci95)}` : ""})`,
    all && `Unrelated to the recording: Apertus <b>${unrelated(all.apertus)}</b>, ` +
           `Whisper ${unrelated(all.whisper)}`,
    c && `With the false claim ${Number(c.premise.k)}/${Number(c.premise.n)}, asked plainly ` +
         `${Number(c.neutral.k)}/${Number(c.neutral.n)}` + (c.premise_minus_neutral_ci95
           ? `; the false claim adds ${pointRange(c.premise_minus_neutral_ci95)} points (95% CI)` : ""),
    r && `On ${esc(short(r.model))}: ${share(r)}, ${(r.variations_reproduced || []).length} of ` +
         `${(r.variations_measured || []).length} variations reproduced`,
    `Team's own rubric score, not the judge's 0–10 severity: severity ${esc(e.severity)}, ` +
      `breadth ${esc(e.breadth)}`,
  ].filter(Boolean).map(line => `<span class="line">${line}</span>`).join("");
}

// Which run and files the numbers come from, each run a link that switches to it.
function sourceLine(e) {
  if (e.unrelated || !e.run_id) return "";
  const files = e.control ? "its events.jsonl and control.json" : "its events.jsonl";
  const replication = e.replication?.run_id ? `; replication run ${runLink(e.replication.run_id)}` : "";
  return `<p class="subnote">Numbers from run ${runLink(e.run_id)} (${files})${replication}.</p>`;
}

// On the run the finding cites, a variation whose example needs a human look says so, as its card does.
function variationLinks(e, run) {
  const here = run.runId === e.run_id;
  const link = v => here ? `href="#f-${esc(v.id)}" data-open="${esc(v.id)}"`
    : `href="?tab=findings&amp;run=${esc(encodeURIComponent(e.run_id))}#f-${esc(encodeURIComponent(v.id))}"`;
  const check = v => here && run.attacks?.[v.id] && !pickEvidence(run.attacks[v.id])?.quoted
    ? ` <span class="tag" tabindex="0" data-tip="${esc(CHECK_TIP)}">needs a check</span>` : "";
  const item = v => `<li><span><a ${link(v)}>${esc(titleOf(v.id, run.hypotheses))}</a>${check(v)}</span> ` +
                    `<span class="k">${Number(v.k)}/${Number(v.n)}</span></li>`;
  return `<ul class="vars">${e.variations.map(item).join("")}</ul>`;
}

// A phone wraps a command only between words, or after a "/" or "=" inside a long one, never in
// the middle of "python3" or "--write". <wbr> holds no text, so the clipboard gets the command as is.
function commandHtml(command) {
  const piece = text => `<span>${esc(text)}</span>`;
  const word = w => w.length > 24 ? w.split(/(?<=[/=])/).map(piece).join("<wbr>") : piece(w);
  return command.split(" ").map(word).join(" ");
}

// Prose left in a command would break it in a shell: a comma before a word, a closing period, or a
// quote left open, as in "model.parameters' unrelated".
const prose = command => /,\s+\w|\.$/.test(command) || (command.match(/'/g) || []).length % 2 === 1;

function place(text) {
  const m = text.match(COMMAND), cut = m ? m[1].search(GOES_ON) : -1;
  const command = m && (cut < 0 ? m[1] : m[1].slice(0, cut));
  if (!m || prose(command)) return `<p>${esc(text)}</p>`;
  const what = text.slice(0, m.index + (m[0].length - m[1].length)).trim();
  const after = cut < 0 ? "" : m[1].slice(cut + 1);
  return `<div class="cmd">${what ? `<p>${esc(what)}</p>` : ""}<code>${commandHtml(command)}</code>
    <p class="copyrow"><button type="button" data-copy>Copy</button> <span role="status"></span></p>
    ${after ? `<p class="does">The command ${esc(after)}</p>` : ""}</div>`;
}

function step(text) {
  const places = text.split(PLACES).map((part, i) => i ? part[0].toUpperCase() + part.slice(1) : part);
  return `<li>${places.map(place).join("")}</li>`;
}

function reproduce(e) {
  const steps = e.reproduce || [];
  return steps.length ? `<div class="repro"><h4>Reproduce</h4><ol>${steps.map(step).join("")}</ol></div>` : "";
}

function dialectTable(e) {
  const share = x => `${Number(x.k)}/${Number(x.n)}`;
  // The pooled row, "all", goes last.
  const rows = Object.entries(e.unrelated).sort(([a], [b]) => (a === "all") - (b === "all")).map(([d, x]) =>
    `<tr${d === "all" ? ' class="total"' : ""}><th scope="row">${esc(DIALECTS[d] || d)}</th>` +
    `<td>${share(x.apertus)}</td><td>${share(x.whisper)}</td></tr>`).join("");
  return `<table class="dialects"><thead><tr><th scope="col">Dialect</th>` +
    `<th scope="col">Apertus unrelated</th><th scope="col">Whisper unrelated</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="subnote">Separate speech probe (run ${esc(e.run_id)}), not a graph run, so it is not in the run
      picker.</p>`;
}

function submittedCard(e, run) {
  return `<details class="sub" data-file="${esc(e.file)}"><summary><h3>${esc(e.issue_title)}</h3>
    ${submittedLines(e)}<span class="open">Overview, variations and how to reproduce</span></summary>
    <div class="subbody">
      ${sourceLine(e)}
      ${e.overview ? `<p>${esc(e.overview)}</p>` : ""}
      ${e.variations?.length ? `<h4>Variations</h4>${variationLinks(e, run)}` : ""}
      ${e.unrelated ? dialectTable(e) : ""}
      ${reproduce(e)}
    </div></details>`;
}

// The clipboard is refused outside a secure page or without focus; the command is then selected
// for the keyboard instead.
async function copy(button) {
  const status = button.nextElementSibling, code = button.closest(".cmd").querySelector("code");
  try {
    await navigator.clipboard.writeText(code.textContent);
    status.textContent = "Copied";
  } catch {
    getSelection().selectAllChildren(code);
    status.textContent = "Selected: copy it with the keyboard";
  }
  setTimeout(() => status.textContent = "", 2500);
}

// The submission cites one graph run; a reader looking at another run is told which.
function elsewhere(submitted, run) {
  const cited = [...new Set(submitted.filter(e => !e.unrelated && e.run_id).map(e => e.run_id))];
  const others = cited.filter(id => id !== run.runId);
  if (!others.length) return "";
  return `<p class="subnote">These rest on run ${others.map(runLink).join(", ")}; you are looking at ` +
         `${esc(run.meta?.name || run.runId)}.</p>`;
}

export function renderSubmitted(submitted, run) {
  const box = $("#submitted");
  if (!box) return;
  if (!submitted?.length) {
    box.innerHTML = "";
    return;
  }
  const open = new Set([...box.querySelectorAll("details[open]")].map(d => d.dataset.file));
  box.classList.add("submitted");
  box.innerHTML = `<h2>Submitted findings (${submitted.length})</h2>${elsewhere(submitted, run)}` +
    `<p class="subnote">The ${term("ci", "95% intervals")} cover sampling only, not the judge's own errors; ` +
    "how far a second judge agrees is said under “Reproduced in this run”.</p>" +
    `<div class="subs">${submitted.map(e => submittedCard(e, run)).join("")}</div>`;
  box.querySelectorAll("details").forEach(d => { if (open.has(d.dataset.file)) d.open = true; });
  box.onclick = e => {
    const button = e.target.closest("[data-copy]");
    if (button) copy(button);
  };
}
