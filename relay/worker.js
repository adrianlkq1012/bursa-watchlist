// Bursa Research relay (Cloudflare Worker, free tier).
// The website can't call Yahoo Finance or Google News directly (they block other sites'
// browser requests), so this fetches on demand, tidies the data, caches it briefly and
// adds the headers that let the site read it. Read-only, public market data only.
//
//   GET /search?q=maybank     find Bursa stocks by name or code
//   GET /stock/5161           prices, profile, ratios and financial statements for one stock
//   GET /news?q="JCY"         recent Google News headlines
//   GET /screen               every Bursa stock with today's quote (for movers / browsing)

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const Y = "https://query1.finance.yahoo.com";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" };

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (request.method !== "GET") return reply({ error: "GET only" }, 405);

    // Serve repeat requests from memory so Yahoo sees few requests. (Cloudflare's Cache API
    // doesn't work on free *.workers.dev addresses, so this is a simple in-memory cache.)
    const url = new URL(request.url);
    const key = url.pathname + url.search;
    const hit = memo.get(key);
    if (hit && hit.until > Date.now()) return reply(hit.body, 200, hit.maxAge);

    try {
      const { body, maxAge } = await route(url);
      memo.set(key, { body, maxAge, until: Date.now() + maxAge * 1000 });
      if (memo.size > 300) memo.delete(memo.keys().next().value);
      return reply(body, 200, maxAge);
    } catch (e) {
      return reply({ error: String(e.message || e) }, e.status || 502);
    }
  },
};

const memo = new Map();

async function route(url) {
  const path = url.pathname.replace(/\/+$/, "");
  let m;
  if (path === "/search") return { body: await search(url.searchParams.get("q") || ""), maxAge: 86400 };
  if ((m = path.match(/^\/stock\/([0-9A-Z]{4,6})$/i))) return { body: await stock(m[1].toUpperCase()), maxAge: 1800 };
  if ((m = path.match(/^\/intraday\/([0-9A-Z]{4,6})$/i))) {
    const range = url.searchParams.get("range") === "60d" ? "60d" : "5d"; // 60 days is for backtesting
    return { body: await intraday(m[1].toUpperCase(), range), maxAge: range === "60d" ? 1800 : 300 };
  }
  if (path === "/news") return { body: await news(url.searchParams.get("q") || ""), maxAge: 3600 };
  if (path === "/screen") return { body: await screen(), maxAge: 1800 };
  throw Object.assign(new Error("Not found"), { status: 404 });
}

function reply(body, status = 200, maxAge = 0) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": maxAge ? `public, max-age=${maxAge}` : "no-store" },
  });
}

