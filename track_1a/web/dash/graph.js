import {$, esc, pct, readable} from "./text.js";

const AGENTS = [
  ["attacker", "Attacker", "writes a realistic probe from a hypothesis"],
  ["mutator", "Mutator", "translates: en · de · gsw · fr · it · rm"],
  ["target", "Target", "Apertus under test"],
  ["judge", "Judge", "temperature-0 rubric verdict"],
  ["verifier", "Verifier", "reruns languages × seeds"],
  ["scribe", "Scribe", "writes schema-valid findings"],
];
const ENDINGS = ["no_issue", "not_reproducible", "error"];

export const plannedHypotheses = events =>
  events.find(e => e.node === "graph" && e.status === "start")?.data?.hypotheses || [];

export function hypothesisStatus(events) {
  const status = {};
  for (const e of events) {
    if (!e.hypothesis) continue;
    if (e.node === "scribe" && e.status === "done") status[e.hypothesis] = "finding";
    else if (e.node === "graph" && ENDINGS.includes(e.status)) status[e.hypothesis] = e.status;
    else status[e.hypothesis] ??= "running";
  }
  return status;
}

export function drawAgents(bust) {
  $("#graph").innerHTML = AGENTS.map(([id, name, desc]) => `<div class="node" id="n-${id}">` +
    `<img src="avatars/${id}.png?${bust}" alt=""><b>${name}</b><span>${desc}</span></div>`).join("");
  $("#pick").innerHTML = AGENTS.map(([id, name], i) =>
    `<label><input type="radio" name="agent" value="${id}"${i === 0 ? " checked" : ""}>` +
    `<img src="avatars/${id}.png?${bust}" alt="">${name}</label>`).join("");
}

const MARK = text => `<span class="v">${text}</span>`;
// What the live feed prints after the node and status of each kind of event.
const DESCRIBE = {
  "attacker done": d => esc(d.prompt),
  "judge done": d => (d.violation ? MARK("VIOLATION") + " " : "ok ") + esc(d.reason),
  "target done": d => esc(String(d.answer ?? "").slice(0, 160)),
  "verifier done": d => "overall " + pct(d.overall),
  "verifier progress": d => `seed ${esc(d.seed)}: ` + (d.violation ? MARK("reproduced") : "clean"),
  "scribe done": d => "wrote " + esc(d.path?.split("/").pop()),
};

function feedLine(e) {
  const d = e.data || {}, lang = d.lang ? `[${esc(d.lang)}] ` : "";
  const describe = DESCRIBE[`${e.node} ${e.status}`] || (e.status === "error" ? x => esc(x.error) : () => "");
  return `<div class="ev"><span class="n">${esc(e.node)}</span> ${esc(e.status)} · ` +
         `<small>${esc(e.hypothesis || "")}</small> ${lang}${describe(d)}</div>`;
}

export function renderGraphTab(s, status) {
  const hyps = plannedHypotheses(s.events);
  $("#hyps").className = hyps.length ? "" : "empty";
  // The scribe writes up what the harness flagged; the recount can drop it below the bar again.
  const kept = new Set(s.findings.map(f => f.issue_summary.title));
  $("#hyps").innerHTML = hyps.length ? hyps.map(h => {
    let st = status[h] || "queued";
    if (st === "finding" && !kept.has(h)) st = "below_bar";
    const name = readable(h, s.hypotheses[h]?.domain || "");
    return `<div class="hyp"><span title="${esc(h)}">${esc(name)}</span>` +
           `<span class="pill ${st}">${st.replace("_", " ")}</span></div>`;
  }).join("") : "Start a run to see progress.";
  $("#feed").innerHTML = s.events.slice(-80).reverse().map(feedLine).join("");
}

// Header badge, mock banner and the glowing agent; returns whether the run has ended.
export function renderLive(s) {
  $("#runBtn").disabled = s.running;
  $("#runBtn").textContent = s.running ? "Running…" : "Run graph";
  const first = s.events[0], short = m => String(m ?? "").split("/").pop();
  const mock = first?.backend === "MOCK", judge = first?.data?.red_model;
  $("#backend").textContent = !first ? "no run yet" : mock ? "backend: MOCK"
    : `target: ${short(first.model)}` + (judge && judge !== first.model ? ` · judge: ${short(judge)}` : "");
  $("#backend").className = "badge " + (!first ? "" : mock ? "mock" : "live");
  $("#mockBanner").hidden = !mock;
  const ended = s.events.some(e => e.node === "graph" && e.status === "end");
  const lastStart = [...s.events].reverse().find(e => e.status === "start" && e.node !== "graph");
  AGENTS.forEach(([id]) => $("#n-" + id).classList.toggle("active", !ended && lastStart?.node === id));
  return ended;
}
