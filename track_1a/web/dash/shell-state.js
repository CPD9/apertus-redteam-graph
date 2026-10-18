import {$} from "./text.js";

// The server only takes runs, labels and avatars from its own pages on 127.0.0.1 or localhost, so
// the tools that post are offered there alone; anyone else reading the dashboard only reads.
export const onLoopback = () => ["127.0.0.1", "localhost"].includes(location.hostname);
// For a reader elsewhere, "this machine" would be their own.
export const here = () => onLoopback() ? "this machine" : "the server";

// What the page shows, mirrored in the URL: ?tab=&run=&h=&domain=&q= and #f-<id> or #g-<key>.
export const view = {tab: "findings", run: "", hypothesis: "", domain: "", query: "", anchor: ""};

// The newest payload with what was derived from it, and the finding cards built from it.
export const page = {latest: null, cards: []};

export function fromUrl() {
  const q = new URLSearchParams(location.search);
  return {tab: q.get("tab") || "", run: q.get("run") || "", hypothesis: q.get("h") || "",
          domain: q.get("domain") || "", query: q.get("q") || ""};
}

// A hand-edited hash such as #f-100% does not decode; it is ignored rather than stopping the page.
export function anchorFromUrl() {
  if (!/^#[fg]-./.test(location.hash)) return "";
  try {
    return decodeURIComponent(location.hash);
  } catch {
    return "";
  }
}

// Tab changes and jumps get their own history entry, so Back undoes them; filters and picks do not.
export function syncUrl(push = false) {
  const q = new URLSearchParams({tab: view.tab});
  if (view.run) q.set("run", view.run);
  if (view.tab === "explain" && view.hypothesis) q.set("h", view.hypothesis);
  if (view.tab === "findings" && view.domain) q.set("domain", view.domain);
  if (view.tab === "findings" && view.query) q.set("q", view.query);
  const url = "?" + q + (view.anchor ? "#" + encodeURIComponent(view.anchor.slice(1)) : "");
  if (url === location.search + location.hash) return;
  history[push ? "pushState" : "replaceState"](null, "", url);
}

// ---- Notices above the content, and announcements for screen readers

const notices = {};

// html must be escaped by the caller; kind is warn, info or done.
export function setNotice(key, html = "", kind = "warn") {
  const was = notices[key];
  if ((was?.html || "") === html && (!html || was.kind === kind)) return;
  if (html) notices[key] = {html, kind};
  else delete notices[key];
  $("#notices").innerHTML = Object.values(notices)
    .map(n => `<p class="notice ${n.kind}">${n.html}</p>`).join("");
}

// Polite announcements; emptied first so the same words are read again.
export function announce(text) {
  const status = $("#status");
  status.textContent = "";
  setTimeout(() => status.textContent = text, 50);
}

export const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
export const scrollBehavior = () => reducedMotion.matches ? "auto" : "smooth";
