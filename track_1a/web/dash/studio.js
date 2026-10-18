import {$} from "./text.js";
import {onLoopback} from "./shell-state.js";

// web/studio/ is not in git, so a fresh clone has no studio. The server checks: a request for the
// missing page itself would put a 404 in the console.
export async function offerStudio() {
  if (!onLoopback()) return false;
  const studio = await fetch("/api/studio").then(r => r.json()).catch(() => null);
  if (!studio?.present) return false;
  $("#t-studio").hidden = false;
  return true;
}

export function loadStudio() {
  if (!$("#studio").src) $("#studio").src = $("#studio").dataset.src;
}

export async function saveAvatar() {
  const dot = $("#studio").contentWindow?.__dot;
  if (!dot) { $("#saveMsg").textContent = "Studio is still loading."; return; }
  const agent = document.querySelector("input[name=agent]:checked").value;
  const url = await dot.snapshot(320);
  const res = await fetch(`/api/avatar/${agent}`, {method: "POST", body: url}).then(r => r.json());
  $("#saveMsg").textContent = res.saved ? `Saved ${agent}'s avatar.` : res.error;
  const fresh = `avatars/${agent}.png?${Date.now()}`;
  document.querySelectorAll(`img[src^="avatars/${agent}.png"]`).forEach(img => img.src = fresh);
}
