// "Ask a question" box backed by Gemini. Calls Google straight from this browser using
// the viewer's own API key, which is kept only in this browser's localStorage.
const StockChat = (() => {
  const STORE = "gemini_api_key";
  const MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"];
  const endpoint = (m) => `https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent`;
  const SYSTEM = `You are an equity research assistant for a mid-to-long-term (6-24 month) investor in Bursa Malaysia stocks.
Answer their questions clearly and precisely in plain English.
- The DATA below is what their dashboard shows: use it first, and quote its numbers.
- For anything newer or not in the DATA (company background, competitors, recent events): use Google Search if you have it and say where it came from; otherwise answer from general knowledge and say clearly that it may be out of date.
- Never invent numbers. If you don't know, say so.
- When asked whether to buy or sell, give a reasoned view with the key levels and risks, and remind them it is analysis, not financial advice.
- Keep answers short: a few short paragraphs or bullets. Use **bold** for key points.`;

  const getKey = () => { try { return localStorage.getItem(STORE) || ""; } catch { return ""; } };
  const setKey = (k) => { try { k ? localStorage.setItem(STORE, k) : localStorage.removeItem(STORE); } catch {} };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let searchOK = true;

  // Minimal markdown: paragraphs, bullets, numbered lists, headings, bold
  function md(text) {
    const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    const out = [];
    let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const raw of text.split("\n")) {
      const line = raw.trim();
      let m;
      if ((m = line.match(/^[-*•]\s+(.*)/))) {
        if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; }
        out.push(`<li>${inline(m[1])}</li>`);
      } else if ((m = line.match(/^\d+[.)]\s+(.*)/))) {
        if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; }
        out.push(`<li>${inline(m[1])}</li>`);
      } else if ((m = line.match(/^#{1,6}\s+(.*)/))) {
        close(); out.push(`<p class="k">${inline(m[1])}</p>`);
      } else if (line) {
        close(); out.push(`<p>${inline(line)}</p>`);
      } else close();
    }
    close();
    return out.join("");
  }

  async function ask(key, system, history) {
    const base = {
      systemInstruction: { parts: [{ text: system }] },
      contents: history,
      generationConfig: { temperature: 0.4 },
    };
    let last = "";
    for (const model of MODELS) {
      for (const search of searchOK ? [true, false] : [false]) {
        const body = search ? { ...base, tools: [{ google_search: {} }] } : base;
        for (const wait of [0, 5000]) {
          if (wait) await sleep(wait);
          const r = await fetch(endpoint(model), {
            method: "POST",
            headers: { "Content-Type": "application/json", "x-goog-api-key": key },
            body: JSON.stringify(body),
          });
          if (r.ok) {
            const j = await r.json();
            const cand = j.candidates?.[0];
            const text = (cand?.content?.parts || []).map((p) => p.text || "").join("");
            if (!text) { last = "Empty answer"; break; }
            const sources = (cand.groundingMetadata?.groundingChunks || []).filter((c) => c.web).map((c) => c.web);
            return { text, sources, model };
          }
          const err = await r.text();
          last = `${r.status}: ${(err.match(/"message":\s*"([^"]+)/) || [])[1] || err.slice(0, 150)}`;
          if (r.status === 400 && /api key/i.test(err)) throw new Error("BAD_KEY");
          if (r.status === 403) throw new Error("BAD_KEY");
          // No Google Search quota on this key: stop asking for it
          if (search && r.status === 429) { searchOK = false; break; }
          if (r.status !== 503 && r.status !== 429 && r.status !== 500) break;
        }
      }
    }
    throw new Error(last);
  }

  function mount(el, { name, data, suggestions = [] }) {
    const system = `${SYSTEM}\n\nDATA (${name}):\n${JSON.stringify(data)}`;
    const history = [];
    el.classList.add("chat");
    el.innerHTML = `
      <h3>Ask about ${esc(name)}</h3>
      <div class="chat-log"></div>
      <div class="chat-chips">${suggestions.map((q) => `<button type="button" class="chip">${esc(q)}</button>`).join("")}</div>
      <form class="chat-form">
        <textarea rows="2" placeholder="Ask anything about ${esc(name)}… (Enter to send)"></textarea>
        <button type="submit">Ask</button>
      </form>
      <div class="chat-key" hidden>
        <p>To chat, paste your Gemini API key from <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a>.
          It's saved only in this browser on this device, and sent only to Google.</p>
        <form class="key-form"><input type="password" autocomplete="off" placeholder="Gemini API key"><button type="submit">Save key</button></form>
      </div>
      <div class="sub chat-foot">Answers by Gemini from this page's data plus Google Search. Not financial advice. <a href="#" class="forget">Forget my key</a></div>`;

    const log = el.querySelector(".chat-log");
    const input = el.querySelector("textarea");
    const keyBox = el.querySelector(".chat-key");
    let pending = null;

    const add = (role, html) => {
      const div = document.createElement("div");
      div.className = `msg ${role}`;
      div.innerHTML = html;
      log.appendChild(div);
      div.scrollIntoView({ block: "nearest", behavior: "smooth" });
      return div;
    };

    async function send(q) {
      q = q.trim();
      if (!q) return;
      const key = getKey();
      if (!key) { pending = q; keyBox.hidden = false; keyBox.querySelector("input").focus(); return; }
      input.value = "";
      add("user", esc(q));
      history.push({ role: "user", parts: [{ text: q }] });
      const wait = add("bot", `<p class="empty">Thinking…</p>`);
      try {
        const a = await ask(key, system, history);
        history.push({ role: "model", parts: [{ text: a.text }] });
        const src = a.sources.length
          ? `<div class="sub">Sources: ${a.sources.slice(0, 5).map((s) => `<a href="${safeUrl(s.uri)}" target="_blank" rel="noopener">${esc(s.title || "link")}</a>`).join(" · ")}</div>`
          : "";
        wait.innerHTML = md(a.text) + src;
      } catch (e) {
        history.pop();
        if (e.message === "BAD_KEY") {
          setKey("");
          wait.innerHTML = `<p class="down">Google rejected the API key. Please paste a valid Gemini key.</p>`;
          pending = q; keyBox.hidden = false;
        } else {
          wait.innerHTML = `<p class="down">Couldn't get an answer (${esc(e.message)}). Gemini's free tier is sometimes busy; try again in a minute.</p>`;
        }
      }
    }

    el.querySelector(".chat-form").addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
    });
    el.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => send(b.textContent)));
    el.querySelector(".key-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const k = e.target.querySelector("input").value.trim();
      if (!k) return;
      setKey(k);
      e.target.querySelector("input").value = "";
      keyBox.hidden = true;
      if (pending) { const q = pending; pending = null; send(q); }
    });
    el.querySelector(".forget").addEventListener("click", (e) => {
      e.preventDefault();
      setKey("");
      add("bot", `<p class="empty">Key removed from this browser.</p>`);
    });
  }

  return { mount };
})();
