// Address of the data relay (relay/worker.js) that fetches live data on demand
const RELAY_URL = "__RELAY_URL__";
async function relay(path, tries = 2) {
  try {
    const r = await fetch(RELAY_URL + path);
    if (r.ok) return r.json();
    const msg = (await r.json().catch(() => ({}))).error || `Relay ${r.status}`;
    if (r.status < 500 || tries <= 1) throw Object.assign(new Error(msg), { final: true });
  } catch (e) {
    if (e.final || tries <= 1) throw e;
  }
  return relay(path, tries - 1); // network blips and upstream hiccups get one retry
}

// Writes (watchlist changes) go straight through, never retried
async function relaySend(method, path, body, headers = {}) {
  const r = await fetch(RELAY_URL + path, { method, headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error || `Relay ${r.status}`), { status: r.status });
  return j;
}
