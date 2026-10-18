import {LANG_NAMES, esc} from "./text.js";
import {range} from "./heat-data.js";

const STEPS = ["0%", "1–20%", "21–40%", "41–60%", "61–80%", "81–100%"];
const whole = x => Math.round(x * 100);

export const scaleHtml = () =>
  `<span class="steps">${STEPS.map((label, i) => `<span class="hc h${i}">${label}</span>`).join("")}</span>`;

const counts = cell => cell.n ? `${Number(cell.k)} of ${Number(cell.n)} answers failed` : "";

// One language's result. The colour step follows the printed percentage: 0 stays 0, 1–20 is step 1,
// …, 81–100 is step 5. Screen readers get one sentence instead of the stacked numbers, with the
// interval the tooltip shows, since nobody tabs to a cell. interval prints that interval as a third
// line, for the averages.
export function heatCell(cell, lang, {big = false, top = false, role = "", interval = false} = {}) {
  const name = esc(LANG_NAMES[lang] || lang), aria = role ? ` role="${role}"` : "";
  if (!cell) {
    return `<span class="hc none"${aria}><span aria-hidden="true">–</span>` +
           `<span class="sr">${name}: not run</span></span>`;
  }
  const p = whole(cell.rate), ci = cell.ci95 ? `95% CI ${range(cell.ci95)}` : "";
  const tip = [counts(cell) || `${p}% of answers failed`, ci];
  const said = [`${name} ${p}%`, counts(cell), ci, top && "highest"];
  const third = interval && cell.ci95
    ? `<small class="ci">${whole(cell.ci95[0])}–${whole(cell.ci95[1])}<span class="pc">%</span></small>` : "";
  const shown = (big ? `<small>${esc(lang)}</small>` : "") + `<b>${p}<span class="pc">%</span></b>` +
                (cell.n ? `<small>${Number(cell.k)}<wbr>/${Number(cell.n)}</small>` : "") + third;
  return `<span class="hc h${Math.ceil(p / 20)}${top ? " top" : ""}"${aria} ` +
         `data-tip="${name}: ${tip.filter(Boolean).join(", ")}"><span aria-hidden="true">${shown}</span>` +
         `<span class="sr">${said.filter(Boolean).join(", ")}</span></span>`;
}
