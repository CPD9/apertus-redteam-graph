import {$, STATUS_TIPS, UNCOUNTED, esc, pct, titleOf} from "./text.js";

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
// What the live feed prints after the node and status of each kind of event. A verifier result is
// the share of answers that count (flagged with severity above 0) unless the server could not
// recount it.
const DESCRIBE = {
  "attacker done": d => esc(d.prompt),
  "judge done": d => (d.violation ? MARK("flagged") + " " : "ok ") + esc(d.reason),
  "target done": d => esc(String(d.answer ?? "").slice(0, 160)),
  "verifier done": (d, uncounted) => (uncounted ? "flagged " : "counted ") + pct(d.overall),
  "verifier progress": d => `seed ${esc(d.seed)}: ` +
    (!d.violation ? "clean" : d.counted === false ? MARK("flagged") + " at severity 0" : MARK("flagged")),
  "scribe done": d => d.path ? "wrote " + esc(d.path.split("/").pop())
                             : "no findings file: the counted share is below the bar",
};

function feedLine(e, uncounted) {
  const d = e.data || {}, lang = d.lang ? `[${esc(d.lang)}] ` : "";
  const describe = DESCRIBE[`${e.node} ${e.status}`] || (e.status === "error" ? x => esc(x.error) : () => "");
  return `<div class="ev"><span class="n">${esc(e.node)}</span> ${esc(e.status)} · ` +
         `<small>${esc(e.hypothesis || "")}</small> ${lang}${describe(d, uncounted.has(e.hypothesis))}</div>`;
}

export function renderGraphTab(s, status) {
  const hyps = plannedHypotheses(s.events), uncounted = new Set(s.uncounted);
  $("#hyps").className = hyps.length ? "" : "empty";
  // Older runs wrote up every hypothesis flagged often enough; the recount can drop one below the bar.
  const kept = new Set(s.findings.map(f => f.hypothesis));
  $("#hyps").innerHTML = hyps.length ? hyps.map(h => {
    let st = status[h] || "queued";
    if (st === "finding" && !kept.has(h)) st = "below_bar";
    const tag = uncounted.has(h) ? UNCOUNTED : "", tip = STATUS_TIPS[st];
    const pill = `<span class="pill ${st}"${tip ? ` data-tip="${tip}"` : ""}>${st.replace("_", " ")}</span>`;
    return `<div class="hyp"><span title="${esc(h)}">${esc(titleOf(h, s.hypotheses))}</span>` +
           `<span class="pills">${tag}${pill}</span></div>`;
  }).join("") : "Start a run to see progress.";
  $("#feed").innerHTML = s.events.slice(-80).reverse().map(e => feedLine(e, uncounted)).join("");
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