async function getJSON(u, opts = {}) {
  const r = await fetch(u, { ...opts, headers: { "User-Agent": UA, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error(`${new URL(u).hostname} answered ${r.status}`);
  return r.json();
}

// Some Yahoo endpoints need a session cookie plus a "crumb" token
let session = null;
async function yahooSession() {
  if (session && Date.now() - session.at < 3600e3) return session;
  const r = await fetch("https://fc.yahoo.com", { headers: { "User-Agent": UA }, redirect: "manual" });
  const cookie = (r.headers.get("set-cookie") || "").split(";")[0];
  const c = await fetch(`${Y}/v1/test/getcrumb`, { headers: { "User-Agent": UA, Cookie: cookie } });
  const crumb = await c.text();
  if (!c.ok || !crumb || crumb.includes("<")) throw new Error("Yahoo session failed");
  session = { cookie, crumb, at: Date.now() };
  return session;
}

const raw = (x) => (x && typeof x === "object" ? x.raw ?? null : x ?? null);

async function search(q) {
  q = q.trim().slice(0, 60);
  if (!q) return [];
  const d = await getJSON(`${Y}/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=15&newsCount=0`);
  return (d.quotes || [])
    .filter((x) => /^\d{4}\.KL$/.test(x.symbol || "") && x.quoteType === "EQUITY")
    .map((x) => ({ c: x.symbol.slice(0, 4), s: x.shortname || x.symbol, n: x.longname || x.shortname || x.symbol, sec: x.sectorDisp || null }));
}

const SUMMARY_MODULES = "price,summaryDetail,defaultKeyStatistics,financialData,assetProfile,majorHoldersBreakdown";
const INCOME = { revenue: "TotalRevenue", gross_profit: "GrossProfit", operating_income: "OperatingIncome", net_income: "NetIncome", eps: "DilutedEPS" };
const BALANCE_CASH = {
  total_assets: "TotalAssets", total_debt: "TotalDebt", cash: "CashAndCashEquivalents", equity: "StockholdersEquity",
  operating_cf: "OperatingCashFlow", capex: "CapitalExpenditure", free_cf: "FreeCashFlow", dividends_paid: "CashDividendsPaid",
};

async function statements(sym) {
  const now = Math.floor(Date.now() / 1000);
  const types = [
    ...Object.values({ ...INCOME, ...BALANCE_CASH }).map((t) => "annual" + t),
    ...Object.values(INCOME).map((t) => "quarterly" + t),
  ].join(",");
  const d = await getJSON(`${Y}/ws/fundamentals-timeseries/v1/finance/timeseries/${sym}?type=${types}&period1=${now - 6 * 365 * 86400}&period2=${now}`);
  const out = { annual: {}, quarterly: {} };
  const fieldOf = Object.fromEntries(Object.entries({ ...INCOME, ...BALANCE_CASH }).map(([k, v]) => [v, k]));
  for (const r of d.timeseries?.result || []) {
    const type = r.meta?.type?.[0] || "";
    const freq = type.startsWith("annual") ? "annual" : type.startsWith("quarterly") ? "quarterly" : null;
    if (!freq) continue;
    const field = fieldOf[type.replace(/^(annual|quarterly)/, "")];
    for (const p of r[type] || []) {
      if (!p) continue;
      (out[freq][p.asOfDate] ||= {})[field] = p.reportedValue?.raw ?? null;
    }
  }
  for (const k of ["annual", "quarterly"]) {
    out[k] = Object.fromEntries(Object.entries(out[k]).sort((a, b) => b[0].localeCompare(a[0])).slice(0, k === "annual" ? 5 : 6));
  }
  return out;
}

async function stock(code) {
  const sym = `${code}.KL`;
  const [chart, summary, fin] = await Promise.all([
    getJSON(`${Y}/v8/finance/chart/${sym}?range=2y&interval=1d&events=div`),
    yahooSession().then((s) => getJSON(`${Y}/v10/finance/quoteSummary/${sym}?modules=${SUMMARY_MODULES}&crumb=${encodeURIComponent(s.crumb)}`,
      { headers: { Cookie: s.cookie } })).catch(() => null),
    statements(sym).catch(() => ({ annual: {}, quarterly: {} })),
  ]);

  const c = chart.chart?.result?.[0];
  if (!c) throw new Error(`No data for ${code}`);
  const q = c.indicators.quote[0];
  const candles = [], volumes = [];
  c.timestamp.forEach((t, i) => {
    if (q.close[i] == null) return;
    const day = new Date((t + 8 * 3600) * 1000).toISOString().slice(0, 10); // Malaysia date
    candles.push([day, q.open[i], q.high[i], q.low[i], q.close[i]]);
    volumes.push(q.volume[i] || 0);
  });

  const s = summary?.quoteSummary?.result?.[0] || {};
  const price = s.price || {}, det = s.summaryDetail || {}, key = s.defaultKeyStatistics || {}, fd = s.financialData || {};
  const prof = s.assetProfile || {}, hold = s.majorHoldersBreakdown || {};
  const meta = c.meta || {};
  const close = raw(price.regularMarketPrice) ?? meta.regularMarketPrice;
  const prev = candles.length > 1 ? candles[candles.length - 2][4] : null;

  const divs = {};
  for (const d of Object.values(c.events?.dividends || {})) {
    const y = new Date(d.date * 1000).getUTCFullYear();
    divs[y] = Math.round(((divs[y] || 0) + d.amount) * 1e4) / 1e4;
  }

  return {
    code, short: price.shortName || meta.shortName || code, name: price.longName || meta.longName || code,
    sector: prof.sector || null, industry: prof.industry || null, summary: (prof.longBusinessSummary || "").slice(0, 1500),
    website: prof.website || null, employees: prof.fullTimeEmployees || null,
    close, change_pct: raw(price.regularMarketChangePercent) != null ? raw(price.regularMarketChangePercent) * 100 : (prev ? (close / prev - 1) * 100 : null),
    change_52w: raw(key["52WeekChange"]) != null ? raw(key["52WeekChange"]) * 100 : null,
    as_of: candles.length ? candles[candles.length - 1][0] : null,
    fundamentals: {
      market_cap: raw(price.marketCap) ?? raw(det.marketCap),
      pe: raw(det.trailingPE), forward_pe: raw(det.forwardPE), pb: raw(key.priceToBook),
      dividend_yield: raw(det.dividendYield) != null ? raw(det.dividendYield) * 100 : null,
      eps: raw(key.trailingEps), roe: raw(fd.returnOnEquity), debt_to_equity: raw(fd.debtToEquity),
      profit_margin: raw(fd.profitMargins), current_ratio: raw(fd.currentRatio),
      total_cash: raw(fd.totalCash), total_debt: raw(fd.totalDebt), free_cashflow: raw(fd.freeCashflow),
      revenue_growth: raw(fd.revenueGrowth),
    },
    financials: {
      ...fin,
      dividends_by_year: divs,
      ownership: { heldPercentInsiders: raw(hold.insidersPercentHeld), heldPercentInstitutions: raw(hold.institutionsPercentHeld) },
      officers: (prof.companyOfficers || []).slice(0, 6).map((o) => ({ name: o.name, title: o.title })),
    },
    candles, volumes,
  };
}

// 15-minute bars (last 5 days, or 60 for backtests), for day-trading setups. Times are
// shifted to Malaysia time (UTC+8) so charts show local clock times.
async function intraday(code, range = "5d") {
  const d = await getJSON(`${Y}/v8/finance/chart/${code}.KL?range=${range}&interval=15m`);
  const c = d.chart?.result?.[0];
  if (!c?.timestamp) throw new Error(`No intraday data for ${code}`);
  const q = c.indicators.quote[0];
  const candles = [], volumes = [];
  c.timestamp.forEach((t, i) => {
    if (q.close[i] == null || q.open[i] == null) return;
    candles.push([t + 8 * 3600, q.open[i], q.high[i], q.low[i], q.close[i]]);
    volumes.push(q.volume[i] || 0);
  });
  return { code, interval: "15m", candles, volumes };
}

const tag = (s, t) => {
  const m = s.match(new RegExp(`<${t}[^>]*>([\\s\\S]*?)</${t}>`));
  return m ? m[1].replace(/<!\[CDATA\[|\]\]>/g, "").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").trim() : "";
};
const items = (xml) => xml.match(/<item>[\s\S]*?<\/item>/g) || [];
const day = (s) => { const d = new Date(s); return isNaN(d) ? "" : d.toISOString().slice(0, 10); };

async function googleNews(q) {
  const r = await fetch(`https://news.google.com/rss/search?q=${encodeURIComponent(q + " when:90d")}&hl=en-MY&gl=MY&ceid=MY:en`,
    { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error(`Google News answered ${r.status}`);
  return items(await r.text()).map((it) => {
    const source = tag(it, "source");
    let title = tag(it, "title");
    if (source && title.endsWith(` - ${source}`)) title = title.slice(0, -source.length - 3);
    return { title, source, link: tag(it, "link"), date: day(tag(it, "pubDate")) };
  });
}

// Fallback: Google often refuses requests from Cloudflare's servers
async function bingNews(q) {
  const r = await fetch(`https://www.bing.com/news/search?q=${encodeURIComponent(q)}&format=rss&setmkt=en-MY`,
    { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error(`Bing News answered ${r.status}`);
  return items(await r.text()).map((it) => {
    let link = tag(it, "link");
    try { link = new URL(link).searchParams.get("url") || link; } catch {}
    let source = tag(it, "News:Source");
    try { source = decodeURIComponent(source); } catch {}
    return { title: tag(it, "title"), source, link, date: day(tag(it, "pubDate")) };
  }).filter((n) => n.date >= day(Date.now() - 180 * 86400e3)); // Bing has no date filter; keep 6 months
}

async function news(q) {
  q = q.trim().slice(0, 120);
  if (!q) return [];
  let list = await googleNews(q).catch(() => []);
  if (!list.length) list = await bingNews(q);
  const seen = new Set();
  return list.filter((n) => {
    const k = n.title.toLowerCase().slice(0, 60);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 15);
}

async function screen() {
  const s = await yahooSession();
  const rows = [];
  for (let offset = 0; offset < 1500; offset += 250) {
    const d = await getJSON(`${Y}/v1/finance/screener?crumb=${encodeURIComponent(s.crumb)}&lang=en-US&region=MY`, {
      method: "POST",
      headers: { Cookie: s.cookie, "Content-Type": "application/json" },
      body: JSON.stringify({
        offset, size: 250, sortField: "intradaymarketcap", sortType: "DESC", quoteType: "EQUITY",
        query: { operator: "EQ", operands: ["exchange", "KLS"] }, userId: "", userIdType: "guid",
      }),
    });
    const quotes = d.finance?.result?.[0]?.quotes || [];
    for (const x of quotes) {
      if (!/^\d{4}\.KL$/.test(x.symbol || "")) continue;
      rows.push({
        c: x.symbol.slice(0, 4), s: x.shortName || x.symbol, n: x.longName || x.shortName || x.symbol,
        p: x.regularMarketPrice ?? null, ch: x.regularMarketChangePercent ?? null, y1: x.fiftyTwoWeekChangePercent ?? null,
        mc: x.marketCap ?? null, pe: x.trailingPE ?? null, pb: x.priceToBook ?? null, dy: x.dividendYield ?? null,
      });
    }
    if (quotes.length < 250) break;
  }
  return rows;
}
