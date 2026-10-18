// Which hypothesis the walkthrough shows, and the list to pick another from.
import {STATUS, esc, titleOf} from "./text.js";
import {cellRates, spread} from "./heat.js";
import {isUrl} from "./explain-steps.js";

// A reproduced hypothesis with an official source whose languages disagree most, so the first
// walkthrough shows a gap and a source to check it against.
export function defaultPick(planned, states, ver, hypotheses) {
  const gap = id => spread(cellRates(ver[id].cells));
  const sourced = id => (hypotheses[id]?.sources || []).some(isUrl) ? 1 : 0;
  const reproduced = planned.filter(id => states(id) === "finding" && ver[id])
    .sort((a, b) => sourced(b) - sourced(a) || gap(b) - gap(a) || ver[b].overall - ver[a].overall ||
                    (a < b ? -1 : 1));
  return reproduced[0] || planned[0];
}

export const optionsHtml = (planned, states, hypotheses) => planned.map(id =>
  `<option value="${esc(id)}">${esc(titleOf(id, hypotheses))} · ${esc(STATUS[states(id)].label)}</option>`).join("");
