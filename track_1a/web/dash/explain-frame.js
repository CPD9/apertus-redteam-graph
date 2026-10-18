// The walkthrough's frame, drawn once: the notices, the bar with the picker, the summary, the step
// list and the controls, and the place the steps go.
import {AGENTS, avatarSrc} from "./graph.js";

// The six agents of the graph tab, lit for the step shown. The step buttons name the agents too,
// so the row is left to sighted readers.
const agentsHtml = () => AGENTS.map(([id, name]) =>
  `<li data-agent="${id}"><img src="${avatarSrc(id)}" alt="">${name}</li>`).join("");

// explain-live says which step Play has moved to, as the focus stays on its button.
export const frameHtml = () => `<p class="explain-source"></p>
  <p class="explain-notice" role="status" hidden></p>
  <p class="explain-live sr" role="status"></p>
  <div class="explain-bar">
    <div class="explain-head">
      <div class="explain-pick"><label for="explainPick">Hypothesis</label><select id="explainPick"></select></div>
      <ol class="explain-agents" aria-hidden="true">${agentsHtml()}</ol>
    </div>
    <p class="explain-summary"></p>
    <ol class="explain-nav" aria-label="Steps"></ol>
    <div class="explain-controls">
      <button type="button" data-act="prev">Previous</button>
      <button type="button" data-act="next">Next</button>
      <button type="button" data-act="all">Show all</button>
      <button type="button" data-act="play">Play</button>
    </div>
  </div>
  <div class="explain-steps"></div>`;
