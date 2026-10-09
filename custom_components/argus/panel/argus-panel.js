/* ARGUS panel – vanilla web component, no build step.
 * Sections: "Prices" (the products you follow and their deals), "Overview" (what it all costs),
 * "Logbook" (everything the integration does) and "Manage" (adding, import, shops, settings).
 * English is the source language; translations live in i18n/<lang>.json ({"English": "translation"}).
 * ARGUS = Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden. */

// ------------------------------------------------------------------ i18n
const LOCALES = { en: "en-IE", nl: "nl-BE", fr: "fr-BE", de: "de-DE", es: "es-ES", zh: "zh-CN", ko: "ko-KR", id: "id-ID" };
let LANG = "nl", DICT = {}, PATTERNS = null, LOC = "nl-BE", NF, NF0;
const fill = (s, p) => (p ? String(s).replace(/\{(\w+)\}/g, (m, k) => (p[k] ?? m)) : String(s));
/** Translate a UI string (English source) and fill in {params}. */
const t = (s, p) => fill(DICT[s] || s, p);
/** Translate a text produced by the backend: English with the parameters already filled in.
 *  Exact match first, else the templates are matched in reverse and the parameters translated too. */
function tx(msg, depth = 0) {
  if (msg == null || msg === "") return "";
  msg = String(msg);
  if (LANG === "en") return msg;
  if (DICT[msg]) return DICT[msg];
  if (depth > 2) return msg;
  if (!PATTERNS) {
    PATTERNS = Object.keys(DICT).filter((k) => k.includes("{")).map((k) => {
      const names = [];
      const src = k.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{(\w+)\}/g, (m, n) => { names.push(n); return "([\\s\\S]+?)"; });
      return { k, names, re: new RegExp(`^${src}$`) };
    }).sort((a, b) => b.k.replace(/\{\w+\}/g, "").length - a.k.replace(/\{\w+\}/g, "").length);
  }
  for (const { k, names, re } of PATTERNS) {
    const m = msg.match(re);
    if (m) { const p = {}; names.forEach((n, i) => { p[n] = tx(m[i + 1], depth + 1); }); return fill(DICT[k], p); }
  }
  return msg;
}
function setLocale(lang) {
  LOC = LOCALES[lang] || "en-IE";
  // Safari/WebKit (iPhone app) is stricter than Chrome: give min and max decimals together, and never fail here
  try {
    NF = new Intl.NumberFormat(LOC, { style: "currency", currency: "EUR" });
    NF0 = new Intl.NumberFormat(LOC, { style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 0 });
  } catch (e) {
    const plain = (dec) => ({ format: (v) => "€" + Number(v).toFixed(dec) });
    NF = plain(2); NF0 = plain(0);
  }
}
setLocale("nl");
async function loadLanguage(lang, version) {
  if (!LOCALES[lang]) lang = "nl";
  if (lang === LANG) return false;
  let dict = {};
  if (lang !== "en") {
    try { const r = await fetch(`/argus_static/i18n/${lang}.json?v=${encodeURIComponent(version || "")}`); if (r.ok) dict = await r.json(); } catch (e) { /* fall back to English */ }
  }
  LANG = lang; DICT = dict; PATTERNS = null; setLocale(lang);
  return true;
}

// ------------------------------------------------------------------ helpers
/** An amount as typed: "164,99", "164.99", "1.649,99", "€ 164,99" → "164.99" ("" when empty). Text fields, not
 * type=number: some phone keyboards drop the decimal comma there (164,99 became 16499). */
const money = (v) => {
  let s = String(v ?? "").replace(/[€\s\u00a0]/g, "");
  if (!s) return "";
  if (s.includes(",") && s.includes(".")) s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  else if (s.includes(",")) s = s.replace(",", ".");
  return s;
};
/** "Approve" for a price that was held back as suspicious (shop table, shops & jobs, logbook). */
/** A doubtful link (not clearly another product): approve it, or never visit it again (the shop is searched for another link). */
const doubtBtns = (num, rid) => `<button class="btn sm ldb" type="button" data-stop data-lact="ok" data-lnum="${esc(num)}" data-lrid="${esc(rid)}" title="${esc(t("This is the right product: use this link and its price"))}">✓ ${esc(t("Approve link"))}</button> <button class="btn ghost sm ldb" type="button" data-stop data-lact="rej" data-lnum="${esc(num)}" data-lrid="${esc(rid)}" title="${esc(t("Block only this link; the shop is searched again for the right page"))}">🚫 ${esc(t("Never visit this link again"))}</button>`;
/** Your own price counts, the shop now says another: approve the new price or keep yours. */
const choiceBtns = (num, rid, c) => `<button class="btn sm pcb" type="button" data-stop data-pacc="1" data-pnum="${esc(num)}" data-prid="${esc(rid)}" title="${esc(t("Your own price goes away; the shop's price counts from now on"))}">✓ ${esc(t("Approve new price {price}", { price: EUR(c.price) }))}</button> <button class="btn ghost sm pcb" type="button" data-stop data-pacc="0" data-pnum="${esc(num)}" data-prid="${esc(rid)}" title="${esc(t("Your own price stays; you are not asked again for this price"))}">${esc(t("Keep old price {price}", { price: EUR(c.manual) }))}</button>`;
const TICKER_RELOAD = 600000;                       // the ticker content is reloaded every 10 minutes
const approveBtn = (num, rid, price) => `<button class="btn sm apprb" type="button" data-stop data-anum="${esc(num)}" data-arid="${esc(rid)}" title="${esc(t("The price is right after all: count it, and accept prices like it for this link from now on"))}">✓ ${esc(t("Approve {price}", { price: EUR(price) }))}</button>`;
const EUR = (v) => (v == null || isNaN(v) ? "–" : NF.format(v));
const EUR0 = (v) => (v == null || isNaN(v) ? "–" : NF0.format(v));
const INT = (v) => (v == null ? "–" : Math.round(v).toLocaleString(LOC));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const signPct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toLocaleString(LOC, { maximumFractionDigits: 1 })}%`);
const DATE = (ts, o = { day: "2-digit", month: "short" }) => new Date(ts * 1000).toLocaleDateString(LOC, o);
const TIME = (ts) => new Date(ts * 1000).toLocaleTimeString(LOC, { hour: "2-digit", minute: "2-digit" });
/** What this panel needs from the server (API_LEVEL in const.py). Different = Home Assistant still runs older code. */
const API_LEVEL = 1;
/** How a price was read, as one letter: ⓤ your own browser (userscript), ⌂ the shop's own site. */
const VIA_MARK = { relay: "ⓤ", userscript: "ⓤ" };
const viaTitle = (via) => (via === "relay" || via === "userscript" ? t("Price fetched by your own browser (userscript)") : t("Read directly from the shop's own site"));
const viaMark = (via, direct = true) => (VIA_MARK[via] ? `<span class="vbadge" title="${esc(viaTitle(via))}">${VIA_MARK[via]}</span>`
  : direct ? `<span class="vbadge" title="${esc(viaTitle(""))}">⌂</span>` : "");
/** Why a shop has no price (sold out / no longer sold): a warning, not an error. */
const unavailableText = (why) => (why === "discontinued" ? t("no longer sold (out of the range)") : t("sold out"));
const viaBadge = (via) => (VIA_MARK[via] ? " " + viaMark(via) : "");
/** A small version of a product image (marketplace images come in sizes; others are used as they are). */
const thumb = (url, w = 320) => {
  if (!url) return url;
  try {
    const u = new URL(url);
    if (/\._[A-Z0-9_,]+_\.(jpe?g|png|webp)$/i.test(u.pathname)) return url.replace(/\._[A-Z0-9_,]+_\.(jpe?g|png|webp)$/i, `._AC_SL${w}_.$1`);
  } catch (e) { /* not a URL */ }
  return url;
};
const GRID_PAGE = 48;
const ago = (ts) => {
  if (!ts) return t("never");
  const s = Date.now() / 1000 - ts;
  if (s < 90) return t("just now");
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400) return t("{n} h ago", { n: Math.round(s / 3600) });
  return t("{n} d ago", { n: Math.round(s / 86400) });
};
const dur = (sec) => (sec >= 5400 ? t("{n} h", { n: (sec / 3600).toFixed(1) }) : sec >= 90 ? t("{n} min", { n: Math.round(sec / 60) }) : t("{n} s", { n: Math.round(sec) }));
const COLORS = ["#c9921a", "#2563eb", "#059669", "#d946ef", "#e11d48", "#0891b2", "#ea580c", "#64748b"];
const CATEGORY_ICONS = { electronics: "🔌", books: "📚", toys_games: "🧸", home_garden_diy: "🏡", other: "📦" };
/** Colour themes for the whole panel: [key, name, swatches]. "ha" = the colours of your Home Assistant theme. */
const COLOR_THEMES = [["ha", "Home Assistant", ["var(--primary-color,#03a9f4)", "var(--card-background-color,#fff)", "var(--primary-background-color,#f3f4f7)"]],
  ["argus", "Classic", ["#c9921a", "#14172b", "#fff"]], ["ocean", "Ocean", ["#0067b8", "#e7f1fb", "#fff"]], ["forest", "Forest", ["#1b7f3b", "#e8f4ec", "#fff"]],
  ["violet", "Violet", ["#7a3c9e", "#f1e9f6", "#fff"]], ["sunset", "Sunset", ["#e3611a", "#fdeee4", "#fff"]], ["light", "Light", ["#0057a6", "#fff", "#f3f4f7"]],
  ["dark", "Dark", ["#e0b04a", "#1c1f26", "#111318"]]];   // stored in English, shown with t()
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const lastAt = (pts, t) => { let r = null; for (const p of pts) { if (p[0] <= t) r = p; else break; } return r; };

// ------------------------------------------------------------------ charts (inline SVG)
const CHARTS = {}; let CHART_N = 0;
function lineChart(series, { height = 240, money = true, area = true, zoom = null } = {}) {
  const W = 760, H = height, P = { l: 56, r: 14, t: 14, b: 26 };
  const all = series.flatMap((s) => s.points);
  if (all.length < 2) return `<div class="empty small">📈 ${t("Not enough data points for a chart yet. The price history appears here after a few refreshes.")}</div>`;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.12 || Math.max(1, y1 * 0.05); y0 = Math.max(0, y0 - pad); y1 += pad;
  const sx = (x) => P.l + ((x - x0) / (x1 - x0 || 1)) * (W - P.l - P.r);
  const sy = (y) => H - P.b - ((y - y0) / (y1 - y0 || 1)) * (H - P.t - P.b);
  const id = ++CHART_N;
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const v = y0 + ((y1 - y0) * i) / 4, y = sy(v);
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}" class="gl"/><text x="${P.l - 8}" y="${y + 4}" text-anchor="end" class="axis">${money ? EUR0(v) : Math.round(v)}</text>`;
  }
  const long = x1 - x0 > 300 * 86400;   // spans > ~10 months: show the year, not the day
  let prevLbl = "";
  for (let i = 0; i <= 4; i++) {
    const t = x0 + ((x1 - x0) * i) / 4, lbl = DATE(t, long ? { month: "short", year: "numeric" } : undefined);
    if (lbl === prevLbl) continue;
    prevLbl = lbl;
    g += `<text x="${sx(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 4 ? "end" : "middle"}" class="axis">${DATE(t, long ? { month: "short", year: "numeric" } : undefined)}</text>`;
  }
  const defs = `<defs>${series.map((s, i) => `<linearGradient id="gr${id}_${i}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".28"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient>`).join("")}</defs>`;
  const lines = series.map((s, i) => {
    const pts = s.points.map(([t, v]) => `${sx(t).toFixed(1)},${sy(v).toFixed(1)}`);
    const last = s.points[s.points.length - 1];
    const fill = area && i === 0 && !s.dashed && s.points.length > 1
      ? `<polygon class="area" fill="url(#gr${id}_${i})" points="${sx(s.points[0][0]).toFixed(1)},${H - P.b} ${pts.join(" ")} ${sx(last[0]).toFixed(1)},${H - P.b}"/>` : "";
    return `${fill}<polyline class="ln${s.dashed ? " dash" : ""}" pathLength="1" fill="none" stroke="${s.color}" stroke-width="${s.dashed ? 1.5 : 2.5}" stroke-linejoin="round" stroke-linecap="round" points="${pts.join(" ")}"/>` +
      `<circle class="dot" cx="${sx(last[0])}" cy="${sy(last[1])}" r="4" fill="${s.color}"/>`;
  }).join("");
  CHARTS[id] = { W, H, P, x0, x1, series, money, sx, zoom };
  const legend = series.map((s) => `<span class="lg"><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("");
  return `<div class="chartbox"><svg viewBox="0 0 ${W} ${H}" class="chart${zoom ? " zoomable" : ""}" data-id="${id}" role="img">${defs}${g}${lines}<line class="hv" y1="${P.t}" y2="${H - P.b}" style="display:none"/>${zoom ? `<rect class="zsel" y="${P.t}" height="${H - P.t - P.b}" x="0" width="0" style="display:none"/>` : ""}</svg><div class="tip" style="display:none"></div></div><div class="legend">${legend}</div>`;
}

function donut(items, { size = 170, label = "" } = {}) {
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!total) return `<div class="empty small">${t("No data.")}</div>`;
  const r = 60, C = 2 * Math.PI * r; let off = 0;
  const arcs = items.map((it, i) => {
    const len = (it.value / total) * C;
    const a = `<circle class="arc" r="${r}" cx="80" cy="80" fill="none" stroke="${it.color || COLORS[i % COLORS.length]}" stroke-width="22" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" style="--d:${i * 60}ms"><title>${esc(it.label)}: ${EUR(it.value)}</title></circle>`;
    off += len; return a;
  }).join("");
  const legend = items.map((it, i) => `<div class="dl"><i style="background:${it.color || COLORS[i % COLORS.length]}"></i><span>${esc(it.label)}</span><b>${Math.round((it.value / total) * 100)}%</b></div>`).join("");
  return `<div class="donut"><svg viewBox="0 0 160 160" width="${size}" height="${size}"><g transform="rotate(-90 80 80)">${arcs}</g><text x="80" y="76" text-anchor="middle" class="dn-v">${EUR0(total)}</text><text x="80" y="96" text-anchor="middle" class="dn-l">${esc(label)}</text></svg><div class="dlegend">${legend}</div></div>`;
}

function bars(items, { fmt = INT, cf = null } = {}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return `<div class="bars">${items.map((it, i) => `<div class="bar${cf ? " click" : ""}" style="--i:${i}"${cf ? ` data-cf="${esc(cf(it))}" title="${esc(t("Show these sets"))}"` : ""}><div class="bv">${fmt(it.value)}</div><div class="bf" style="--h:${(it.value / max) * 100}%"></div><div class="bl">${esc(it.label)}</div></div>`).join("")}</div>`;
}

// Price bands and statuses for the filter drop-downs.
const PRICE_BANDS = [["p0", 0, 25], ["p25", 25, 50], ["p50", 50, 100], ["p100", 100, 200], ["p200", 200, 400], ["p400", 400, Infinity]];
const STATUS_FILTERS = [
  ["deal", "Deal now", (s, p) => p.isDeal(s)], ["low", "Lowest price so far", (s) => s.is_all_time_low],
  ["target", "Target price reached", (s) => s.target_hit], ["drop", "Price dropped this week", (s) => (s.change_7d ?? 0) <= -3],
  ["noprice", "No price yet", (s) => s.best_price == null], ["single", "Found at one shop only", (s) => s.offers_live === 1],
  ["suspect", "Link to check", (s) => s.offers_suspect > 0], ["error", "Has errors", (s) => s.offers_error > 0],
];

/** Solved (green) and new (red) side by side per period, with the net change as a title. */
function pairBars(rows) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.a, r.b]));
  return `<div class="pbars">${rows.map((r, i) => `<div class="pbar" style="--i:${i}" title="${esc(r.label)}: ${esc(t("{n} solved", { n: r.a }))}, ${esc(t("{n} new", { n: r.b }))}">
    <div class="pcols"><div class="pc ok" style="--h:${(r.a / max) * 100}%"><span>${r.a || ""}</span></div><div class="pc bad" style="--h:${(r.b / max) * 100}%"><span>${r.b || ""}</span></div></div>
    <div class="bl">${esc(r.label)}</div></div>`).join("")}</div>
    <div class="legend"><span class="lg"><i style="background:var(--ar-green)"></i>${esc(t("Solved"))}</span><span class="lg"><i style="background:var(--ar-red)"></i>${esc(t("New"))}</span></div>`;
}

function spark(vals) {
  if (!vals || vals.length < 2) return `<div class="spark ph-spark"></div>`;
  const min = Math.min(...vals), max = Math.max(...vals), w = 100, h = 26;
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / (max - min || 1)) * (h - 4)).toFixed(1)}`).join(" ");
  const down = vals[vals.length - 1] <= vals[0];
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="spark"><polyline class="ln" pathLength="1" fill="none" stroke="${down ? "#00852b" : "#d01012"}" stroke-width="1.8" points="${pts}"/></svg>`;
}

function ring(score, size = 44) {
  const r = 17, C = 2 * Math.PI * r, v = Math.max(0, Math.min(100, score || 0));
  const col = v >= 70 ? "#00852b" : v >= 45 ? "#f5a800" : "var(--ar-muted)";
  return `<div class="ring" style="width:${size}px;height:${size}px" title="${t("Deal score {n}/100", { n: v })}"><svg viewBox="0 0 44 44"><circle cx="22" cy="22" r="${r}" class="ring-bg"/><circle cx="22" cy="22" r="${r}" class="ring-fg" stroke="${col}" stroke-dasharray="${C}" style="--off:${C * (1 - v / 100)};--c:${C}" transform="rotate(-90 22 22)"/></svg><span>${v}</span></div>`;
}

const LOGO = `<svg viewBox="0 0 64 64" class="logo" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#14172b"/><path d="M6 32C14 19 23 13 32 13s18 6 26 19c-8 13-17 19-26 19S14 45 6 32Z" fill="#fff6dd"/><circle cx="32" cy="32" r="12" fill="#c9921a"/><circle cx="32" cy="32" r="6" fill="#14172b"/><circle cx="35" cy="29" r="2.2" fill="#fff"/></svg>`;

/** A stored source of a log line (who did it) in words. */
const SOURCE_WORDS = { relay: "your browser (relay)", userscript: "Tampermonkey userscript", panel: "panel (you)", server: "server", schedule: "schedule (automatic)", import: "import", user: "manual" };
const srcName = (k) => (k ? (SOURCE_WORDS[k] ? t(SOURCE_WORDS[k]) : String(k)) : "");


// ------------------------------------------------------------------ styles
const STYLE = `

:host{--ar-bg:var(--primary-background-color,#f3f4f7);--ar-card:var(--card-background-color,#fff);--ar-text:var(--primary-text-color,#1b1c20);--ar-muted:var(--secondary-text-color,#6b6f7a);
--ar-line:var(--divider-color,#e1e3e8);--ar-accent:var(--primary-color,#0057a6);--ar-on-accent:var(--text-primary-color,#fff);--ar-soft:color-mix(in srgb,var(--ar-accent) 10%,var(--ar-card));
--ar-red:#d0332f;--ar-green:#00852b;--ar-yellow:#f5a800;--ar-purple:#7a3c9e;--ar-radius:16px;--ar-shadow:var(--ha-card-box-shadow,0 1px 2px rgba(0,0,0,.06),0 4px 16px rgba(0,0,0,.06));
display:block;background:var(--ar-bg);color:var(--ar-text);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,Roboto,system-ui,sans-serif);-webkit-font-smoothing:antialiased}
/* colour themes (Settings → Colours); none set = the colours of your Home Assistant theme */
:host([data-colors="argus"]){--ar-accent:#b07d12;--ar-on-accent:#fff;--ar-soft:#fbf3dc}
:host([data-colors="ocean"]){--ar-accent:#0067b8;--ar-on-accent:#fff}
:host([data-colors="forest"]){--ar-accent:#1b7f3b;--ar-on-accent:#fff}
:host([data-colors="violet"]){--ar-accent:#7a3c9e;--ar-on-accent:#fff}
:host([data-colors="sunset"]){--ar-accent:#e3611a;--ar-on-accent:#fff}
:host([data-colors="light"]){--ar-bg:#f3f4f7;--ar-card:#fff;--ar-text:#1b1c20;--ar-muted:#6b6f7a;--ar-line:#e1e3e8;--ar-accent:#0057a6;--ar-on-accent:#fff;color-scheme:light}
:host([data-colors="dark"]){--ar-bg:#111318;--ar-card:#1c1f26;--ar-text:#e8eaf0;--ar-muted:#9aa0ad;--ar-line:#2c313b;--ar-accent:#e0b04a;--ar-on-accent:#14172b;--ar-shadow:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.35);color-scheme:dark}
.colrow{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:8px;margin-top:10px}
.colsw{display:flex;flex-direction:column;gap:6px;align-items:center;padding:10px 6px;border:2px solid var(--ar-line);border-radius:12px;background:var(--ar-card);cursor:pointer;font-size:13px}
.colsw.on{border-color:var(--ar-accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--ar-accent) 25%,transparent)}.colsw i{display:flex;gap:3px}.colsw i b{width:18px;height:18px;border-radius:50%;border:1px solid rgba(0,0,0,.12)}
input[type=range].colrange{width:100%;accent-color:var(--ar-accent)}
*{box-sizing:border-box}[hidden]{display:none!important}
.wrap{max-width:1280px;margin:0 auto;padding:12px 16px 64px}
header{display:flex;align-items:center;gap:12px;padding:6px 0 14px}
.logo{width:40px;height:28px;flex:none;filter:drop-shadow(0 2px 3px rgba(20,23,43,.35))}img.logo{width:44px;height:44px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.18))}
h1{margin:0;font-size:21px;font-weight:700;letter-spacing:-.01em}
.meta{font-size:12px;color:var(--ar-muted)}
.hsp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:99px;background:var(--ar-soft);font-size:12px;color:var(--ar-muted)}
.dotst{width:8px;height:8px;border-radius:50%;background:var(--ar-green);display:inline-block}.dotst.warn{background:var(--ar-yellow)}.dotst.bad{background:var(--ar-red)}
button{font:inherit;color:inherit}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:10px;border:1px solid transparent;background:var(--ar-accent);color:var(--ar-on-accent);cursor:pointer;font-weight:500;transition:transform .15s,box-shadow .15s,background .15s,opacity .15s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.12)}.btn:active{transform:translateY(0)}
.btn.ghost{background:var(--ar-card);color:var(--ar-text);border-color:var(--ar-line)}.btn.danger{background:var(--ar-card);color:var(--ar-red);border-color:color-mix(in srgb,var(--ar-red) 40%,var(--ar-line))}
a.btn{text-decoration:none}.btn[disabled]{opacity:.5;pointer-events:none}.btn.sm{padding:5px 10px;font-size:13px;border-radius:8px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .7s linear infinite}
.erow.on{background:var(--ar-soft)}.setlink{cursor:pointer;color:inherit;text-decoration:none;border-bottom:1px dashed var(--ar-muted)}.setlink:hover{color:var(--ar-accent);border-color:var(--ar-accent)}
.res{display:inline-flex;gap:4px;align-items:center;font-size:12px;padding:2px 8px;border-radius:99px;margin:1px 2px 1px 0;white-space:nowrap}.res.ok{background:color-mix(in srgb,var(--ar-green) 16%,transparent);color:var(--ar-green)}
.res.fail{background:color-mix(in srgb,var(--ar-red) 14%,transparent);color:var(--ar-red)}.res.skip{background:var(--ar-soft);color:var(--ar-muted)}.res.warn{background:color-mix(in srgb,var(--ar-yellow) 18%,transparent);color:color-mix(in srgb,var(--ar-yellow) 70%,var(--ar-text))}div.res{border-radius:8px;display:flex}
.tbl.log tr.lrow td:first-child{border-left:3px solid transparent}.tbl.log tr.lv-ok td:first-child{border-left-color:var(--ar-green)}.tbl.log tr.lv-error td:first-child{border-left-color:var(--ar-red)}.tbl.log tr.lv-warning td:first-child{border-left-color:var(--ar-yellow)}
.tag{white-space:nowrap}.chip.okc.on{background:var(--ar-green)}
@media(max-width:640px){.tbl.log tr:not(:has(td[colspan])) > :nth-child(3),.tbl.log tr:not(:has(td[colspan])) > :nth-child(5){display:none}.tbl.log td,.tbl.log th{padding:6px 4px}.tbl.log td:first-child{font-size:11px;white-space:normal!important;min-width:54px}.otbl .ou{min-width:150px}}.chip.failc.on{background:var(--ar-red)}
.item{background:var(--ar-soft);border-radius:12px;padding:12px;margin:4px 0 8px;animation:rise .25s both}.itemhead{display:flex;gap:12px;align-items:flex-start;margin-bottom:8px}
.itemhead img,.itemhead .ph{width:72px;height:72px;object-fit:contain;background:#fff;border-radius:10px;flex:none;display:flex;align-items:center;justify-content:center;font-size:32px}
.item .tbl{background:var(--ar-card);border-radius:10px}.oact{white-space:nowrap}.oact .btn{margin:0 2px 2px 0}tr.orow.focus td{background:color-mix(in srgb,var(--ar-accent) 8%,transparent)}
tr.efix > td{padding:0 4px 8px}
@media(max-width:640px){.item{max-width:calc(100vw - 44px);position:sticky;left:0;padding:8px}.itemhead img,.itemhead .ph{width:48px;height:48px;font-size:22px}
.otbl,.otbl tbody{display:block}.otbl tr:first-child{display:none}.otbl tr.orow{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:8px 4px;border-bottom:1px solid var(--ar-line)}
.otbl tr.orow td{border:0;padding:2px}.otbl tr.orow td:nth-child(1),.otbl tr.orow td:nth-child(2){grid-column:1/-1}.otbl td.num{text-align:left}.otbl .ou{min-width:0}.otbl .oact{align-self:end;text-align:right}}.form label .mbadge{align-self:flex-start;margin:2px 0}.mbadge{font-size:10px;font-weight:700;padding:1px 6px;border-radius:6px;background:var(--ar-purple);color:#fff;vertical-align:1px}.abadge{font-size:10px;font-weight:600;padding:1px 6px;border-radius:6px;background:var(--ar-soft);color:var(--ar-muted);vertical-align:1px}
.otbl input{padding:6px 8px;font-size:13px}.otbl .ou{min-width:220px;width:100%}.otbl .op{width:96px}.orow.dirty td{background:color-mix(in srgb,var(--ar-yellow) 10%,transparent)}.fixbox{background:var(--ar-soft);border-radius:12px;padding:12px;margin:2px 0 8px;animation:rise .25s both}
.rule{border:1px solid var(--ar-line);border-radius:14px;padding:12px 14px;margin-bottom:10px;display:flex;gap:12px;align-items:flex-start;transition:border-color .2s}.rule:hover{border-color:var(--ar-accent)}
.rule.off{opacity:.55}.rule .sum{font-size:13px;color:var(--ar-muted);margin-top:4px;line-height:1.6}.tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;background:var(--ar-soft);margin:2px 4px 2px 0}
.switch{position:relative;width:40px;height:22px;flex:none;cursor:pointer}.switch input{display:none}.switch i{position:absolute;inset:0;border-radius:99px;background:var(--ar-line);transition:background .2s}
.switch i::after{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:transform .2s cubic-bezier(.3,1.4,.5,1)}.switch input:checked+i{background:var(--ar-accent)}.switch input:checked+i::after{transform:translateX(18px)}
.trig{display:grid;grid-template-columns:24px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--ar-line)}.trig:last-child{border:0}.trig select,.trig input{padding:6px 8px}
.tgt{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px;border:1px solid var(--ar-line);border-radius:10px;margin-bottom:6px}.tgt select,.tgt input{padding:6px 8px}
.jobbar{display:flex;gap:12px;align-items:center;background:var(--ar-card);border-radius:14px;padding:10px 14px;margin-bottom:12px;box-shadow:var(--ar-shadow);border-left:4px solid var(--ar-accent)}.jobbar.in{animation:rise .35s both}
.jobbar .spin{color:var(--ar-accent);flex:none}.jt{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lk{font-size:12px;font-weight:600;padding:2px 7px;border-radius:6px;white-space:nowrap}.lk.suspect{background:color-mix(in srgb,var(--ar-red) 15%,transparent);color:var(--ar-red)}
.lk.ok,.lk.confirmed{background:color-mix(in srgb,var(--ar-green) 15%,transparent);color:var(--ar-green)}.lk.unknown{background:var(--ar-soft);color:var(--ar-muted)}
.actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.action{border:1px solid var(--ar-line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:8px}
.action b{font-size:15px}.action p{margin:0;font-size:13px}.action .btn{align-self:flex-start;margin-top:auto}
/* section switch */
.seg{display:flex;gap:6px;background:var(--ar-card);padding:5px;border-radius:14px;box-shadow:var(--ar-shadow);position:relative;margin-bottom:12px}
.seg button{flex:1;border:0;background:none;padding:11px 12px;border-radius:10px;cursor:pointer;font-weight:600;font-size:15px;color:var(--ar-muted);position:relative;z-index:1;transition:color .25s}
.seg button.on{color:var(--ar-on-accent)}
.seg .ind{position:absolute;top:5px;bottom:5px;border-radius:10px;background:var(--ar-accent);transition:left .35s cubic-bezier(.3,1.3,.5,1),width .35s cubic-bezier(.3,1.3,.5,1);box-shadow:0 3px 10px color-mix(in srgb,var(--ar-accent) 40%,transparent)}
.seg small{display:block;font-weight:400;font-size:11px;opacity:.8}
.sub{display:flex;gap:4px;margin:0 0 14px;overflow-x:auto;scrollbar-width:none}
.sub button{border:0;background:none;padding:8px 14px;border-radius:99px;cursor:pointer;color:var(--ar-muted);font-weight:500;white-space:nowrap;transition:background .2s,color .2s}
.sub button:hover{background:var(--ar-soft)}.sub button.on{background:var(--ar-soft);color:var(--ar-accent)}
.sub .secretlink{flex:1;min-width:40px;opacity:0;cursor:default;padding:0}.sub .count{font-size:11px;background:var(--ar-accent);color:var(--ar-on-accent);border-radius:99px;padding:1px 7px;margin-left:5px}
/* kpis */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--ar-card);border-radius:var(--ar-radius);padding:14px 16px;box-shadow:var(--ar-shadow);position:relative;overflow:hidden}
.kpi small{color:var(--ar-muted);font-size:12px;display:flex;align-items:center;gap:6px}.kpi b{display:block;font-size:24px;font-weight:700;margin-top:4px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .sub2{font-size:12px;color:var(--ar-muted);margin-top:2px}.kpi.hl::before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--c,var(--ar-accent))}
.up{color:var(--ar-green)}.down{color:var(--ar-red)}
/* filter bar */
.fbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.search{flex:1;min-width:200px;position:relative}.search input{width:100%;padding-left:34px}.search::before{content:"🔍";position:absolute;left:11px;top:50%;transform:translateY(-50%);font-size:13px;opacity:.6}
input,select,textarea{font:inherit;padding:9px 11px;border-radius:10px;border:1px solid var(--ar-line);background:var(--ar-card);color:var(--ar-text);transition:border-color .15s,box-shadow .15s;min-width:0}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--ar-accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--ar-accent) 20%,transparent)}
input[type=range]{padding:0;accent-color:var(--ar-accent)}input[type=checkbox]{accent-color:var(--ar-accent);width:16px;height:16px}
.thr{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ar-muted);background:var(--ar-card);border:1px solid var(--ar-line);border-radius:10px;padding:6px 12px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.chip{padding:5px 12px;border-radius:99px;background:var(--ar-card);border:1px solid var(--ar-line);cursor:pointer;font-size:13px;transition:all .2s;user-select:none}
.bk-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px;position:sticky;top:0;z-index:3;background:var(--ar-card);padding:6px 0}
.tbl.bk input,.tbl.bk select{padding:5px 7px;font-size:13px;min-width:90px;width:100%}.tbl.bk input[type=checkbox]{min-width:0;width:auto}.tbl.bk .bk-num{width:84px;min-width:70px}.tbl.bk .bk-wide{min-width:200px}
.tbl.bk input[type=date]{min-width:130px}.tbl.bk td{padding:4px 5px;vertical-align:middle}.tbl.bk td.c{text-align:center}.tbl.bk tr.dirty td{background:color-mix(in srgb,var(--ar-yellow) 12%,transparent)}
.tbl.bk tr.bk-copy td{border-top:0}.tbl.bk tr.bk-new td{background:color-mix(in srgb,var(--ar-green) 7%,transparent)}.tbl.bk .bk-sticky{position:sticky;left:0;background:var(--ar-card);z-index:1;white-space:nowrap}
.labform{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.labres{border:1px solid var(--ar-line);border-left:4px solid var(--ar-muted);border-radius:12px;padding:12px 14px;background:var(--ar-bg)}
.labres.lv-ok{border-left-color:var(--ar-green)}.labres.lv-warn{border-left-color:var(--ar-yellow)}.labres.lv-bad{border-left-color:var(--ar-red)}
code{word-break:break-all}
@media(max-width:640px){.rule{flex-wrap:wrap}.rule>div:last-child{width:100%;justify-content:flex-start!important}.labgrid{flex-direction:column}}
.labres .kv{display:grid;grid-template-columns:minmax(120px,180px) 1fr;gap:10px;justify-content:start;text-align:left}.labres .kv b{text-align:left;font-weight:600}
.labgrid{display:flex;gap:14px;align-items:flex-start;justify-content:space-between}.labgrid>div{flex:1;min-width:0}.labgrid .kv b{word-break:break-word}
.labfind{list-style:none;padding:0;margin:0;display:grid;gap:6px}.labfind li{display:flex;gap:8px;font-size:14px;line-height:1.4}.labfind li.lv-bad{color:var(--ar-red)}.labfind li.lv-warn{color:var(--ar-yellow)}
.labhead{white-space:pre-wrap;word-break:break-all;font-size:11px;max-height:220px;overflow:auto;background:var(--ar-card);padding:8px;border-radius:8px}
.bc-warn{margin-top:10px;padding:8px 10px;border-radius:8px;font-size:13px;white-space:normal;background:color-mix(in srgb,var(--ar-yellow) 18%,transparent);color:color-mix(in srgb,var(--ar-yellow) 60%,var(--ar-text))}
.about-head{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.about-logo{width:112px;height:112px;border-radius:24px}.about-letters{display:grid;gap:10px}.about-letter{display:flex;gap:12px;align-items:flex-start}
.about-l{flex:0 0 40px;height:40px;border-radius:8px;background:#E4572E;color:#FFF6EA;display:flex;align-items:center;justify-content:center;font-size:22px}
.coffee{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:10px;background:#FFDD00;color:#111A2E;font-weight:700;text-decoration:none;font-size:14px}.coffee:hover{filter:brightness(.95)}
.bc-pick{display:flex;gap:6px;flex-wrap:wrap;align-items:center;border:1px solid var(--ar-line);border-radius:10px;padding:6px;background:var(--ar-card)}.bc-chip{display:inline-flex;gap:6px;align-items:center;cursor:default}.bc-chip.bad{border-color:var(--ar-red);color:var(--ar-red)}
.bc-x{border:0;background:none;color:inherit;cursor:pointer;font-size:16px;line-height:1;padding:0 2px}.bc-in{position:relative;flex:1;min-width:200px}.bc-in input{width:100%;border:0;background:transparent;box-sizing:border-box}
.bc-sug{position:absolute;z-index:5;left:0;right:0;top:100%;background:var(--ar-card);border:1px solid var(--ar-line);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.15);max-height:260px;overflow:auto}.bc-opt{padding:7px 10px;cursor:pointer;font-size:13px}.bc-opt.on,.bc-opt:hover{background:var(--ar-soft,rgba(0,0,0,.06))}
.chip:hover{border-color:var(--ar-accent)}.chip.on{background:var(--ar-accent);color:var(--ar-on-accent);border-color:transparent}.chip.sm{font-size:12px;padding:3px 10px}
.toggle{display:inline-flex;border:1px solid var(--ar-line);border-radius:10px;overflow:hidden}.toggle button{border:0;background:var(--ar-card);padding:8px 11px;cursor:pointer}.toggle button.on{background:var(--ar-soft);color:var(--ar-accent)}
/* layout */
.cols{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}@media(max-width:980px){.cols{grid-template-columns:minmax(0,1fr)}}
.panel{background:var(--ar-card);border-radius:var(--ar-radius);padding:16px;box-shadow:var(--ar-shadow);margin-bottom:16px}
.panel h3{margin:0 0 12px;font-size:16px;display:flex;align-items:center;gap:8px}.panel h3 .hsp{flex:1}
.panel p{margin:0 0 10px;color:var(--ar-muted);font-size:14px;line-height:1.5}
h2.sec{font-size:16px;margin:18px 0 10px;display:flex;align-items:center;gap:8px}h2.sec .n{font-size:12px;color:var(--ar-muted);font-weight:500}
.addtile{align-items:center;justify-content:center;text-align:center;min-height:230px;border:2px dashed color-mix(in srgb,var(--ar-accent) 45%,transparent);background:var(--ar-soft);color:var(--ar-accent);box-shadow:none;gap:8px}
.addtile .plus{font-size:54px;line-height:1;font-weight:300}.addtile:hover{background:color-mix(in srgb,var(--ar-accent) 16%,var(--ar-card))}
.card .img{position:relative}.cbtns{position:absolute;right:4px;bottom:4px;display:flex;gap:4px}
.cbtn{width:28px;height:28px;border-radius:50%;border:0;background:var(--ar-accent);color:var(--ar-on-accent);font-weight:700;font-size:15px;line-height:1;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.35);display:grid;place-items:center;padding:0}
.cbtn:hover{transform:scale(1.1)}.vbadge{color:var(--ar-accent);font-weight:700;cursor:help}.shop.click{cursor:pointer;transition:box-shadow .15s}.shop.click:hover{box-shadow:0 0 0 2px var(--ar-accent)}.tlx li.tlr{display:flex;gap:10px;align-items:flex-start}.tlx .tthumb{position:relative;flex:0 0 72px;width:72px;height:72px;border-radius:10px;overflow:hidden;background:var(--ar-soft)}.tlx .tthumb img{width:100%;height:100%;object-fit:contain}.tlx .tthumb .ph{display:grid;place-items:center;width:100%;height:100%;font-size:28px}.tlx .tthumb .cbtns{right:2px;bottom:2px;gap:2px}.tlx .tthumb .cbtn{width:22px;height:22px;font-size:11px}.tlx .tthumb .cbtn.off{min-width:22px;padding:0 4px;font-size:10px}.tlx .tbody{min-width:0;flex:1}.tlx a{color:var(--ar-accent)}.cbtn.off{width:auto;min-width:28px;padding:0 7px;border-radius:14px;background:var(--ar-card,#fff);color:var(--ar-accent);font-size:13px}.prefill{display:flex;gap:12px;align-items:center;padding:10px;margin:0 0 12px;border-radius:12px;background:var(--ar-soft)}
.prefill .img{width:72px;height:72px;display:grid;place-items:center}.prefill .img img{max-width:72px;max-height:72px;object-fit:contain}.prefill>div:nth-child(2){flex:1}
.radio label.dis{opacity:.5;cursor:not-allowed}.radio label.dis input{cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:14px}
.grid .card{content-visibility:auto;contain-intrinsic-size:auto 300px}.enter .grid .card:nth-child(n+13){animation:none}
@media(prefers-reduced-motion:reduce){.enter>*,.enter .card,.enter .shop{animation:none!important}}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.two{grid-template-columns:1fr}}
/* cards */
.card{background:var(--ar-card);border-radius:var(--ar-radius);padding:10px 10px 12px;cursor:pointer;position:relative;box-shadow:var(--ar-shadow);display:flex;flex-direction:column;gap:3px;transition:transform .2s cubic-bezier(.3,1.4,.5,1),box-shadow .2s;outline:none}
.card:hover,.card:focus-visible{transform:translateY(-3px);box-shadow:0 10px 28px rgba(0,0,0,.14)}
.card .img{height:130px;border-radius:12px;background:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;margin-bottom:6px;position:relative}
.card .img img{max-width:92%;max-height:118px;object-fit:contain;transition:transform .3s}.card:hover .img img{transform:scale(1.05)}
.card .img .ph{font-size:40px;opacity:.5}
.card .n{font-weight:600;font-size:14px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:36px}
.card .m{color:var(--ar-muted);font-size:12px}.card .row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.card .p{font-size:20px;font-weight:700;letter-spacing:-.02em}.card s{color:var(--ar-muted);font-size:13px}
.badges{position:absolute;top:16px;left:16px;display:flex;flex-direction:column;gap:4px;z-index:1}
.badge{font-size:11px;font-weight:700;padding:3px 8px;border-radius:7px;color:#fff;background:var(--ar-green);width:fit-content;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.badge.red{background:var(--ar-red)}.badge.blue{background:#0057a6}.badge.purple{background:var(--ar-purple)}.badge.yellow{background:var(--ar-yellow);color:#241a00}.badge.grey{background:#6c6e68}
.card .ring{position:absolute;top:14px;right:14px;z-index:1;background:var(--ar-card);border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.15)}
.trend{font-size:12px;font-weight:600}.stars{color:var(--ar-yellow);letter-spacing:1px;font-size:13px}
.spark{width:100%;height:26px;margin-top:2px}.ph-spark{border-bottom:1px dashed var(--ar-line);height:14px;margin-bottom:12px}
/* hero */
.hero{display:grid;grid-template-columns:220px 1fr;gap:18px;background:linear-gradient(135deg,color-mix(in srgb,var(--ar-yellow) 18%,var(--ar-card)),var(--ar-card) 60%);border-radius:20px;padding:16px;box-shadow:var(--ar-shadow);margin-bottom:6px;cursor:pointer;position:relative;overflow:hidden;transition:transform .25s}
.hero:hover{transform:translateY(-2px)}.hero .img{height:170px;background:#fff;border-radius:14px;display:flex;align-items:center;justify-content:center}.hero .img img{max-width:92%;max-height:160px}
.hero .k{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--ar-muted);font-weight:700}.hero h2{margin:4px 0 6px;font-size:22px}
.hero .p{font-size:34px;font-weight:800;letter-spacing:-.03em}.hero .ring{position:absolute;right:16px;top:16px}
@media(max-width:600px){.hero{grid-template-columns:1fr}}
/* timeline */
.tl{list-style:none;margin:0;padding:0}.tl li{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--ar-line);font-size:13px;cursor:pointer;align-items:flex-start}.tl li:last-child{border:0}
.tl .ic{width:28px;height:28px;border-radius:9px;display:flex;align-items:center;justify-content:center;flex:none;background:var(--ar-soft)}
.tl .t{color:var(--ar-muted);font-size:11px}
/* tables */
.tbl{color:inherit;width:100%;border-collapse:collapse;font-size:14px}.tbl th{text-align:left;font-size:12px;color:var(--ar-muted);font-weight:600;padding:8px;border-bottom:1px solid var(--ar-line);white-space:nowrap}
.tbl th[data-sort]{cursor:pointer}.tbl th[data-sort]:hover{color:var(--ar-accent)}
.tbl td{padding:8px;border-bottom:1px solid var(--ar-line);vertical-align:top}.tbl tr.click{cursor:pointer;transition:background .15s}.tbl tr.click:hover{background:var(--ar-soft)}
.tbl .num{text-align:right;font-variant-numeric:tabular-nums}.tscroll{overflow-x:auto}
/* charts */
.chartbox{position:relative}.chart.zoomable{cursor:crosshair;touch-action:pan-y;user-select:none;-webkit-user-select:none}.zsel{fill:var(--ar-accent);fill-opacity:.15;stroke:var(--ar-accent);stroke-opacity:.5}.zbar{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin:0 0 8px}.zbar input[type=date]{font:inherit;padding:3px 6px;border-radius:8px;border:1px solid var(--ar-line);background:var(--ar-card);color:var(--ar-text)}.pstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:10px}.pstats .stat{padding:8px 10px;border-radius:10px;background:var(--ar-soft)}.pstats small{display:block;color:var(--ar-muted);font-size:11px}.pstats b{font-size:15px}.tbl td.num{text-align:right;white-space:nowrap}.chart{width:100%;height:auto;display:block}.gl{stroke:var(--ar-line)}.axis{font-size:11px;fill:var(--ar-muted)}.hv{stroke:var(--ar-muted);stroke-dasharray:3 3}
.ln{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.1s cubic-bezier(.4,0,.2,1) forwards}.ln.dash{stroke-dasharray:.012 .01;stroke-dashoffset:0;animation:fade .8s both}
.area{animation:fade 1s .4s both}.dot{animation:pop .4s .9s both;transform-box:fill-box;transform-origin:center}
.tip{position:absolute;top:8px;left:60px;background:var(--ar-card);border:1px solid var(--ar-line);border-radius:10px;padding:8px 10px;font-size:12px;pointer-events:none;box-shadow:0 6px 18px rgba(0,0,0,.15);white-space:nowrap;z-index:2}
.tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin-top:6px;color:var(--ar-muted)}.lg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.donut{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.arc{animation:arc .9s cubic-bezier(.4,0,.2,1) both;animation-delay:var(--d)}
.dn-v{font-size:17px;font-weight:700;fill:var(--ar-text)}.dn-l{font-size:10px;fill:var(--ar-muted)}
.dlegend{flex:1;min-width:150px}.dl{display:flex;align-items:center;gap:8px;font-size:13px;padding:3px 0}.dl i{width:10px;height:10px;border-radius:3px;flex:none}.dl span{flex:1}
.bars{display:flex;align-items:flex-end;gap:6px;height:170px;padding-top:18px;overflow-x:auto}
[data-cf]{cursor:pointer}.stat.click{transition:box-shadow .15s}.stat.click:hover,.chip[data-cf]:hover{box-shadow:0 0 0 2px var(--ar-accent)}.bar.click:hover .bf{filter:brightness(1.15)}.fmore{flex-wrap:wrap;gap:8px;margin-top:-4px}.ff{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--ar-muted)}.ff select{max-width:200px}
.bar{flex:1;min-width:30px;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}
.bf{width:70%;height:var(--h);background:linear-gradient(var(--ar-accent),color-mix(in srgb,var(--ar-accent) 60%,var(--ar-card)));border-radius:6px 6px 2px 2px;animation:grow .8s cubic-bezier(.3,1.2,.5,1) both;animation-delay:calc(var(--i) * 40ms);transform-origin:bottom}
.pbars{display:flex;align-items:flex-end;gap:4px;height:170px;padding-top:14px;overflow-x:auto}.pbar{flex:1;min-width:0;display:flex;flex-direction:column;height:100%;justify-content:flex-end}
.pcols{flex:1;display:flex;align-items:flex-end;gap:2px;justify-content:center}.pc{width:42%;max-width:16px;height:var(--h);min-height:1px;border-radius:4px 4px 1px 1px;position:relative;animation:grow .8s cubic-bezier(.3,1.2,.5,1) both;animation-delay:calc(var(--i) * 25ms);transform-origin:bottom}
.pc.ok{background:var(--ar-green)}.pc.bad{background:var(--ar-red)}.pc span{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);font-size:10px;color:var(--ar-muted)}
.pbar .bl{text-align:center;white-space:nowrap}
.bv{font-size:11px;color:var(--ar-muted);margin-bottom:3px}.bl{font-size:11px;color:var(--ar-muted);margin-top:4px}
.ring{position:relative;display:inline-block}.ring svg{width:100%;height:100%}.ring-bg{fill:none;stroke:var(--ar-line);stroke-width:4}
.ring-fg{fill:none;stroke-width:4;stroke-linecap:round;stroke-dashoffset:var(--off);animation:ring 1s cubic-bezier(.4,0,.2,1) both}
.ring span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
/* misc */
.empty{padding:36px 20px;text-align:center;color:var(--ar-muted);background:var(--ar-card);border-radius:var(--ar-radius);border:1px dashed var(--ar-line)}.empty.small{padding:18px;font-size:13px;background:none}
.empty .big{font-size:40px;display:block;margin-bottom:8px}
.banner{display:flex;gap:10px;align-items:center;background:color-mix(in srgb,var(--ar-yellow) 16%,var(--ar-card));border:1px solid color-mix(in srgb,var(--ar-yellow) 45%,transparent);border-radius:12px;padding:10px 14px;margin-bottom:14px;font-size:13px}
.banner a{color:var(--ar-accent);cursor:pointer;text-decoration:underline}
a{color:var(--ar-accent)}.err{color:var(--ar-red);font-size:12px}.ok{color:var(--ar-green)}.tbl .bad,.panel .bad{color:var(--ar-red)}.tbl .warn,.panel .warn{color:var(--ar-yellow)}.tbl td.ell{max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.muted{color:var(--ar-muted)}
.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px}
.form label{display:flex;flex-direction:column;font-size:12px;color:var(--ar-muted);gap:4px;font-weight:500}.form label.chk{flex-direction:row;align-items:center;gap:8px;font-size:14px;color:var(--ar-text)}
.hint{font-size:12px;margin-top:-4px;min-height:16px}
.radio{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}.radio label{flex:1;min-width:200px;border:2px solid var(--ar-line);border-radius:12px;padding:12px;cursor:pointer;transition:border-color .2s,background .2s}
.radio label.on{border-color:var(--ar-accent);background:var(--ar-soft)}.radio input{display:none}.radio b{display:block}.radio span{font-size:12px;color:var(--ar-muted)}
.drop{border:2px dashed var(--ar-line);border-radius:16px;padding:30px;text-align:center;transition:all .2s;cursor:pointer;background:var(--ar-card)}
.drop.over{border-color:var(--ar-accent);background:var(--ar-soft);transform:scale(1.01)}.drop .big{font-size:36px;display:block;margin-bottom:6px}
.steps{display:flex;gap:8px;margin-bottom:14px;font-size:13px}.steps span{padding:4px 12px;border-radius:99px;background:var(--ar-card);border:1px solid var(--ar-line);color:var(--ar-muted)}.steps span.on{background:var(--ar-accent);color:var(--ar-on-accent);border-color:transparent}
.st{display:inline-flex;width:22px;height:22px;border-radius:50%;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff}.st.ok{background:var(--ar-green)}.st.warning{background:var(--ar-yellow);color:#241a00}.st.error{background:var(--ar-red)}
.iss{font-size:12px;line-height:1.4}.iss .error{color:var(--ar-red)}.iss .warning{color:#9a6a00}.iss .info{color:var(--ar-muted)}
.sumpills{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.sumpills span{padding:6px 12px;border-radius:10px;font-size:13px;font-weight:600;background:var(--ar-soft)}
.shops{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.shop{background:var(--ar-card);border-radius:var(--ar-radius);padding:14px;box-shadow:var(--ar-shadow)}.shop h4{margin:0 0 8px;display:flex;align-items:center;gap:8px}
.meter{height:8px;border-radius:99px;background:var(--ar-line);overflow:hidden;margin:8px 0}.meter i{display:block;height:100%;background:var(--ar-green);border-radius:99px;animation:grow-x .9s cubic-bezier(.4,0,.2,1) both;transform-origin:left}
.kv{display:flex;justify-content:space-between;font-size:13px;padding:2px 0}.kv span{color:var(--ar-muted)}
.skel{background:linear-gradient(90deg,var(--ar-line) 25%,color-mix(in srgb,var(--ar-line) 40%,var(--ar-card)) 50%,var(--ar-line) 75%);background-size:200% 100%;animation:shimmer 1.3s infinite;border-radius:var(--ar-radius)}
/* dialog */
dialog{border:0;border-radius:22px;padding:0;overflow:auto;max-width:920px;width:calc(100vw - 24px);max-height:calc(100vh - 32px);background:var(--ar-card);color:var(--ar-text);box-shadow:0 24px 80px rgba(0,0,0,.35)}
dialog[open]{animation:dlg .32s cubic-bezier(.3,1.3,.5,1)}dialog.closing{animation:dlgout .18s ease-in forwards}
dialog::backdrop{background:rgba(10,12,20,.55);backdrop-filter:blur(3px);animation:fade .25s}
.dhead{display:grid;grid-template-columns:150px 1fr auto;gap:16px;padding:18px 20px;border-bottom:1px solid var(--ar-line);position:sticky;top:0;background:var(--ar-card);z-index:3}
.dhead .img{height:110px;background:#fff;border-radius:12px;display:flex;align-items:center;justify-content:center}.dhead .img img{max-width:92%;max-height:100px}
.dhead h2{margin:0 0 4px;font-size:20px}.dbody{padding:16px 20px 20px}.x{border:0;background:var(--ar-soft);width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:18px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:12px 0}.stat{background:var(--ar-soft);border-radius:12px;padding:8px 10px}.stat small{display:block;font-size:11px;color:var(--ar-muted)}.stat b{font-size:15px}
fieldset{border:1px solid var(--ar-line);border-radius:14px;padding:12px 14px 4px;margin:0 0 12px}legend{padding:0 6px;font-weight:600;font-size:14px}
@media(max-width:640px){.dhead{grid-template-columns:72px 1fr;gap:12px;padding:14px}.dhead .img{height:72px}.dhead .img img{max-height:64px}.dhead h2{font-size:17px;padding-right:40px}
.dhead>div:last-child{position:absolute;top:12px;right:12px}.dhead .ring{display:none}.dbody{padding:12px 14px 16px}.axis{font-size:22px}}
/* toast */
.ticker{position:fixed;left:0;right:0;bottom:0;height:30px;overflow:hidden;z-index:15;background:var(--ar-card);border-top:1px solid var(--ar-line);font-size:13px;display:flex;align-items:center}
.ticker:empty{display:none}.ticker .tkv{flex:1;overflow:hidden;height:100%;display:flex;align-items:center;min-width:0}.ticker .tk{display:inline-flex;gap:28px;white-space:nowrap;will-change:transform}
.ticker .fixed{color:var(--ar-ok,#1a7f37)}
details[open] .dfhint{display:none}.wsg{display:grid;grid-template-columns:max-content 1fr;gap:10px 16px;align-items:center;font-size:14px}.wsg .rng{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--ar-muted)}.wsg input{width:110px}
@media(max-width:560px){.wsg{grid-template-columns:1fr;gap:4px}.wsg .rng{margin-bottom:8px}}
.ticker .ti{cursor:pointer;display:inline-flex;gap:6px;align-items:center;border:0;background:none;color:inherit;font:inherit;padding:0}.ticker .ti:hover b{text-decoration:underline}
.ticker .big{color:var(--ar-ok,#1a7f37);font-weight:700}.ticker .small{color:var(--ar-ok,#1a7f37)}.ticker .up{color:var(--ar-muted,#888)}
.ticker .deal{color:var(--ar-accent)}.ticker .tktag{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;background:var(--ar-accent);color:var(--ar-on-accent,#fff);font-size:10px;font-weight:800;flex:none}.ticker .fire{letter-spacing:-2px}.ticker .news{font-weight:600}.ticker .news .dot{color:var(--ar-accent)}
.ticker .lbl{flex:none;padding:0 10px;font-weight:700;height:100%;display:flex;align-items:center;background:var(--ar-soft);border-right:1px solid var(--ar-line);z-index:1}
@media(prefers-reduced-motion:reduce){.ticker .tkv{overflow-x:auto}.ticker .tk{padding-left:10px}}
.toasts{position:fixed;right:18px;bottom:40px;display:flex;flex-direction:column;gap:8px;z-index:20}
.toast{background:#23252c;color:#fff;padding:11px 16px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.3);font-size:14px;max-width:380px;animation:toast .35s cubic-bezier(.3,1.3,.5,1);display:flex;gap:8px;align-items:flex-start}
.toast.err{background:#8e0b0c}.toast.ok{background:#0b5d22}.toast.out{animation:toastout .25s forwards}
/* motion */
.enter>*{animation:rise .45s cubic-bezier(.2,.8,.3,1) both}.enter>*:nth-child(2){animation-delay:40ms}.enter>*:nth-child(3){animation-delay:80ms}.enter>*:nth-child(4){animation-delay:120ms}.enter>*:nth-child(n+5){animation-delay:160ms}
.enter .card,.enter .shop{animation:pop .45s cubic-bezier(.3,1.3,.5,1) both;animation-delay:calc(min(var(--i,0),14) * 30ms + 80ms)}
@keyframes rise{from{opacity:0;transform:translateY(10px)}}@keyframes pop{from{opacity:0;transform:scale(.94) translateY(8px)}}@keyframes fade{from{opacity:0}}
@keyframes draw{to{stroke-dashoffset:0}}@keyframes grow{from{transform:scaleY(0)}}@keyframes grow-x{from{transform:scaleX(0)}}@keyframes spin{to{transform:rotate(360deg)}}
@keyframes ring{from{stroke-dashoffset:var(--c)}}@keyframes arc{from{stroke-dasharray:0 999}}@keyframes shimmer{to{background-position:-200% 0}}
@keyframes dlg{from{opacity:0;transform:translateY(16px) scale(.97)}}@keyframes dlgout{to{opacity:0;transform:translateY(10px) scale(.98)}}
@keyframes toast{from{opacity:0;transform:translateY(16px) scale(.95)}}@keyframes toastout{to{opacity:0;transform:translateX(30px)}}
@media(max-width:640px){.wrap{padding:8px 10px 40px}h1{font-size:17px}header{gap:8px}header .lbl{display:none}.logo{width:32px;height:22px}img.logo{width:36px;height:36px}
.seg{gap:2px;padding:4px}.seg button{font-size:13px;padding:9px 4px}.seg small{display:none}
.kpis{grid-template-columns:1fr 1fr;gap:8px}.kpi{padding:10px 12px}.kpi b{font-size:19px}
.grid{grid-template-columns:1fr 1fr;gap:10px}.card .img{height:96px}.card .img img{max-height:88px}.card .p{font-size:17px}.card .ring{width:34px!important;height:34px!important}
.hero .img{height:130px}.hero .p{font-size:28px}.fbar .search{min-width:100%}.panel{padding:12px}}
@media (prefers-reduced-motion: reduce){*,*::before{animation:none!important;transition:none!important}.ln{stroke-dashoffset:0}}
`;

// ------------------------------------------------------------------ component
// labels are English source strings, translated with t() when rendered

const SECTIONS = {
  prices: { label: "🏷️ Prices", hint: "your products and their deals", subs: [["today", "Today"], ["all", "All products"], ["dset", "Deal settings"]] },
  overview: { label: "📊 Overview", hint: "what it all costs", subs: [["cost", "Cost"], ["shops", "Shops"]] },
  log: { label: "📜 Logbook", hint: "checks, prices, errors", subs: [["all", "Everything"], ["checks", "Shop checks"], ["errors", "Open errors"]] },
  manage: { label: "⚙️ Manage", hint: "add, import, shops, settings", subs: [["add", "Add"], ["import", "Import"], ["links", "Link check"], ["notify", "Notifications"], ["shops", "Shops & jobs"], ["lab", "Parser lab"], ["settings", "Settings"], ["userscript", "Userscript"], ["backup", "Backup"], ["legal", "Legal"], ["about", "About ARGUS"]] },
};

class ArgusPanel extends HTMLElement {
  // ---------------------------------------------------------------- derived
  get products() { return (this.state.data && this.state.data.products) || []; }
  /** The name of a product by its id (for texts that only know the id). */
  nameOf(pid) { const p = this.products.find((x) => x.id === pid); return p ? p.name || pid : pid || ""; }
  catName(c) { return ((this.state.data && this.state.data.categories) || {})[c] ? t(this.state.data.categories[c]) : t("Other"); }
  /** "Refresh all prices" is off unless allowed; then at most once a minute (the server checks it too). */
  discountOf(s) { return s.discount_ref != null ? s.discount_ref : s.discount_avg; }
  isDeal(s) {
    const r = (this.state.data && this.state.data.deal_rules) || { min_score: 70, atl: true, target: true };
    const d = this.discountOf(s);
    return s.best_price != null && ((r.atl && s.is_all_time_low) || (r.target && s.target_hit) || s.deal_score >= r.min_score || (d != null && d >= this.state.threshold));
  }
  filtered(list) {
    const { q, category, shop, price, status } = this.state.f;
    let out = list.filter((s) => !category || s.category === category);
    if (shop) out = out.filter((s) => s.best_retailer === shop);
    if (price) { const [lo, hi] = PRICE_BANDS.find(([k]) => k === price).slice(1); out = out.filter((s) => s.best_price != null && s.best_price >= lo && s.best_price < hi); }
    if (status) { const fn = (STATUS_FILTERS.find(([k]) => k === status) || [])[2]; if (fn) out = out.filter((s) => fn(s, this)); }
    if (q) { const n = q.toLowerCase(); out = out.filter((s) => `${s.name} ${s.brand || ""} ${s.ean || ""} ${s.mpn || ""} ${s.notes || ""}`.toLowerCase().includes(n)); }
    return out;
  }
  sorted(list, key) {
    const k = {
      score: (s) => -(s.deal_score || 0) - (s.best_price != null ? 0 : -1000), discount: (s) => -(this.discountOf(s) ?? -1e9), price: (s) => s.best_price ?? 1e9,
      drop: (s) => s.change_7d ?? 1e9, spread: (s) => -(s.shop_spread ?? -1), name: (s) => (s.name || "").toLowerCase(),
      priority: (s) => -(s.priority || 0) * 1000 - (s.deal_score || 0), newest: (s) => -(s.added || 0), deal_new: (s) => -(s.last_deal || 0),
    }[key] || ((s) => 0);
    return [...list].sort((a, b) => { const x = k(a), y = k(b); return x < y ? -1 : x > y ? 1 : 0; });
  }

  // ---------------------------------------------------------------- shared pieces
  /** Extra filters as drop-downs (shop, price, status): only choices that occur in the list, with counts. */
  moreFilters(list) {
    const f = this.state.f, count = (fn) => { const c = {}; list.forEach((s) => [].concat(fn(s)).forEach((k) => { if (k != null && k !== "") c[k] = (c[k] || 0) + 1; })); return c; };
    const sel = (key, label, opts) => opts.length ? `<label class="ff">${label} <select data-ff="${key}"><option value="">${t("all")}</option>${opts.map(([v, l, n]) => `<option value="${esc(v)}" ${f[key] === v ? "selected" : ""}>${esc(l)} (${n})</option>`).join("")}</select></label>` : "";
    const out = [];
    const cs = count((s) => s.best_retailer); out.push(sel("shop", t("Cheapest at"), Object.keys(cs).sort().map((k) => [k, this.state.data.retailers[k] || k, cs[k]])));
    const cp = count((s) => s.best_price == null ? null : (PRICE_BANDS.find(([, lo, hi]) => s.best_price >= lo && s.best_price < hi) || [])[0]);
    out.push(sel("price", t("Price"), PRICE_BANDS.filter(([k]) => cp[k]).map(([k, lo, hi]) => [k, hi === Infinity ? `≥ ${EUR0(lo)}` : `${EUR0(lo)} – ${EUR0(hi)}`, cp[k]])));
    out.push(sel("status", t("Status"), STATUS_FILTERS.map(([k, l, fn]) => [k, t(l), list.filter((s) => fn(s, this)).length]).filter((x) => x[2])));
    const active = ["shop", "price", "status", "category"].filter((k) => f[k]).length + (f.q ? 1 : 0);
    const html = out.filter(Boolean).join("");
    return html || active ? `<div class="fbar fmore">${html}${active ? `<button class="btn ghost sm" data-ffclear>✕ ${t("Clear filters")} (${active})</button>` : ""}</div>` : "";
  }
  filterBar({ sorts, threshold = false, list }) {
    const f = this.state.f;
    const counts = {}; list.forEach((s) => { const c = s.category || "other"; counts[c] = (counts[c] || 0) + 1; });
    const cats = Object.keys(counts).sort();
    return `<div class="fbar"><div class="search"><input id="q" placeholder="${t("Search by name, brand, barcode…")}  ( / )" value="${esc(f.q)}" autocomplete="off"></div>
      <select id="sort" aria-label="${t("Sort")}">${sorts.map(([k, l]) => `<option value="${k}" ${f.sort === k ? "selected" : ""}>${t(l)}</option>`).join("")}</select>
      ${threshold ? `<label class="thr">${t("Discount")} ≥ <b id="thrv">${this.state.threshold}%</b><input id="thr" type="range" min="5" max="70" step="5" value="${this.state.threshold}"></label>` : ""}</div>
      ${cats.length > 1 ? `<div class="chips"><span class="chip ${!f.category ? "on" : ""}" data-cat="">${t("All categories")}</span>${cats.map((c) => `<span class="chip ${f.category === c ? "on" : ""}" data-cat="${esc(c)}">${CATEGORY_ICONS[c] || "📦"} ${esc(this.catName(c))} <span class="muted">${counts[c]}</span></span>`).join("")}</div>` : ""}
      ${this.moreFilters(list)}`;
  }
  img(s, big = false) { return s.image ? `<img loading="lazy" decoding="async" src="${esc(thumb(s.image, big ? 640 : 320))}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'${CATEGORY_ICONS[s.category] || "📦"}'}))">` : `<span class="ph"${big ? ' style="font-size:60px"' : ""}>${CATEGORY_ICONS[s.category] || "📦"}</span>`; }
  badges(s) {
    const d = this.discountOf(s);
    return [
      s.is_all_time_low ? `<span class="badge">🔻 ${t("Lowest so far")}</span>` : "",
      d != null && d >= this.state.threshold && s.best_price != null ? `<span class="badge red">−${Math.round(d)}%</span>` : "",
      s.target_hit ? `<span class="badge purple">🎯 ${t("Target price")}</span>` : "",
      s.offers_live > 1 && s.shop_spread >= 5 ? `<span class="badge blue" title="${esc(t("The cheapest shop is {pct}% below the dearest one", { pct: Math.round(s.shop_spread) }))}">⇅ ${Math.round(s.shop_spread)}%</span>` : "",
    ].join("");
  }
  /** Go to Manage → Add. */
  goAdd(prefill = null) {
    const s = this.state;
    s.section = "manage"; s.sub.manage = "add"; s.addPrefill = prefill;
    this.closeDialog(true); this.resetFilters(); this.persist(); this.render(true);
    try { this.scrollIntoView({ block: "start" }); } catch (e) { /* ignore */ }
  }
  card(s, i = 0) {
    const store = s.best_retailer ? this.state.data.retailers[s.best_retailer] : "";
    const trd = s.change_7d == null || s.change_7d === 0 ? "" : `<span class="trend ${s.change_7d <= 0 ? "up" : "down"}">${s.change_7d <= 0 ? "▼" : "▲"} ${Math.abs(s.change_7d)}%</span>`;
    const stars = s.priority ? `<span class="stars">${"★".repeat(s.priority)}</span>` : "";
    const nShops = Object.keys(s.offers || {}).length;
    const status = store ? t("at {shop}", { shop: esc(store) }) + viaBadge(((s.offers || {})[s.best_retailer] || {}).via) + (s.offers_live > 1 ? ` · ${t("{n} shops", { n: s.offers_live })}` : "")
      : s.offers_live === 0 && nShops ? "⚠ " + t("no price found") : nShops ? t("no price") : (this.state.data.first_checks || []).includes(s.id) ? "⏳ " + t("looking for shops…") : t("no shop links yet");
    return `<div class="card" tabindex="0" data-set="${esc(s.id)}" style="--i:${i}"><div class="badges">${this.badges(s)}</div>${s.best_price != null ? ring(s.deal_score, 40) : ""}
      <div class="img">${this.img(s)}</div><div class="n">${esc(s.name || s.id)}</div>
      <div class="m">${[s.brand, this.catName(s.category)].filter(Boolean).map(esc).join(" · ")} ${stars}</div>
      <div class="row"><span class="p">${EUR(s.best_price)}</span>${s.ref_price && s.best_price != null && s.best_price < s.ref_price ? `<s>${EUR(s.ref_price)}</s>` : ""}${trd}</div>
      ${s.offers_suspect ? `<div class="m" style="color:var(--ar-red)">⚠ ${t(s.offers_suspect > 1 ? "{n} suspicious links" : "{n} suspicious link", { n: s.offers_suspect })}</div>` : ""}
      <div class="m">${status}${s.target_price ? ` · 🎯 ${EUR0(s.target_price)}` : ""}</div>
      ${spark(s.spark)}</div>`;
  }
  /** The first "card" of a grid: a big + that opens Manage → Add. */
  addTile() {
    return `<div class="card addtile" data-addtile="1" role="button" tabindex="0" title="${esc(t("Add a product"))}"><span class="plus">＋</span><b>${t("Add a product")}</b></div>`;
  }
  gridOf(list, addTile = false) {
    // page by page: hundreds of cards (images, animations) at once make the iPhone app run out of memory
    const max = this.state.gridMax || GRID_PAGE, shown = list.slice(0, max);
    const more = list.length > max ? `<div style="text-align:center;margin:14px 0"><button class="btn ghost" data-gridmore="1">${t("Show {n} more ({total} left)", { n: Math.min(GRID_PAGE, list.length - max), total: list.length - max })}</button></div>` : "";
    return `<div class="grid">${addTile ? this.addTile() : ""}${shown.map((s, i) => this.card(s, i)).join("")}</div>${more}`;
  }

  // ---------------------------------------------------------------- PRICES
  vToday() {
    const all = this.products, list = this.filtered(all);
    if (!all.length) return this.emptyState("👁", t("No products yet. Paste the address of a product page: ARGUS reads it and looks the same product up at the other shops."), `<button class="btn" data-goto="manage/add">＋ ${t("Add a product")}</button> <button class="btn ghost" data-goto="manage/import">⇪ ${t("Import products")}</button>`);
    const deals = this.sorted(list.filter((s) => this.isDeal(s)), this.state.f.sort || "score");
    const top = deals[0];
    const lows = list.filter((s) => s.is_all_time_low).length, targets = list.filter((s) => s.target_hit).length, dropped = list.filter((s) => (s.change_7d ?? 0) <= -3);
    const sum = this.state.data.summary;
    const kpis = `<div class="kpis">${this.kpi(t("Deals now"), deals.length, { icon: "🏷️", color: "var(--ar-red)", sub: t("of {n} products", { n: list.length }) })}${this.kpi(t("Lowest price so far"), lows, { icon: "🔻", color: "var(--ar-green)" })}${this.kpi(t("Target price reached"), targets, { icon: "🎯", color: "var(--ar-purple)" })}${this.kpi(t("Price dropped this week"), dropped.length, { icon: "📉", color: "var(--ar-yellow)" })}${this.kpi(t("Everything now"), sum.cost, { fmt: "eur", icon: "🛒", sub: sum.saving > 0 ? `<span class="up">${t("{amount} below the usual prices", { amount: EUR0(sum.saving) })}</span>` : t("{n} with a price", { n: sum.priced }) })}</div>`;
    const hero = top ? `<div class="hero" data-set="${esc(top.id)}"><div class="img">${this.img(top, true)}</div><div><div class="k">⭐ ${t("Deal of the day")}</div><h2>${esc(top.name || top.id)}</h2><div class="m muted">${[top.brand, this.catName(top.category)].filter(Boolean).map(esc).join(" · ")}</div>
      <div style="display:flex;align-items:baseline;gap:10px;margin:8px 0"><span class="p">${EUR(top.best_price)}</span>${top.ref_price && top.ref_price > top.best_price ? `<s class="muted">${EUR(top.ref_price)}</s>` : ""}${this.discountOf(top) > 0 ? `<span class="badge red">−${Math.round(this.discountOf(top))}%</span>` : ""}</div>
      <div class="muted" style="font-size:13px">${t("at {shop}", { shop: esc(this.state.data.retailers[top.best_retailer] || "") })}${top.is_all_time_low ? " · " + t("lowest price so far") : ""}${top.target_hit ? " · " + t("below your target price") : ""}${top.offers_live > 1 ? " · " + t("{n} shops compared", { n: top.offers_live }) : ""}</div>
      ${top.best_url ? `<a class="btn sm" style="margin-top:12px" href="${esc(top.best_url)}" target="_blank" rel="noopener noreferrer" data-stop>${t("Go to the shop")} ↗</a>` : ""}</div>${ring(top.deal_score, 64)}</div>` : "";
    const drops = this.sorted(dropped.filter((s) => !this.isDeal(s)), "drop").slice(0, 8);
    const main = `${hero}<h2 class="sec">🏷️ ${t("All deals")} <span class="n">${deals.length}</span></h2>${this.gridOf(deals.slice(1), true)}
      ${!deals.length ? this.emptyState("😴", t("No deals today among your {n} products. Tip: lower the discount threshold or set target prices.", { n: list.length })) : ""}
      ${drops.length ? `<h2 class="sec">📉 ${t("Big price drops")} <span class="n">${t("last 7 days")}</span></h2>${this.gridOf(drops)}` : ""}`;
    if (this._todayResults) return `<div class="cols"><div>${main}</div><aside>${this.timeline()}</aside></div>`;
    const bar = this.filterBar({ list: all, sorts: [["score", "Deal score"], ["discount", "Highest discount"], ["price", "Lowest price"], ["drop", "Biggest drop"], ["spread", "Biggest difference between shops"], ["deal_new", "Latest deal notification"]] });
    return `${this.banner()}${kpis}${bar}<div id="results" data-fn="rToday"><div class="cols"><div>${main}</div><aside>${this.timeline()}</aside></div></div>`;
  }
  /** Prices → Today without the filters above (typing in the search box keeps its focus). */
  rToday() {
    this._todayResults = true;
    try { return this.vToday(); } finally { this._todayResults = false; }
  }
  timeline() {
    const ev = this.state.data.events || [], byId = Object.fromEntries(this.products.map((x) => [x.id, x]));
    const ic = { is_all_time_low: ["🔻", "lowest price so far"], high_discount: ["🏷️", "good discount"], target_hit: ["🎯", "target price reached"] };
    const row = (e) => {
      const [i, lbl] = ic[e.kind] || ["•", e.kind], s = byId[e.product] || { id: e.product, name: e.name };
      const price = e.price != null ? e.price : s.best_price, shop = e.retailer || s.best_retailer;
      const url = e.url || (shop && s.offers && s.offers[shop] && s.offers[shop].url) || s.best_url;
      const shopName = shop ? esc(this.state.data.retailers[shop] || shop) : "";
      const now = s.best_price != null && price != null && Math.abs(s.best_price - price) >= 0.01 ? ` <span class="t">(${t("now {price}", { price: EUR(s.best_price) })})</span>` : "";
      const disc = e.discount != null ? e.discount : null;
      const score = e.score != null ? e.score : s.deal_score;
      const tags = `${disc != null && disc > 0 ? `<span class="badge red">−${Math.round(disc)}%</span>` : ""}${score != null ? `<span class="badge grey" title="${esc(t("Deal score"))}">⭐ ${Math.round(score)}</span>` : ""}`;
      return `<li class="tlr" data-set="${esc(e.product)}"><div class="tthumb img">${this.img(s)}</div><div class="tbody"><b><span class="ic">${i}</span> ${esc(s.name || e.name || e.product)}</b>
        <div style="display:flex;gap:4px;flex-wrap:wrap;margin:2px 0">${tags}</div><div>${esc(t(lbl))} · <b>${EUR(price)}</b>${now}${shopName ? ` · ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-stop>${shopName} ↗</a>` : shopName}` : ""}</div>
        <div class="t">${DATE(e.ts, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</div></div></li>`;
    };
    return `<div class="panel"><h3>🕒 ${t("Recent deals")}</h3>${ev.length ? `<ul class="tl tlx">${ev.slice(0, 12).map(row).join("")}</ul>` : `<p>${t("Nothing reported yet. New lowest prices, good discounts and reached target prices appear here.")}</p>`}</div>`;
  }
  vAll() {
    if (!this.products.length) return this.vToday();
    return `${this.banner()}${this.filterBar({ list: this.products, threshold: true, sorts: [["score", "Deal score"], ["priority", "Priority"], ["discount", "Highest discount"], ["price", "Lowest price"], ["drop", "Biggest drop"], ["spread", "Biggest difference between shops"], ["newest", "Newest first"], ["name", "Name"]] })}<div id="results" data-fn="rAll">${this.rAll()}</div>`;
  }
  rAll() { const l = this.sorted(this.filtered(this.products), this.state.f.sort); return l.length ? this.gridOf(l, true) : `<div class="grid">${this.addTile()}</div>` + this.emptyState("🔍", t("Nothing found with these filters.")); }
  /** Prices → Deal settings: when does a price count as a deal? */
  vDealSettings() {
    const st = this.state.settings;
    if (!st) { this.loadSettings().then(() => { if (this.state.section === "prices" && this.state.sub.prices === "dset") this.renderContent(); }); return `<div class="skel" style="height:240px"></div>`; }
    return `<div class="panel"><h3>🎚️ ${t("When is it a deal?")}</h3>
      <p>${t("A price counts as a deal when one of these is true. Deals show under Today, in the ticker and in your notifications.")}</p>
      <div class="form"><label>${t("Deal score at least")} <b id="df_scorev">${st.deal_min_score}</b><input id="df_score" type="range" min="10" max="100" step="5" value="${st.deal_min_score}"></label>
        <label>${t("Discount at least")} <b id="df_thrv">${st.discount_threshold}%</b><input id="df_thr" type="range" min="5" max="70" step="5" value="${st.discount_threshold}"></label></div>
      <label class="chk" style="display:flex;gap:8px;margin:8px 0"><input type="checkbox" id="df_atl" ${st.deal_atl ? "checked" : ""}> ${t("The lowest price so far counts as a deal")}</label>
      <label class="chk" style="display:flex;gap:8px;margin:8px 0"><input type="checkbox" id="df_target" ${st.deal_target ? "checked" : ""}> ${t("A price at or below your target price counts as a deal")}</label>
      <p class="muted" style="font-size:13px">${t("The deal score (0–100) weighs the discount against your reference price and against the usual price of the last 90 days, the distance to the lowest price so far, how much cheaper the best shop is than the dearest one, and a reached target price.")}</p>
      <button class="btn" id="df_save">💾 ${t("Save")}</button></div>`;
  }
  bindDealSettings(root, $) {
    const link = (a, b, suf) => { const el = $(a); if (el) el.addEventListener("input", (e) => { $(b).textContent = e.target.value + suf; }); };
    link("df_score", "df_scorev", ""); link("df_thr", "df_thrv", "%");
    $("df_save").onclick = () => this.busy($("df_save"), t("Saving…"), async () => {
      await this._hass.callWS({ type: "argus/settings/set", fields: { deal_min_score: +$("df_score").value, discount_threshold: +$("df_thr").value, deal_atl: $("df_atl").checked, deal_target: $("df_target").checked } });
      this.state.settings = null; this.state.threshold = null; await new Promise((r) => setTimeout(r, 1500)); await this.load(); this.toast(t("Saved"), "ok");
    });
  }

  // ---------------------------------------------------------------- OVERVIEW
  vCost() {
    const sum = this.state.data.summary, c = this.state.coll || { series: [] };
    if (!this.products.length) return this.emptyState("📊", t("The overview appears as soon as you track products."), `<button class="btn" data-goto="manage/add">＋ ${t("Add a product")}</button>`);
    const days = this.state.range, cut = days ? Date.now() / 1000 - days * 86400 : 0;
    const pts = (c.series || []).filter((p) => p.t >= cut).map((p) => [p.t, p.cost]);
    const cats = Object.entries(sum.by_category || {}).filter(([, v]) => v.cost > 0 || v.products).sort((a, b) => b[1].cost - a[1].cost);
    const top = this.sorted(this.products.filter((s) => s.shop_spread != null), "spread").slice(0, 8);
    return `<div class="kpis">${this.kpi(t("Products"), sum.products, { icon: "👁", sub: t("{n} with a price", { n: sum.priced }) })}${this.kpi(t("Everything now"), sum.cost, { fmt: "eur", icon: "🛒", sub: t("at the cheapest shops") })}${this.kpi(t("Usual prices"), sum.ref, { fmt: "eur", icon: "🏷️", sub: t("your reference price, else today's") })}${this.kpi(t("Saving"), sum.saving, { fmt: "eur", icon: "💰", color: "var(--ar-green)" })}</div>
      <div class="panel"><h3>📈 ${t("What it all costs over time")}</h3><div class="chips">${[[30, t("{n} d", { n: 30 })], [90, t("{n} d", { n: 90 })], [365, t("1 year")], [0, t("All")]].map(([d, l]) => `<span class="chip sm ${this.state.range === d ? "on" : ""}" data-range="${d}">${l}</span>`).join("")}</div>
        ${lineChart([{ name: t("Everything at the cheapest shops"), color: COLORS[0], points: pts }], { area: true })}</div>
      <div class="two"><div class="panel"><h3>🗂 ${t("Per category")}</h3>${donut(cats.map(([c2, v], i) => ({ label: `${CATEGORY_ICONS[c2] || "📦"} ${this.catName(c2)}`, value: v.cost, color: COLORS[i % COLORS.length] })), { label: t("now") })}
          <table class="tbl" style="margin-top:8px"><tr><th>${t("Category")}</th><th class="num">${t("Products")}</th><th class="num">${t("Cost now")}</th></tr>${cats.map(([c2, v]) => `<tr><td>${CATEGORY_ICONS[c2] || "📦"} ${esc(this.catName(c2))}</td><td class="num">${v.products}</td><td class="num">${EUR(v.cost)}</td></tr>`).join("")}</table></div>
        <div class="panel"><h3>⇅ ${t("Biggest difference between shops")}</h3>${top.length ? `<table class="tbl"><tr><th>${t("Product")}</th><th class="num">${t("Cheapest")}</th><th class="num">${t("Dearest")}</th></tr>${top.map((s) => `<tr class="click" data-set="${esc(s.id)}"><td>${esc((s.name || s.id).slice(0, 44))}<div class="muted" style="font-size:12px">${esc(this.state.data.retailers[s.best_retailer] || "")} · −${Math.round(s.shop_spread)}%</div></td><td class="num"><b>${EUR(s.best_price)}</b></td><td class="num">${EUR(s.highest_price)}</td></tr>`).join("")}</table>` : `<p>${t("Products found at two or more shops show their price difference here.")}</p>`}</div></div>`;
  }
  vShopsOverview() {
    const st = this.state.data.retailer_stats || {}, rows = Object.entries(st).filter(([, r]) => r.offers).sort((a, b) => b[1].cheapest - a[1].cheapest);
    if (!this.products.length) return this.emptyState("🏪", t("The overview appears as soon as you track products."), `<button class="btn" data-goto="manage/add">＋ ${t("Add a product")}</button>`);
    return `<div class="panel"><h3>🏪 ${t("Which shop is the cheapest most often?")}</h3>${rows.length ? bars(rows.map(([k, r]) => ({ label: r.label, value: r.cheapest })), { fmt: INT }) : `<p>${t("No prices yet.")}</p>`}</div>
      <div class="panel tscroll"><table class="tbl"><tr><th>${t("Shop")}</th><th class="num">${t("Products")}</th><th class="num">${t("Cheapest")}</th><th class="num">${t("Errors")}</th><th>${t("Last price")}</th></tr>
      ${rows.map(([k, r]) => `<tr class="click shop" data-shop="${esc(k)}"><td><b>${esc(r.label)}</b>${r.paused_hours > 0 ? ` <span class="lk suspect">⏸</span>` : ""}</td><td class="num">${r.ok}/${r.offers}</td><td class="num">${r.cheapest}</td><td class="num ${r.errors ? "err" : ""}">${r.errors || "–"}</td><td>${r.last_ok ? ago(r.last_ok) : "–"}</td></tr>`).join("")}</table></div>`;
  }

  // ---------------------------------------------------------------- MANAGE → add / import
  vAdd() {
    const pre = this.state.addPrefill || {}, d = this.state.data, cats = d.categories, shops = Object.entries(d.retailers);
    const byCat = {}; for (const [rid, label] of shops) { const cs = (d.shop_categories || {})[rid] || []; for (const c of (cs.length ? cs : Object.keys(cats))) (byCat[c] = byCat[c] || []).push(label); }
    return `<div class="panel"><h3>＋ ${t("Add a product")}</h3>
      <p>${t("Paste the address of a product page at one of your shops (e.g. bol, Amazon, Fnac). ARGUS reads the name, barcode and price from that page and then looks the same product up at the other shops of its category.")}</p>
      <div class="form"><label style="grid-column:1/-1">${t("Address of the product page")}<input id="a_url" type="url" inputmode="url" autocomplete="off" placeholder="https://www.example-shop.be/p/…" value="${esc(pre.url || "")}" style="width:100%"></label></div>
      <details style="margin:8px 0" ${pre.name || pre.ean ? "open" : ""}><summary>${t("No address, or you want to fill things in yourself?")}</summary>
        <p class="muted" style="font-size:13px">${t("Without an address a name is enough (a barcode makes the search much surer). What you fill in here wins over what the page says.")}</p>
        <div class="form"><label style="grid-column:span 2">${t("Name")}<input id="a_name" value="${esc(pre.name || "")}" placeholder="${t("e.g. {example}", { example: "Sony WH-1000XM5" })}"></label>
          <label>${t("Barcode (EAN / ISBN)")}<input id="a_ean" inputmode="numeric" autocomplete="off" value="${esc(pre.ean || "")}"></label>
          <label>${t("Brand")}<input id="a_brand"></label><label>${t("Model number")}<input id="a_mpn"></label>
          <label>${t("Category")}<select id="a_cat"><option value="">${t("automatic")}</option>${Object.entries(cats).map(([k, v]) => `<option value="${esc(k)}">${CATEGORY_ICONS[k] || ""} ${esc(t(v))}</option>`).join("")}</select></label></div></details>
      <div class="form"><label>${t("Target price")} (€)<input id="a_target" type="text" inputmode="decimal" autocomplete="off" data-money placeholder="${t("optional: you get a message below it")}"></label>
        <label>${t("Reference price")} (€)<input id="a_ref" type="text" inputmode="decimal" autocomplete="off" data-money placeholder="${t("optional: the usual price")}"></label>
        <label>${t("Priority")}<select id="a_prio">${[0, 1, 2, 3].map((p) => `<option value="${p}">${p ? "★".repeat(p) : "–"}</option>`).join("")}</select></label></div>
      <button class="btn" id="a_go">＋ ${t("Add & find at other shops")}</button> <span id="a_hint" class="muted" style="font-size:13px"></span>
      <div id="a_result"></div></div>
      <div class="panel"><h3>🏪 ${t("Where does ARGUS look?")}</h3><p>${t("A product is only looked up at the shops that sell its category. The shops come from your shop settings (Manage → Shops & jobs).")}</p>
        <table class="tbl">${Object.entries(cats).map(([k, v]) => `<tr><td style="white-space:nowrap">${CATEGORY_ICONS[k] || ""} <b>${esc(t(v))}</b></td><td>${(byCat[k] || []).length ? (byCat[k] || []).map(esc).join(", ") : `<span class="muted">${t("no shops yet")}</span>`}</td></tr>`).join("")}</table></div>`;
  }
  vImport() {
    const imp = this.state.imp, a = imp.analysis;
    if (a) {
      const map = Object.entries(a.mapping).map(([k, i]) => `${esc(t(k))} ← <b>${esc(a.columns[i] || "")}</b>`).join(" · ");
      return `<div class="panel"><h3>⇪ ${t("Import products")}</h3><p>${t("{n} products found in the file.", { n: a.count })}${a.truncated ? " " + t("(only the first 500 are imported)") : ""}</p>
        <p class="muted" style="font-size:13px">${map}</p>
        <div class="tscroll"><table class="tbl"><tr><th>${t("Name")}</th><th>${t("Address")}</th><th>${t("Category")}</th><th>${t("Barcode")}</th><th class="num">${t("Target price")}</th></tr>${a.sample.map((r) => `<tr><td>${esc(r.name || "")}</td><td>${esc((r.url || "").replace(/^https?:\/\/(www\.)?/, "").slice(0, 50))}</td><td>${esc(r.category || "")}</td><td>${esc(r.ean || "")}</td><td class="num">${r.target_price != null ? EUR(r.target_price) : ""}</td></tr>`).join("")}</table></div>
        <label class="chk" style="display:flex;gap:8px;margin:10px 0"><input type="checkbox" id="imp_discover" ${imp.discover ? "checked" : ""}> ${t("Look every new product up at the other shops")}</label>
        <button class="btn" id="impgo">⇪ ${t("Import {n} products", { n: a.count })}</button> <button class="btn ghost" id="impback">${t("Back")}</button></div>`;
    }
    return `<div class="panel"><h3>⇪ ${t("Import products")}</h3>
      <p>${t("A spreadsheet (CSV) with a column for the address of the product page and/or the name. Other columns ARGUS understands: category, barcode (EAN/ISBN), brand, model, reference price, target price, priority and notes. The first row holds the column names.")}</p>
      <div class="drop" id="drop"><input type="file" id="csvfile" accept=".csv,text/csv,.txt" hidden><label for="csvfile" class="btn ghost">${t("Choose a file…")}</label> <span class="muted">${t("or drop it here")}</span></div>
      <p class="muted" style="margin:10px 0 4px">${t("or paste the CSV text")}</p>
      <textarea id="csvtext" rows="6" style="width:100%;box-sizing:border-box;font-family:monospace">${esc(imp.text)}</textarea>
      <div style="margin-top:8px"><button class="btn" id="analyze">${t("Check")}</button> <button class="btn ghost" id="expcsv2">⬇ ${t("Export my products as CSV")}</button></div></div>`;
  }
  /** After adding: what ARGUS read from the page and what happens next. */
  addedHtml(r) {
    const p = r.product || {};
    return `<div class="prefill item" style="margin-top:12px;display:flex;gap:12px;align-items:center"><div class="img" style="width:72px;height:72px;display:grid;place-items:center">${this.img(p)}</div>
      <div style="flex:1"><div class="muted" style="font-size:12px">${r.existing ? t("Already tracked: this shop was added to it") : t("Added: ARGUS is looking it up at the other shops")}</div>
        <b>${esc(p.name || "")}</b><div class="muted" style="font-size:13px">${[p.brand, this.catName(p.category), p.ean ? t("barcode {ean}", { ean: p.ean }) : t("no barcode on the page: matched by title")].filter(Boolean).map(esc).join(" · ")}${r.price != null ? ` · <b>${EUR(r.price)}</b>` : ""}</div>
        ${r.error ? `<div class="err" style="font-size:12px">⚠ ${esc(tx(r.error))}</div>` : ""}</div><button class="btn sm" data-set="${esc(r.id)}">${t("Open product")}</button></div>`;
  }

  // ---------------------------------------------------------------- the product window
  async openSet(num, focusShop = null) {
    const gen = (this._dlgGen = (this._dlgGen || 0) + 1);
    this._dlgNum = num;
    clearInterval(this._shopTimer);
    const dlg = this.shadowRoot.getElementById("dlg");
    if (!dlg.open) { dlg.innerHTML = `<div class="dbody"><div class="skel" style="height:110px;margin-bottom:12px"></div><div class="skel" style="height:240px"></div></div>`; dlg.showModal(); }
    let s; try { s = await this._hass.callWS({ type: "argus/product", product: num }); } catch (e) { if (gen !== this._dlgGen) return; dlg.innerHTML = `<div class="dbody"><div class="empty">${esc(tx(e.message))}</div><br><button class="btn" id="x2">${t("Close")}</button></div>`; dlg.querySelector("#x2").onclick = () => this.closeDialog(); return; }
    if (gen !== this._dlgGen) return;
    const scroll = dlg.scrollTop;
    const days = this.state.range, cut = days ? Date.now() / 1000 - days * 86400 : 0;
    const win = (h) => { if (!cut) return h; const keep = h.filter((p) => p[0] >= cut), prev = lastAt(h, cut); return prev && (!keep.length || keep[0][0] > cut) ? [[cut, prev[1]], ...keep] : keep; };
    const series = Object.entries(s.history).filter(([, h]) => h.length).map(([rid, h], i) => ({ name: s.offers[rid]?.label || rid, color: COLORS[i % COLORS.length], points: win(h) })).filter((x) => x.points.length);
    const allT = series.flatMap((x) => x.points.map((p) => p[0]));
    if (s.ref_price && allT.length) series.push({ name: t("reference price"), color: "#9aa0a6", dashed: true, points: [[Math.min(...allT), s.ref_price], [Math.max(...allT), s.ref_price]] });
    if (s.target_price && allT.length) series.push({ name: t("Target price"), color: "#7a3c9e", dashed: true, points: [[Math.min(...allT), s.target_price], [Math.max(...allT), s.target_price]] });
    const retailers = this.state.data.retailers, cats = this.state.data.categories;
    const stat = (l, v) => `<div class="stat"><small>${l}</small><b>${v}</b></div>`;
    const d = this.discountOf(s);
    dlg.innerHTML = `<div class="dhead"><div class="img">${this.img(s, true)}</div><div><h2>${esc(s.name || s.id)}</h2><div class="muted">${[s.brand, this.catName(s.category), s.ean ? t("barcode {ean}", { ean: s.ean }) : "", s.mpn].filter(Boolean).map(esc).join(" · ")}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">${this.badges(s)}</div>
        <div style="margin-top:8px;display:flex;align-items:baseline;gap:6px 10px;flex-wrap:wrap"><span style="font-size:26px;font-weight:800">${EUR(s.best_price)}</span>${s.best_retailer ? `<span class="muted">${t("at {shop}", { shop: esc(retailers[s.best_retailer]) })}</span>` : ""}${s.best_url ? `<a class="btn sm" href="${esc(s.best_url)}" target="_blank" rel="noopener noreferrer">${t("Buy")} ↗</a>` : ""}</div></div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:10px"><button class="x" id="x" aria-label="${t("Close")}">✕</button>${s.best_price != null ? ring(s.deal_score, 56) : ""}</div></div>
      <div class="dbody"><div class="chips">${[[30, t("{n} d", { n: 30 })], [90, t("{n} d", { n: 90 })], [365, t("1 year")], [0, t("All")]].map(([dd, l]) => `<span class="chip sm ${this.state.range === dd ? "on" : ""}" data-range="${dd}">${l}</span>`).join("")}</div>
        ${lineChart(series, { area: true })}
        <div class="stats">${stat(t("Lowest so far"), EUR(s.all_time_low))}${stat(t("reference price"), EUR(s.ref_price))}${stat(t("Discount"), d != null ? `${d > 0 ? "−" : "+"}${Math.abs(d)}%` : "–")}${stat(t("Between shops"), s.shop_spread != null ? `${Math.round(s.shop_spread)}%` : "–")}${stat(t("7 days"), signPct(s.change_7d))}${stat(t("30 days"), signPct(s.change_30d))}${stat(t("Shops with a price"), `${s.offers_live || 0}/${(s.shops_for || []).length}`)}${stat(t("Last check"), ago(s.checked))}</div>
        <h3 style="margin:16px 0 4px;display:flex;align-items:center;gap:8px">🏪 ${t("Shops: links & prices")}<span class="hsp" style="flex:1"></span><button class="btn ghost sm" id="rp" type="button" title="${esc(t("Collects the links, prices, errors and recent log of this product, with your remark, for the logbook or a CSV file"))}">⚠ ${t("Problem with this product")}</button><button class="btn ghost sm" id="lg" type="button">📜 ${t("Logbook")}</button></h3>
        <div id="rpbox" hidden></div>
        <p class="muted" style="font-size:12px;margin:0 0 6px">${t("Edit a link or price and press Save. What you enter by hand always wins and is never overwritten; empty a field to hand it back to the automatic search / price.")}</p>
        ${this.shopTableHtml(s, focusShop)}
        <form id="ef" style="margin-top:16px" autocomplete="off">
        <fieldset><legend>🎯 ${t("Tracking")}</legend><div class="form"><label>${t("Target price")} (€)<input name="target_price" type="text" inputmode="decimal" autocomplete="off" data-money value="${s.target_price ?? ""}"></label>
          <label>${t("Reference price")} (€)<input name="ref_price" type="text" inputmode="decimal" autocomplete="off" data-money value="${s.ref_price ?? ""}" placeholder="${t("the usual price")}"></label>
          <label>${t("Priority")}<select name="priority">${[0, 1, 2, 3].map((p) => `<option value="${p}" ${(s.priority || 0) === p ? "selected" : ""}>${p ? "★".repeat(p) : "–"}</option>`).join("")}</select></label></div>
          <div class="form"><label style="grid-column:1/-1">${t("Notes")}<input name="notes" value="${esc(s.notes || "")}" maxlength="500"></label></div></fieldset>
        <fieldset><legend>👁 ${t("Product details")}</legend><p class="muted" style="font-size:12px;margin:0 0 8px">${t("Read from the page you added the product with. The barcode is what ARGUS uses to be sure that a page at another shop is the same product; empty it to let ARGUS learn it again.")}</p>
          <div class="form"><label style="grid-column:span 2">${t("Name")}<input name="name" value="${esc(s.name || "")}"></label><label>${t("Category")}<select name="category">${Object.entries(cats).map(([k, v]) => `<option value="${esc(k)}" ${s.category === k ? "selected" : ""}>${CATEGORY_ICONS[k] || ""} ${esc(t(v))}</option>`).join("")}</select></label>
          <label>${t("Brand")}<input name="brand" value="${esc(s.brand || "")}"></label><label>${t("Barcode (EAN / ISBN)")}<input name="ean" inputmode="numeric" autocomplete="off" value="${esc(s.ean || "")}"></label><label>${t("Model number")}<input name="mpn" value="${esc(s.mpn || "")}"></label>
          <label style="grid-column:span 2">${t("Image (https URL)")}<input name="image" value="${esc(s.image || "")}" placeholder="https://…"></label></div></fieldset>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="save" type="submit">${t("Save")}</button><button class="btn ghost" id="find" type="button" ${this.mAttr("find")}>🔎 ${t("Find at other shops")}</button><button class="btn ghost" id="rf" type="button" ${this.mAttr("prices")}>↻ ${t("Fetch prices")}</button><span class="hsp" style="flex:1"></span><button class="btn danger" id="rm" type="button">${t("Delete")}</button></div></form></div>`;
    const q = (id) => dlg.querySelector("#" + id);
    dlg.scrollTop = scroll;
    q("x").onclick = () => this.closeDialog();
    q("lg").onclick = () => this.showLogFor(num);
    q("rp").onclick = () => this.reportForm(q("rpbox"), s);
    dlg.querySelectorAll("[data-goto]").forEach((el) => { el.onclick = () => { const [a, b] = el.dataset.goto.split("/"); this.state.section = a; this.state.sub[a] = b; this.closeDialog(true); this.persist(); this.render(true); }; });
    dlg.querySelectorAll("[data-range]").forEach((ch) => ch.onclick = () => { this.state.range = +ch.dataset.range; this.persist(); this.openSet(num); });
    // ---- shop table: manual links and prices, per-shop fetch
    const shop = this.bindShopTable(dlg, s, () => this.openSet(num));
    const changes = shop.changes;
    if (focusShop) { const i = dlg.querySelector(`tr.orow[data-rid="${focusShop}"] .ou`); if (i) { i.focus(); i.select(); } }
    // ---- details form: only changed fields are sent
    const ef = q("ef");
    const snapshot = () => { const fd = new FormData(ef), o = {}; for (const [k, v] of fd.entries()) o[k] = ef.querySelector(`[name="${k}"][data-money]`) ? money(v) : v.toString().trim(); return o; };
    const orig = snapshot();
    ef.addEventListener("submit", (e) => {
      e.preventDefault();
      const now = snapshot(), f = {};
      for (const k of Object.keys(now)) if (now[k] !== orig[k]) f[k] = k === "priority" ? +now[k] : now[k];
      if (!Object.keys(f).length && !changes().length) { this.closeDialog(); return; }
      if (f.ref_price && s.best_price && (+f.ref_price > s.best_price * 20 || +f.ref_price < s.best_price / 20) && !confirm(t("{price} is very different from the current price {rrp}. Save anyway?", { price: EUR(+f.ref_price), rrp: EUR(s.best_price) }))) return;
      if (changes().length && !confirm(t("You also changed shop links or prices. Save those too?"))) return;
      this.busy(q("save"), t("Saving…"), async () => {
        const list = changes(); if (list.length) { if (!shop.check(list)) return; await shop.send(list); }
        if (Object.keys(f).length) await this._hass.callWS({ type: "argus/update_product", product: num, fields: f });
        await this.load(); this.toast(t("Saved"), "ok"); this.closeDialog();
      });
    });
    q("find").onclick = (e) => this.busy(e.currentTarget, t("Searching…"), async () => { const r = await this._hass.callWS({ type: "argus/product/find", product: num }); await this.load(); this.toast(r.result.found ? t("{n} shop links found", { n: r.result.found }) : t("No new shop found"), r.result.found ? "ok" : ""); this.openSet(num); });
    q("rf").onclick = (e) => this.busy(e.currentTarget, t("Fetching…"), async () => { await this._hass.callWS({ type: "argus/product/refresh", product: num }); await this.load(); this.openSet(num); });
    q("rm").onclick = () => { if (!confirm(t("Delete {name} with its whole price history?", { name: s.name || num }))) return; this.busy(q("rm"), "", async () => { await this._hass.callWS({ type: "argus/remove_product", product: num }); this.closeDialog(); await this.load(); this.toast(t("Product deleted"), "ok"); }); };
    this.hookCharts(dlg); this.tickManual();
  }
  // ---------------------------------------------------------------- bindings of the content area
  bindContent(root) {
    const s = this.state, $ = (id) => root.querySelector("#" + id), on = (sel, ev, fn) => root.querySelectorAll(sel).forEach((e) => e.addEventListener(ev, fn));
    this.bindCards(root);
    this.shadowRoot.querySelectorAll("[data-gridmore]").forEach((el) => { el.onclick = () => { const y = window.scrollY; s.gridMax = (s.gridMax || GRID_PAGE) + GRID_PAGE; this.render(false); window.scrollTo(0, y); }; });
    this.shadowRoot.querySelectorAll("[data-goto]").forEach((el) => { el.onclick = () => { const [a, b] = el.dataset.goto.split("/"); s.section = a; s.sub[a] = b; if (a === "log") s.logv.data = null; this.closeDialog(true); this.resetFilters(); this.persist(); this.render(true); }; });
    // filters
    const q = $("q"); if (q) q.addEventListener("input", (e) => { s.f.q = e.target.value; this.renderResults(); });
    const so = $("sort"); if (so) so.addEventListener("change", (e) => { s.f.sort = e.target.value; this.renderResults(); });
    on("[data-cat]", "click", (e) => { s.f.category = e.currentTarget.dataset.cat || null; this.renderContent(); });
    on("[data-ff]", "change", (e) => { s.f[e.currentTarget.dataset.ff] = e.currentTarget.value || null; this.renderContent(); });
    on("[data-ffclear]", "click", () => { const sort = s.f.sort; this.resetFilters(); s.f.sort = sort; this.renderContent(); });
    on("[data-addtile]", "click", () => this.goAdd());
    on("[data-addtile]", "keydown", (e) => { if (e.key === "Enter") this.goAdd(); });
    on(".shop[data-shop]", "click", (e) => { if (e.target.closest("button, a")) return; this.openShop(e.currentTarget.dataset.shop); });
    on(".shop[data-shop]", "keydown", (e) => { if (e.key === "Enter" && e.target === e.currentTarget) this.openShop(e.currentTarget.dataset.shop); });
    on("[data-range]", "click", (e) => { s.range = +e.currentTarget.dataset.range; this.persist(); this.renderContent(); });
    const thr = $("thr"); if (thr) { thr.addEventListener("input", (e) => { const v = $("thrv"); if (v) v.textContent = e.target.value + "%"; }); thr.addEventListener("change", (e) => { s.threshold = +e.target.value; this.render(); }); }
    // add by address
    const url = $("a_url"); if (url) url.addEventListener("input", () => {
      const v = url.value.trim(), h = $("a_hint");
      if (!v) { h.textContent = ""; return; }
      let host = ""; try { host = new URL(v).hostname.replace(/^www\./, ""); } catch (e) { h.innerHTML = `<span class="err">${t("That is not a web address")}</span>`; return; }
      const known = Object.keys(this.state.data.retailers).some((rid) => (this.state.settings?.shops || []).some((x) => x.id === rid && x.domain && (host === x.domain || host.endsWith("." + x.domain))));
      h.innerHTML = this.state.settings && !known ? `<span style="color:#9a6a00">${t("{host} is not one of your shops yet: add it under Manage → Shops & jobs first.", { host: esc(host) })}</span>` : "";
    });
    const add = $("a_go"); if (add) add.addEventListener("click", () => {
      const v = (id) => (root.querySelector("#" + id) || {}).value?.trim?.() || "";
      const d = { type: "argus/add_product", url: v("a_url") };
      for (const [k, id] of [["name", "a_name"], ["ean", "a_ean"], ["brand", "a_brand"], ["mpn", "a_mpn"], ["category", "a_cat"]]) if (v(id)) d[k] = v(id);
      for (const [k, id] of [["ref_price", "a_ref"], ["target_price", "a_target"]]) if (v(id)) { const x = +money(v(id)); if (!(x > 0)) return this.toast(t("{field}: invalid number", { field: k }), "err"); d[k] = x; }
      if (+v("a_prio")) d.priority = +v("a_prio");
      if (!d.url && !d.name && !d.ean) return this.toast(t("Enter the address of a product page, or at least a name."), "err");
      this.busy(add, t("Reading the page…"), async () => {
        const r = await this._hass.callWS(d);
        s.addPrefill = null; await this.load(); this.toast(t("Added: {name}", { name: (r.name || "").slice(0, 60) }), "ok");
        const box = this.shadowRoot.getElementById("a_result"); if (box) { box.innerHTML = this.addedHtml(r); this.bindCards(box); }
        ["a_url", "a_name", "a_ean", "a_brand", "a_mpn", "a_target", "a_ref"].forEach((id) => { const el = this.shadowRoot.getElementById(id); if (el) el.value = ""; });
      });
    });
    // header-style action buttons inside content (Shops & jobs)
    root.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => this.startJob(b.dataset.act, b)));
    // shop pause: resume one ("") = all
    root.querySelectorAll("[data-resume]").forEach((b) => b.addEventListener("click", () => this.busy(b, "…", async () => {
      const rid = b.dataset.resume;
      const info = await this._hass.callWS({ type: "argus/shop_action", action: rid ? "resume" : "resume_all", ...(rid ? { retailer: rid } : {}) });
      Object.assign(this.state.data, { paused: info.paused }); this.state.settings = null; await this.load(); this.toast(rid ? t("Shop resumed") : t("All pauses lifted"), "ok");
    })));
    root.querySelectorAll("[data-shoplog]").forEach((a) => a.addEventListener("click", () => { Object.assign(s.logv, { level: "", kind: "", retailer: a.dataset.shoplog, source: "", status: "fail", product: "", q: "", data: null, open: null }); s.section = "log"; s.sub.log = "checks"; this.persist(); this.render(true); }));
    // settings, errors, notifications
    if ($("relaybox")) this.bindRelay($("relaybox"));
    if ($("contbox")) this.bindCont($("contbox"));
    if ($("d_res")) this.bindSecret(root, $);
    if ($("lb_go")) this.bindLab(root, $);
    if ($("o_save")) this.bindSettings(root, $);
    if ($("df_save")) this.bindDealSettings(root, $);
    if ($("e_shop")) this.bindErrors(root, $);
    if ($("lg_reload")) this.bindLog(root, $);
    if (root.querySelector("[data-nf]")) this.bindNotify(root, $);
    // link check
    const L = s.links;
    on("[data-lstatus]", "click", (e) => { L.status = e.currentTarget.dataset.lstatus; L.edit = null; this.renderContent(); });
    const lv = $("lverify"); if (lv) lv.addEventListener("click", () => this.busy(lv, "…", async () => { const r = (await this.svc("verify_links", {}, true)).response; await this.load(); this.toast(t("{suspect} suspicious, {ok} OK, {unknown} cannot be judged yet", { suspect: r.suspect, ok: r.ok + r.confirmed, unknown: r.unknown }), "ok"); }));
    root.querySelectorAll("tr[data-key]").forEach((tr) => {
      const [num, rid] = tr.dataset.key.split("|"), b = (c) => tr.querySelector("." + c);
      if (b("lok")) b("lok").onclick = () => this.busy(b("lok"), "", async () => { await this.svc("confirm_offer", { product: num, retailer: rid }); await this.load(); this.toast(t("Link approved"), "ok"); });
      if (b("lrm")) b("lrm").onclick = () => { if (!confirm(t("Remove this link? It will not be linked automatically again."))) return; this.busy(b("lrm"), "", async () => { await this.svc("remove_offer", { product: num, retailer: rid }); await this.load(); this.toast(t("Link removed"), "ok"); }); };
      const toggle = () => { L.edit = L.edit === tr.dataset.key ? null : tr.dataset.key; this.renderContent(); };
      if (b("ledit")) b("ledit").onclick = (e) => { e.stopPropagation(); toggle(); };
      tr.addEventListener("click", (e) => { if (e.target.closest("button,a,[data-set],input")) return; toggle(); });
    });
    if ($("lverify")) root.querySelectorAll(".efix .item[data-inum]").forEach((box) => this.bindItemEditor(box, () => this.renderContent()));
    // import wizard
    const imp = s.imp;
    const analyze = async () => { if (!imp.text.trim()) return this.toast(t("Choose a file or paste CSV text"), "err"); try { imp.analysis = await this._hass.callWS({ type: "argus/import_preview", csv_text: imp.text }); this.renderContent(true); } catch (e) { this.toast(tx(e.message), "err"); } };
    const readFile = async (f) => { if (!f) return; if (f.size > 1_000_000) return this.toast(t("File too large (max {mb} MB).", { mb: 1 }), "err"); imp.text = await f.text(); imp.name = f.name; await analyze(); };
    const drop = $("drop"); if (drop) {
      ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", (e) => readFile(e.dataTransfer.files[0]));
      $("csvfile").addEventListener("change", (e) => readFile(e.target.files[0]));
    }
    const an = $("analyze"); if (an) an.addEventListener("click", () => { imp.text = $("csvtext").value; imp.name = ""; this.busy(an, t("Checking…"), analyze); });
    const back = $("impback"); if (back) back.addEventListener("click", () => { imp.analysis = null; this.renderContent(true); });
    const idc = $("imp_discover"); if (idc) idc.addEventListener("change", (e) => { imp.discover = e.target.checked; });
    const go = $("impgo"); if (go) go.addEventListener("click", () => this.busy(go, t("Importing…"), async () => {
      const r = await this._hass.callWS({ type: "argus/import_products", csv_text: imp.text, discover: imp.discover });
      s.imp = { text: "", name: "", analysis: null, discover: true };
      this.toast(t("{job} started for {n} products", { job: tx(r.job.label), n: r.job.total }), "ok"); this.state.job = r.job; this.pollJob(); this.renderJob();
      s.section = "prices"; s.sub.prices = "all"; this.persist(); this.render(true);
    }));
    // shop settings (Shops & jobs, Legal)
    const ssi = $("ss_import"); if (ssi) ssi.onclick = () => this.openShopSettings(true);
    const ssa = $("ss_accept"); if (ssa) ssa.onclick = () => this.openShopSettings();
    const sse = $("ss_export"); if (sse) sse.onclick = () => this.busy(sse, "…", async () => { const x = await this._hass.callWS({ type: "argus/shop_settings/export" }); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(x, null, 2)], { type: "application/json" })); a.download = "argus-shop-settings.json"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000); });
    const ssw = $("ss_withdraw"); if (ssw) ssw.onclick = () => { if (!confirm(t("Remove the shop settings and withdraw your acceptance? From then on no shop is contacted; your products and prices stay."))) return; this.busy(ssw, "…", async () => { await this._hass.callWS({ type: "argus/shop_settings/withdraw" }); await new Promise((res) => setTimeout(res, 1500)); await this.load(); }); };
    // backup
    const dl = (name, text, mime) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: mime })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000); };
    for (const id of ["expcsv", "expcsv2"]) { const ec = $(id); if (ec) ec.addEventListener("click", () => this.busy(ec, "…", async () => { const x = await this.svc("export_products", {}, true); dl("argus_products.csv", "﻿" + x.response.csv, "text/csv;charset=utf-8"); this.toast(t("CSV downloaded"), "ok"); })); }
    const ej = $("expjson"); if (ej) ej.addEventListener("click", () => this.busy(ej, "…", async () => { const x = await this.svc("export_data", {}, true); dl(`argus_backup_${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(x.response, null, 1), "application/json"); this.toast(t("Backup downloaded"), "ok"); }));
    const jd = $("jdrop"); if (jd) {
      let payload = null;
      const pick = async (f) => { if (!f) return; try { payload = JSON.parse(await f.text()); $("jname").textContent = `${f.name} · ${t("{n} products", { n: Object.keys(payload.products || {}).length })}`; $("impjson").disabled = false; } catch (e) { payload = null; $("impjson").disabled = true; this.toast(t("Not a valid JSON file"), "err"); } };
      ["dragenter", "dragover"].forEach((ev) => jd.addEventListener(ev, (e) => { e.preventDefault(); jd.classList.add("over"); }));
      ["dragleave", "drop"].forEach((ev) => jd.addEventListener(ev, (e) => { e.preventDefault(); jd.classList.remove("over"); }));
      jd.addEventListener("drop", (e) => pick(e.dataTransfer.files[0])); $("jsonfile").addEventListener("change", (e) => pick(e.target.files[0]));
      const ij = $("impjson"); ij.addEventListener("click", () => {
        const merge = $("merge").checked; if (!merge && !confirm(t("All current data will be replaced. Continue?"))) return;
        this.busy(ij, t("Checking and restoring…"), async () => { const r = await this.svc("import_data", { data: payload, merge }, true); await this.load(); this.toast(t("Backup restored: {n} products", { n: r.response.products }), "ok"); });
      });
    }
  }


  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.state = {
      section: "prices", sub: { prices: "today", overview: "cost", log: "all", manage: "add" },
      f: { q: "", category: null, sort: "score" }, threshold: null, range: 90, addMode: "url",
      imp: { text: "", name: "", analysis: null, discover: true },
      links: { status: "suspect", edit: null },
      errs: { type: "all", shop: "", open: null, showIgnored: false },
      logv: { level: "", kind: "", retailer: "", source: "", status: "", product: "", q: "", data: null, open: null, extra: [] },
      notif: { data: null, edit: null, idx: null, err: null },
      data: null, coll: null, err: null, busy: false,
    };
    try {
      const saved = JSON.parse(localStorage.getItem("argus_ui") || "{}");
      if (SECTIONS[saved.section]) this.state.section = saved.section;
      if ([0, 30, 90, 365].includes(saved.range)) this.state.range = saved.range;
      for (const [k, v] of Object.entries(saved.sub || {})) if (SECTIONS[k] && SECTIONS[k].subs.some(([x]) => x === v)) this.state.sub[k] = v;
    } catch (e) { /* storage unavailable */ }
    this.resetFilters();
    // approving a suspicious price works the same everywhere (set dialog, shops & jobs, logbook)
    this.shadowRoot.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest(".apprb"); if (!b) return;
      e.stopPropagation(); e.preventDefault();
      this.busy(b, "…", async () => {
        const r = await this._hass.callWS({ type: "argus/offer/approve", product: b.dataset.anum, retailer: b.dataset.arid });
        this.toast(t("Price {price} approved", { price: EUR(r.price) }), "ok");
        await this.load();
        const d = this.shadowRoot.getElementById("dlg"); if (d && d.open && d.querySelector(".orow")) this.openSet(b.dataset.anum);
      });
    }, true);
    // your own price or the newly fetched one: the same two choices everywhere
    this.shadowRoot.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest(".pcb"); if (!b) return;
      e.stopPropagation(); e.preventDefault();
      const num = b.dataset.pnum, accept = b.dataset.pacc === "1";
      this.busy(b, "…", async () => {
        const r = await this._hass.callWS({ type: "argus/offer/price_choice", product: num, retailer: b.dataset.prid, accept });
        this.toast(accept ? t("Price {price} approved", { price: EUR(r.price) }) : t("Your own price {price} stays", { price: EUR(r.price) }), "ok");
        await this.load();
        if (this.state.section === "log") this.loadLog();
        const d = this.shadowRoot.getElementById("dlg"); if (d && d.open && d.querySelector(".orow")) this.openSet(num);
      });
    }, true);
    // a doubtful link: the same two choices everywhere (set dialog, shops & jobs, logbook)
    this.shadowRoot.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest(".ldb"); if (!b) return;
      e.stopPropagation(); e.preventDefault();
      const num = b.dataset.lnum, rid = b.dataset.lrid, ok = b.dataset.lact === "ok";
      this.busy(b, "…", async () => {
        if (ok) await this.svc("confirm_offer", { product: num, retailer: rid });
        else await this._hass.callWS({ type: "argus/offer/reject", product: num, retailer: rid });
        this.toast(ok ? t("Link of {number} approved", { number: num }) : t("Link blocked; the shop is searched again"), "ok");
        await this.load();
        if (this.state.section === "log") this.loadLog();
        const d = this.shadowRoot.getElementById("dlg"); if (d && d.open && d.querySelector(".orow")) this.openSet(num);
      });
    }, true);
    // browser relay: progress messages from the userscript running in this browser
    window.addEventListener("message", (e) => {
      const m = e.data;
      // only the userscript in this very page (not another frame or site), and only plain values
      if (e.origin !== location.origin || (e.source && e.source !== window) || !m || typeof m !== "object" || m.source !== "argus-userscript") return;
      const num = (v) => (Number.isFinite(+v) ? +v : 0), str = (v) => (typeof v === "string" ? v.slice(0, 80) : "");
      if (m.type === "relay-pong") this.state.relayHere = { version: str(m.version), token: !!m.token, running: !!m.running, last: num(m.last), continuous: !!m.continuous, render: !!m.render };
      if (m.type === "continuous-status") {
        this.state.contRun = { on: !!m.on, running: !!m.running, idle: !!m.idle, other_tab: !!m.other_tab, done: num(m.done), ok: num(m.ok), fail: num(m.fail),
          found: num(m.found), next: num(m.next), shop: str(m.shop), product: str(m.product), error: str(m.error) };
      }
      if (m.type === "relay-status") {
        this.state.relayRun = { running: !!m.running, finished: !!m.finished, disabled: !!m.disabled, done: num(m.done), total: num(m.total), ok: num(m.ok), fail: num(m.fail),
          shop: str(m.shop), product: str(m.product), error: str(m.error) };
        m.ok = num(m.ok); m.fail = num(m.fail);
        if (m.finished) { this.toast(t("Browser relay done: {ok} prices, {fail} failed", { ok: m.ok, fail: m.fail }), m.ok ? "ok" : "err"); this.load(); }
        if (m.error === "no-token") this.toast(t("The userscript has no token yet: Tampermonkey menu → ARGUS settings"), "err");
      }
      const box = this.shadowRoot && this.shadowRoot.getElementById("relaybox"); if (box) { box.innerHTML = this.relayBoxInner(); this.bindRelay(box); }
      const cbox = this.shadowRoot && this.shadowRoot.getElementById("contbox"); if (cbox) { cbox.innerHTML = this.contBoxInner(); this.bindCont(cbox); }
    });
  }
  relayPing() { try { window.postMessage({ source: "argus-panel", type: "relay-ping" }, "*"); } catch (e) { /* ignore */ } }
  relayBoxInner() {
    const d = this.state.data || {}, here = this.state.relayHere, run = this.state.relayRun, last = d.relay_last, rel = d.relay || {};
    const status = here ? `<span class="lk ok">✓ ${t("active in this browser")} (v${esc(here.version)})</span>${here.token ? "" : ` <span class="lk suspect">${t("no token yet")}</span>`}` : `<span class="lk unknown">${t("not detected in this browser")}</span>`;
    const prog = run && run.running ? `<div class="meter" style="margin:8px 0"><i style="width:${run.total ? Math.round((run.done / run.total) * 100) : 0}%;animation:none;transition:width .6s"></i></div><div class="muted" style="font-size:12px">${t("{done}/{total} pages · {ok} prices · {fail} failed", { done: run.done || 0, total: run.total || 0, ok: run.ok || 0, fail: run.fail || 0 })}${run.shop ? ` · ${esc(run.shop)} ${esc(run.product || "")}` : ""}</div>` : "";
    return `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${status}<span class="muted" style="font-size:13px">${rel.enabled === false ? t("Browser relay is off (Settings)") : t("{n} shop pages waiting for the relay", { n: rel.pending ?? 0 })}${last && last.ts ? " · " + t("last run {when}: {ok} prices, {fail} failed", { when: ago(last.ts), ok: last.ok || 0, fail: last.fail || 0 }) : ""}</span>
      <span class="hsp" style="flex:1"></span><button class="btn sm" id="relaygo" ${here && !(run && run.running) && rel.enabled !== false ? "" : "disabled"}>▶ ${t("Run now in this browser")}</button></div>${prog}`;
  }
  /** The userscript's continuous check: status in this browser, the last sign of life of any browser, the queue. */
  /** The userscript's continuous check: status in this browser, the last sign of life of any browser, the queue. */
  contBoxInner() {
    const d = this.state.data || {}, rel = d.relay || {}, here = this.state.relayHere, run = this.state.contRun || {}, hb = rel.heartbeat, q = rel.continuous || {};
    const on = run.on != null ? run.on : !!(here && here.continuous);
    const local = !here ? `<span class="lk unknown">${t("userscript not detected in this browser")}</span>`
      : !here.token ? `<span class="lk suspect">${t("no token yet")}</span>`
      : on ? (run.other_tab ? `<span class="lk ok">✓ ${t("on: another tab of this browser does the work")}</span>` : `<span class="lk ok">✓ ${t("on in this browser")}</span>`)
      : `<span class="lk unknown">${t("off in this browser")}</span>`;
    const alive = hb && hb.ts && Date.now() / 1000 - hb.ts < 15 * 60 && hb.on;
    const remote = hb && hb.ts ? (alive ? `<span class="lk ok">⏺ ${t("a browser is checking (last sign of life {when})", { when: ago(hb.ts) })}</span>` : `<span class="muted">${t("last sign of life of a browser: {when}", { when: ago(hb.ts) })}</span>`) : `<span class="muted">${t("no browser has done a continuous check yet")}</span>`;
    const now = on && run.running && !run.other_tab ? `<div class="muted" style="font-size:12px;margin-top:6px">${run.idle ? t("Nothing to do right now: it looks again every 10 minutes.") : run.next ? t("Waiting until a site may be asked again ({time}).", { time: TIME(run.next / 1000) }) : run.shop ? t("Now: {shop} {number}", { shop: esc(run.shop), number: esc(this.nameOf(run.product)) }) : ""}
      ${run.done ? ` · ${t("{done} checked · {ok} prices · {found} links found · {fail} failed", { done: run.done, ok: run.ok || 0, found: run.found || 0, fail: run.fail || 0 })}` : ""}</div>` : "";
    const queue = rel.enabled === false ? t("Browser relay is off (Settings)") : t("Waiting: {a} links without a price · {d} open errors · {b} searches at shops without a link · {c} links the server can't fetch", { a: q.no_price || 0, d: q.open_error || 0, b: q.search || 0, c: q.server_fails || 0 });
    return `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${local}${remote}<span class="hsp" style="flex:1"></span>
      <button class="btn sm${on ? " ghost" : ""}" id="contgo" ${here && here.token && rel.enabled !== false ? "" : "disabled"}>${on ? `■ ${t("Switch off in this browser")}` : `▶ ${t("Switch on in this browser")}`}</button></div>
      <div class="muted" style="font-size:13px;margin-top:6px">${queue}</div>${now}${run.error ? `<div class="err" style="font-size:12px;margin-top:4px">⚠ ${run.error === "no-token" ? t("Home Assistant rejected the token (401)") : esc(run.error)}</div>` : ""}
      <label class="chk" style="display:flex;gap:8px;align-items:flex-start;margin-top:10px" title="${esc(t("Needs the userscript version that asks for the right to open tabs; Tampermonkey asks you to confirm when it updates."))}"><input type="checkbox" id="rendertabs" ${here && here.render ? "checked" : ""} ${here && here.token ? "" : "disabled"}>
        <span>${t("Search shops that build their results with JavaScript in a background tab")}<br><span class="muted" style="font-size:12px">${t("A tab opens in the background for a few seconds, the script reads the finished page and the tab closes again. At most one search per shop every 2 minutes.")}</span></span></label>`;
  }
  bindCont(box) {
    const rt = box.querySelector("#rendertabs");
    if (rt) rt.onchange = () => { window.postMessage({ source: "argus-panel", type: "render-set", on: rt.checked }, "*"); this.toast(rt.checked ? t("Background tabs switched on in this browser") : t("Background tabs switched off"), "ok"); };
    const b = box.querySelector("#contgo"); if (!b) return;
    b.onclick = () => {
      const run = this.state.contRun || {}, here = this.state.relayHere || {}, on = run.on != null ? run.on : !!here.continuous;
      window.postMessage({ source: "argus-panel", type: "continuous-set", on: !on }, "*");
      this.state.contRun = { ...run, on: !on }; box.innerHTML = this.contBoxInner(); this.bindCont(box);
      this.toast(!on ? t("Continuous check switched on in this browser") : t("Continuous check switched off"), "ok");
    };
  }
  bindRelay(box) { const b = box.querySelector("#relaygo"); if (b) b.onclick = () => { window.postMessage({ source: "argus-panel", type: "relay-run" }, "*"); this.state.relayRun = { running: true, done: 0, total: 0 }; box.innerHTML = this.relayBoxInner(); }; }
  set hass(h) {
    const first = !this._hass; this._hass = h;
    if (first) { try { this.render(true); } catch (e) { this.crash(e); } this.load().catch((e) => this.crash(e)); }
  }
  /** Something broke while drawing: show it (never a black page) and send it to the Home Assistant log. */
  /** Something broke while drawing: show it (never a black page) and send it to the Home Assistant log. */
  crash(e) {
    const msg = String((e && e.message) || e), stack = String((e && e.stack) || "").slice(0, 3000);
    try { if (this._hass) this._hass.callWS({ type: "argus/client_error", message: msg.slice(0, 500), stack, ua: navigator.userAgent.slice(0, 300), view: `${this.state.section}/${this.state.sub[this.state.section]}` }); } catch (x) { /* ignore */ }
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `<div style="padding:24px;font-family:system-ui,sans-serif;color:var(--primary-text-color,#111);background:var(--primary-background-color,#fff);min-height:100vh;box-sizing:border-box">
      <h2 style="margin:0 0 8px">👁 ARGUS</h2><p>Something went wrong while showing this page. The error was sent to the Home Assistant log (custom_components.argus).</p>
      <pre style="white-space:pre-wrap;font-size:12px;opacity:.8">${esc(msg)}</pre><button id="crash_reload" style="padding:10px 16px;border-radius:10px;border:0;background:#0057a6;color:#fff;font-size:15px">↻ Reload</button></div>`;
    const b = this.shadowRoot.getElementById("crash_reload");
    if (b) b.onclick = () => { this.state.section = "prices"; try { localStorage.removeItem("argus_ui"); } catch (x) { /* ignore */ } this._rendered = false; this.shadowRoot.innerHTML = ""; try { this.render(true); } catch (x) { this.crash(x); return; } this.load().catch((x) => this.crash(x)); };
  }
  set narrow(v) { this._narrow = v; }
  set panel(_) {}
  colorTheme() { try { const c = localStorage.getItem("argus_colors"); return COLOR_THEMES.some(([k]) => k === c) ? c : "ha"; } catch (e) { return "ha"; } }
  // the host may get attributes only once it is in the page: an attribute set in the constructor makes Firefox
  // refuse to create the panel (NotSupportedError)
  // the host may get attributes only once it is in the page: an attribute set in the constructor makes Firefox
  // refuse to create the panel (NotSupportedError)
  // the host may get attributes only once it is in the page: an attribute set in the constructor makes Firefox
  // refuse to create the panel (NotSupportedError)
  // the host may get attributes only once it is in the page: an attribute set in the constructor makes Firefox
  // refuse to create the panel (NotSupportedError)
  connectedCallback() { if (!this._colored) { this._colored = true; this.applyColors(this.colorTheme()); } }
  applyColors(key) { if (key && key !== "ha") this.dataset.colors = key; else delete this.dataset.colors; }
  persist() { try { localStorage.setItem("argus_ui", JSON.stringify({ section: this.state.section, sub: this.state.sub, cview: this.state.cview, range: this.state.range })); } catch (e) { /* ignore */ } }

  // ---------------------------------------------------------------- data
  // ---------------------------------------------------------------- data
  async load(animate = false) {
    try {
      const [d, c] = await Promise.all([this._hass.callWS({ type: "argus/overview" }), this._hass.callWS({ type: "argus/collection" })]);
      if (await loadLanguage(d.language, d.version)) { animate = true; this.shadowRoot.host.setAttribute("lang", LANG); }
      this.state.data = d; this.state.coll = c; this.state.err = null; this.state.mAt = Date.now() / 1000;
      if (this.state.threshold == null) this.state.threshold = d.threshold;
      this.state.job = d.job; if (d.job && d.job.running) this.pollJob();
      if ((d.first_checks || []).length) this.followFirstChecks();
      if (!this._tickerAt || Date.now() - this._tickerAt > TICKER_RELOAD) this.loadTicker();
    } catch (e) { this.state.err = e.message || String(e); }
    this.render(animate || !this._rendered);
    const ss = (this.state.data || {}).shop_settings;
    if (ss && !ss.ready && !this._gateShown && (!this._hass.user || this._hass.user.is_admin)) { this._gateShown = true; this.openShopSettings(); }
  }
  // ---------------------------------------------------------------- ticker (latest prices, deals, news)
  /** The content (deals, watchlist, news, solved errors) is reloaded every 10 minutes; in between it keeps scrolling. */
  // ---------------------------------------------------------------- ticker (latest prices, deals, news)
  /** The content (deals, watchlist, news, solved errors) is reloaded every 10 minutes; in between it keeps scrolling. */
  // ---------------------------------------------------------------- ticker (latest prices, deals, news)
  /** The content (deals, watchlist, news, solved errors) is reloaded every 10 minutes; in between it keeps scrolling. */
  // ---------------------------------------------------------------- ticker (latest prices, deals, news)
  /** The content (deals, watchlist, news, solved errors) is reloaded every 10 minutes; in between it keeps scrolling. */
  async loadTicker() {
    this._tickerAt = Date.now();
    clearTimeout(this._tickerTimer); this._tickerTimer = setTimeout(() => { if (this.isConnected) this.loadTicker(); }, TICKER_RELOAD);
    let tk;
    try { tk = await this._hass.callWS({ type: "argus/ticker", lang: LANG, ...(this._tkSince ? { since: this._tkSince } : {}) }); } catch (e) { return; }
    this._tkSince = tk.cursor ?? tk.now; this.state.ticker = tk;      // more solved errors waiting: they come next time
    // solved errors wait in a queue until a round has really shown them (the server sends each one once)
    const q = this._tkFixed || (this._tkFixed = []);
    for (const f of tk.fixed || []) if (!q.some((x) => x.ts === f.ts && x.product === f.product && x.shop === f.shop)) q.push(f);
    this.renderTicker();
  }
  /** News you closed ("read"): hidden until a new news file is put online. */
  /** News you closed ("read"): hidden until a new news file is put online. */
  newsClosed() {
    const tk = this.state.ticker || {};
    try { const c = JSON.parse(localStorage.getItem("ar_news_closed") || "{}"); return c.hash === tk.news_hash ? c.ids || [] : []; } catch (e) { return []; }
  }
  tickerHtml() {
    const tk = this.state.ticker; if (!tk) return "";
    const closed = this.newsClosed();
    const parts = (tk.news || []).map((n, i) => closed.includes(n.id) ? "" : `<button class="ti news" type="button" data-tnews="${i}"><span class="dot" title="${esc(t("Unread"))}">●</span> 📰 <b>${esc(n.title)}</b></button>`).filter(Boolean);
    // 🔥 good price (deal score ≥ 45), 🔥🔥 super price (≥ 70), 🔥🔥🔥 amazing price (≥ 85)
    const fire = (sc) => { const n = sc >= 85 ? 3 : sc >= 70 ? 2 : sc >= 45 ? 1 : 0; return n ? ` <span class="fire" title="${esc(n === 3 ? t("Amazing price") : n === 2 ? t("Super price") : t("Good price"))}">${"🔥".repeat(n)}</span>` : ""; };
    const tag = (l, title) => `<span class="tktag" title="${esc(title)}">${l}</span>`;
    for (const it of tk.items || []) {
      const who = `<b>${esc((it.name || "").slice(0, 48))}</b>`;
      // a discount is only shown when the price is below the RRP (never "−-110%")
      const off = it.discount > 0 && Math.round(it.discount) > 0 ? ` −${Math.round(it.discount)}%` : "";
      if (it.kind === "deal") {
        parts.push(`<button class="ti deal" type="button" data-tset="${esc(it.product)}">${tag("D", t("Deal"))}${fire(it.score)} ${who} ${it.price != null ? EUR(it.price) : ""}${off}${it.shop ? ` · ${esc(it.shop)}` : ""}</button>`);
      } else {
        parts.push(`<button class="ti" type="button" data-tset="${esc(it.product)}">${tag("↓", t("Price drop"))}${fire(it.score)} ${who} ${EUR(it.price)}${it.change != null && it.change <= -1 ? ` ${Math.round(it.change)}%` : off}${it.shop ? ` · ${esc(it.shop)}` : ""}</button>`);
      }
    }
    // errors solved since the previous ticker: shown this once (gone at the next reload)
    for (const f of this._tkFixed || []) parts.push(`<button class="ti fixed" type="button" data-tset="${esc(f.product)}">✅ ${esc(t("Error fixed"))}: <b>${esc((f.name || "").slice(0, 48))}</b>${f.shop ? ` · ${esc(f.shop)}` : ""}</button>`);
    const cfg = tk.config || {};
    if (cfg.shuffle !== false) for (let i = parts.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [parts[i], parts[j]] = [parts[j], parts[i]]; }   // mixed
    if (!parts.length && (cfg.drops || cfg.deals || cfg.news)) return `<span class="ti muted" data-ph="1">${esc(t("No prices or news yet: they appear here as soon as the first prices come in."))}</span>`;
    return parts.join("");
  }
  /** New content waits for the end of the current round, so the ticker never jumps or starts over. */
  /** New content waits for the end of the current round, so the ticker never jumps or starts over. */
  renderTicker(now = false) {
    const el = this._tickerEl; if (!el || !this.state.ticker) return;
    const html = this.tickerHtml();
    const track = el.querySelector(".tk");
    if (!html) { el.innerHTML = ""; this._tkPending = null; return; }
    if (!track) {
      el.innerHTML = `<span class="lbl">📈</span><div class="tkv"><div class="tk"></div></div>`;
      el.addEventListener("mouseenter", () => { this._tkHold = true; }); el.addEventListener("mouseleave", () => { this._tkHold = false; });
      el.addEventListener("focusin", () => { this._tkHold = true; }); el.addEventListener("focusout", () => { this._tkHold = false; });
      el.addEventListener("click", (e) => {
        const b = e.target.closest("[data-tset],[data-tnews]"); if (!b) return;
        if (b.dataset.tset) this.openSet(b.dataset.tset); else this.openNews(+b.dataset.tnews);
      });
      this._tkPlace = () => { const r = this.getBoundingClientRect(); el.style.left = Math.max(0, r.left) + "px"; el.style.right = Math.max(0, window.innerWidth - r.right) + "px"; };
      window.addEventListener("resize", () => this._tickerEl && this._tkPlace());
    }
    this._tkPlace();
    const tr = el.querySelector(".tk");
    if (now || !tr.innerHTML || tr.querySelector("[data-ph]")) { this.applyTicker(tr, html); this._tkPos = 0; } else this._tkPending = { html, fixed: (this._tkFixed || []).slice() };
    this.tickerLoop();
  }
  /** Put content on the running track; the solved errors in it have been shown and leave the queue. */
  /** Put content on the running track; the solved errors in it have been shown and leave the queue. */
  applyTicker(tr, html, fixed = (this._tkFixed || []).slice()) {
    tr.innerHTML = html; this._tkPending = null;
    if (this._tkFixed) this._tkFixed = this._tkFixed.filter((f) => !fixed.includes(f));
  }
  /** Scrolls the ticker at an even speed from a position that survives re-renders, tab switches and popups. */
  /** Scrolls the ticker at an even speed from a position that survives re-renders, tab switches and popups. */
  tickerLoop() {
    if (this._tkRaf) return;
    const SPEED = 70;                                   // pixels per second
    let last = 0;
    const step = (ts) => {
      const el = this._tickerEl, tr = el && el.querySelector(".tk");
      if (!this.isConnected || !tr) { this._tkRaf = null; return; }
      const dt = last ? Math.min(ts - last, 100) : 0; last = ts;
      const view = tr.parentElement.clientWidth;
      if (REDUCED) { tr.style.transform = ""; if (this._tkPending) this.applyTicker(tr, this._tkPending.html, this._tkPending.fixed); this._tkRaf = requestAnimationFrame(step); return; }
      if (!this._tkHold) this._tkPos = (this._tkPos || 0) + dt * SPEED / 1000;
      if (this._tkPos > tr.scrollWidth + view) {         // one round done: start again from the right, with new content
        this._tkPos = 0;
        if (this._tkPending) this.applyTicker(tr, this._tkPending.html, this._tkPending.fixed);
      }
      tr.style.transform = `translateX(${view - this._tkPos}px)`;
      this._tkRaf = requestAnimationFrame(step);
    };
    this._tkRaf = requestAnimationFrame(step);
  }
  /** Take one news item out of the running ticker without a jump. */
  /** Take one news item out of the running ticker without a jump. */
  dropNews(i) {
    const tr = this._tickerEl && this._tickerEl.querySelector(".tk"); if (!tr) return;
    const b = tr.querySelector(`[data-tnews="${i}"]`);
    if (b) {
      const view = tr.parentElement.clientWidth, w = b.offsetWidth + 28;
      if (view - (this._tkPos || 0) + b.offsetLeft + b.offsetWidth < 0) this._tkPos -= w;   // already passed: keep the rest in place
      b.remove();
    }
    if (this._tkPending) this._tkPending = { html: this.tickerHtml(), fixed: (this._tkFixed || []).slice() };
  }
  /** One news item in a popup: plain text (escaped), links only https:// or inside Home Assistant.
   *  Close = read: hidden until a new news file is online. Keep unread = it stays in the ticker with ●. */
  /** One news item in a popup: plain text (escaped), links only https:// or inside Home Assistant.
   *  Close = read: hidden until a new news file is online. Keep unread = it stays in the ticker with ●. */
  /** One news item in a popup: plain text (escaped), links only https:// or inside Home Assistant.
   *  Close = read: hidden until a new news file is online. Keep unread = it stays in the ticker with ●. */
  /** One news item in a popup: plain text (escaped), links only https:// or inside Home Assistant.
   *  Close = read: hidden until a new news file is online. Keep unread = it stays in the ticker with ●. */
  openNews(i) {
    const tk = this.state.ticker || {}, n = (tk.news || [])[i];
    if (!n) return;
    const linkify = (txt) => esc(txt).replace(/https:\/\/[^\s<]+[^\s<.,;:!?)]/g, (u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
    const body = !(n.body || "").trim() ? `<p class="muted">${esc(t("This news item has no text."))}</p>` : (n.body || "").split(/\n\s*\n/).map((p) => `<p>${linkify(p).replace(/\n/g, "<br>")}</p>`).join("");
    const link = n.link ? (n.link.startsWith("/") ? `<a class="btn" href="${esc(n.link)}" target="_top">${t("Open")} →</a>` : `<a class="btn" href="${esc(n.link)}" target="_blank" rel="noopener noreferrer">${t("Open")} ↗</a>`) : "";
    const dlg = this.shadowRoot.getElementById("dlg");
    this._dlgGen = (this._dlgGen || 0) + 1; clearInterval(this._shopTimer);
    dlg.innerHTML = `<div class="dhead" style="grid-template-columns:1fr auto"><div><h2>📰 ${esc(n.title)}</h2><div class="muted">${esc(n.date || "")}</div></div><div><button class="x" id="x" aria-label="${t("Keep unread")}" title="${t("Keep unread")}">✕</button></div></div>
      <div class="dbody">${body}${link ? `<div style="margin-top:12px">${link}</div>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;border-top:1px solid var(--ar-line);padding-top:12px">
        <button class="btn" id="nw_close" title="${esc(t("Read: this news item leaves the ticker until new news is put online"))}">✓ ${t("Close")}</button>
        <button class="btn ghost" id="nw_keep" title="${esc(t("It stays in the ticker, marked as unread"))}">● ${t("Keep unread")}</button></div></div>`;
    if (!dlg.open) dlg.showModal();
    dlg.querySelector("#x").onclick = () => this.closeDialog();
    dlg.querySelector("#nw_keep").onclick = () => this.closeDialog();
    dlg.querySelector("#nw_close").onclick = () => {
      try {
        const ids = this.newsClosed(); if (!ids.includes(n.id)) ids.push(n.id);
        localStorage.setItem("ar_news_closed", JSON.stringify({ hash: tk.news_hash || "", ids: ids.slice(-100) }));
      } catch (e) { /* private mode: it shows again next time */ }
      this.closeDialog(); this.dropNews(i);
    };
    const inner = dlg.querySelector('a[target="_top"]');
    if (inner) inner.onclick = (e) => { e.preventDefault(); this.closeDialog(true); history.pushState(null, "", n.link); window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } })); };
  }
  /** Manual fetches and searches are possible once every 2 minutes (per set action, per shop site): seconds to wait. */
  /** Manual fetches and searches are possible once every 2 minutes (per set action, per shop site): seconds to wait. */
  mLeft(key) {
    const m = this.state.data && this.state.data.manual; if (!m) return 0;
    const u = key === "prices" || key === "find" ? m[key] : (m.shops || {})[key];
    return u ? Math.max(0, Math.ceil(u - m.now - (Date.now() / 1000 - this.state.mAt))) : 0;
  }
  mTitle(sec) { return t("To protect the traffic to and the load on the shops, this is possible once every 2 minutes. Available again in {s} s.", { s: sec }); }
  mAttr(key) { const sec = this.mLeft(key); return sec ? `disabled data-mwait="${esc(key)}" title="${esc(this.mTitle(sec))}"` : `data-mkey="${esc(key)}"`; }
  /** Count the greyed buttons down and switch them on again when their 2 minutes are over. */
  /** Count the greyed buttons down and switch them on again when their 2 minutes are over. */
  tickManual() {
    clearTimeout(this._mTimer);
    const roots = [this.shadowRoot, this.shadowRoot.getElementById("dlg")].filter(Boolean);
    let waiting = false;
    for (const r of roots) for (const b of r.querySelectorAll("[data-mwait]")) {
      const sec = this.mLeft(b.dataset.mwait);
      if (sec) { waiting = true; b.disabled = true; b.title = this.mTitle(sec); } else { b.disabled = false; b.removeAttribute("title"); b.dataset.mkey = b.dataset.mwait; delete b.dataset.mwait; }
    }
    if (waiting) this._mTimer = setTimeout(() => this.tickManual(), 1000);
  }
  svc(service, data = {}, ret = false) {
    return this._hass.callWS({ type: "call_service", domain: "argus", service, service_data: data, return_response: ret });
  }
  toast(msg, kind = "") {
    const box = this.shadowRoot.querySelector(".toasts"); if (!box) return;
    const t = document.createElement("div"); t.className = `toast ${kind}`;
    t.innerHTML = `<span>${kind === "err" ? "⚠️" : kind === "ok" ? "✅" : "ℹ️"}</span><span>${esc(msg)}</span>`;
    box.appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 260); }, kind === "err" ? 6500 : 3800);
  }
  async busy(btn, label, fn) {
    const old = btn ? btn.innerHTML : ""; if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${esc(label)}`; }
    try { return await fn(); } catch (e) { this.toast(tx(e.message || String(e)), "err"); return undefined; } finally { if (btn && btn.isConnected) { btn.disabled = false; btn.innerHTML = old; } }
  }

  // value of one unit, honouring the "value based on" setting
  /** Your copies of a set together: how many, their value (each by its own condition), what you paid for the
   * copies with a known price (and their value, for the gain), and their conditions. */
  /** "Refresh all prices" is off unless allowed; then at most once a minute (the server checks it too). */
  // value of one unit, honouring the "value based on" setting
  /** Your copies of a set together: how many, their value (each by its own condition), what you paid for the
   * copies with a known price (and their value, for the gain), and their conditions. */
  /** "Refresh all prices" is off unless allowed; then at most once a minute (the server checks it too). */
  fullRefreshAttr(title) {
    const d = this.state.data;
    if (d && !d.full_refresh) return `disabled title="${esc(t("Switched off to protect the traffic to and the load on the shops: prices are checked product by product in the background; use ↻ in a product to fetch one product now (once every 2 minutes)."))}"`;
    return title ? `title="${esc(title)}"` : "";
  }
  /** Left out under Deals → Settings (theme switched off, price / discount / pieces limits): why, or "". */
  // ---------------------------------------------------------------- shell
  /** Left out under Deals → Settings (theme switched off, price / discount / pieces limits): why, or "". */
  // ---------------------------------------------------------------- shell
  render(animate = false) {
    try { this._render(animate); } catch (e) { console.error(e); this.crash(e); }
  }
  _render(animate = false) {
    const s = this.state, root = this.shadowRoot;
    const gridKey = `${s.section}/${s.sub[s.section]}/${JSON.stringify(s.f)}`;
    if (gridKey !== this._gridKey) { this._gridKey = gridKey; s.gridMax = GRID_PAGE; }   // new view or filter: first page again
    this._rendered = true;
    const sec = SECTIONS[s.section], sub = s.sub[s.section];
    const d = s.data;
    const status = d ? this.healthDot() : "";
    const keepToasts = root.querySelector(".toasts"), keepDlg = root.getElementById("dlg"), dlgScroll = keepDlg ? keepDlg.scrollTop : 0;
    root.innerHTML = `<style>${STYLE}</style><div class="wrap">
      <header>${this._narrow ? `<ha-menu-button></ha-menu-button>` : ""}<img class="logo" src="/argus_static/icon.png${d ? `?v=${encodeURIComponent(d.version)}` : ""}" alt="" title="Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden" onerror="this.outerHTML=this.dataset.fb" data-fb="${esc(LOGO)}"><div><h1>ARGUS</h1><div class="meta">${d ? `v${esc(d.version)} · ${t("{n} products tracked", { n: d.products.length })}` : t("loading…")}</div></div>
        <div class="hsp"></div>${status}<button class="btn ghost sm" data-act="discover" title="${t("Look every product up at the shops of its category that have no link yet: a job you can follow and stop, spread out so every shop is searched at most once every 2 minutes")}">🔎 <span class="lbl">${t("Find at other shops")}</span></button><button class="btn sm" data-act="refresh" ${this.fullRefreshAttr(t("Fetch all shop prices now"))}>↻ <span class="lbl">${t("Refresh prices")}</span></button></header>
      ${d && d.api !== API_LEVEL ? `<div class="banner" style="border-color:var(--ar-bad,#c62828)">🔄 <span><b>${t("Restart Home Assistant to finish the update.")}</b> ${t("The new panel is loaded, but Home Assistant still runs the previous version of the integration, so some buttons and settings don't work yet. Settings → System → Restart.")}</span></div>` : ""}
      ${d && d.shop_settings && !d.shop_settings.ready ? `<div class="banner" style="border-color:var(--ar-bad,#c62828)">⚖️ <span><b>${t(d.shop_settings.imported ? "Accept the terms once to keep fetching prices." : "First step: import your shop settings.")}</b> ${t("Until then no shop is contacted. Your products and prices stay.")} <a id="gate_open">${t(d.shop_settings.imported ? "Read and accept" : "Import shop settings")} →</a></span></div>` : ""}
      <div id="jobbar"></div>
      <nav class="seg" role="tablist">${Object.entries(SECTIONS).map(([k, v]) => `<button role="tab" data-sec="${k}" class="${k === s.section ? "on" : ""}">${t(v.label)}<small>${t(v.hint)}</small></button>`).join("")}<span class="ind"></span></nav>
      <div class="sub">${sec.subs.map(([k, l]) => `<button data-sub="${k}" class="${k === sub ? "on" : ""}">${t(l)}${this.subCount(s.section, k)}</button>`).join("")}${s.section === "manage" ? `<button data-sub="secret" class="secretlink" tabindex="-1" aria-hidden="true"></button>` : ""}</div>
      <div id="content"></div></div><div class="ticker" id="ticker" role="marquee" aria-label="${t("Latest prices and news")}"></div><div class="toasts"></div><dialog id="dlg"></dialog>`;
    if (this._tickerEl) { root.getElementById("ticker").replaceWith(this._tickerEl); this.tickerLoop(); } else this._tickerEl = root.getElementById("ticker");
    // keep notifications and an open set dialog alive across re-renders (e.g. when a job finishes)
    if (keepToasts) root.querySelector(".toasts").replaceWith(keepToasts);
    if (keepDlg) {
      root.getElementById("dlg").replaceWith(keepDlg); keepDlg._bound = true;
      // taking an open dialog out of the page ends its modal state (no backdrop, content spilling out of the
      // box): show it as a modal again, without the opening animation, at the same scroll position
      if (keepDlg.open) { keepDlg.style.animation = "none"; keepDlg.close(); keepDlg.showModal(); keepDlg.scrollTop = dlgScroll; requestAnimationFrame(() => { keepDlg.style.animation = ""; }); }
    }
    const menu = root.querySelector("ha-menu-button"); if (menu) { menu.hass = this._hass; menu.narrow = this._narrow; }
    this.placeIndicator(false);
    root.querySelectorAll("[data-sec]").forEach((b) => b.addEventListener("click", () => { if (s.section === b.dataset.sec) return; s.section = b.dataset.sec; this.resetFilters(); this.persist(); this.render(true); }));
    root.querySelectorAll(".sub [data-sub]").forEach((b) => b.addEventListener("click", () => { s.sub[s.section] = b.dataset.sub; if (s.section === "log") { s.logv.data = null; s.logv.open = null; } this.resetFilters(); this.persist(); this.render(true); }));
    this.renderJob();
    const dlg = root.getElementById("dlg");
    if (!dlg._bound) dlg.addEventListener("cancel", (e) => { e.preventDefault(); this.closeDialog(); });
    if (!dlg._bound) dlg.addEventListener("click", (e) => { if (e.target === dlg) this.closeDialog(); });
    dlg._bound = true;
    if (!this._keys) { this._keys = true; this.addEventListener("keydown", (e) => { if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test((e.composedPath()[0] || {}).tagName || "")) { const q = this.shadowRoot.getElementById("q"); if (q) { e.preventDefault(); q.focus(); } } }); }
    root.querySelectorAll("header [data-act]").forEach((b) => b.addEventListener("click", () => this.startJob(b.dataset.act, b)));
    const go = root.getElementById("gate_open"); if (go) go.onclick = () => this.openShopSettings();
    this.renderContent(animate);
    this.renderJob();
    if (animate) requestAnimationFrame(() => this.placeIndicator(true));
  }
  // ---------------------------------------------------------------- background jobs
  // ---------------------------------------------------------------- background jobs
  async startJob(kind, btn) {
    const d = this.state.data || {}, paused = Object.entries(d.paused || {});
    const svc = { refresh: "refresh", discover: "find_shops" }[kind];
    const data = {};
    if (paused.length) {
      const list = paused.map(([k, h]) => `• ${k} (${t("{time} left", { time: dur(h * 3600) })})`).join("\n");
      data.force = confirm(`${t("These shops are paused after being blocked:")}\n${list}\n\n${t("OK = try anyway (risk of a new block)")}\n${t("Cancel = skip the paused shops")}`);
    }
    await this.busy(btn, t("Starting…"), async () => {
      const r = (await this.svc(svc, data, true)).response;
      if (!r.total) { this.toast(kind === "refresh" ? t("Nothing to refresh: no products with a link at an active shop") + (r.note ? ` (${tx(r.note)})` : "") : t("All products already have a link at every shop of their category"), ""); }
      else this.toast(`${t("{job} started for {n} products", { job: tx(r.label), n: r.total })}${r.note ? ` · ${tx(r.note)}` : ""}`, "ok");
      this.state.job = r; this.pollJob();
    });
    this.renderJob();
  }
  pollJob() {
    if (this._poll) return;
    const tick = async () => {
      let info; try { info = await this._hass.callWS({ type: "argus/job" }); } catch (e) { this._poll = null; return; }
      const was = this.state.job && this.state.job.running;
      this.state.job = info.job; this.state.data && Object.assign(this.state.data, { paused: info.paused, schedule: info.schedule, last: info.last });
      this.renderJob();
      if (info.job && info.job.running) { if (info.job.done && info.job.done % 10 === 0 && info.job.done !== this._lastReload) { this._lastReload = info.job.done; this.load(); } this._poll = setTimeout(tick, 2000); return; }
      this._poll = null;
      if (was && info.last) {
        const l = info.last, parts = [l.updated && t("{n} updated", { n: l.updated }), l.found && t("{n} links found", { n: l.found }), l.skipped && t("{n} skipped (paused)", { n: l.skipped }), l.errors && t("{n} errors", { n: l.errors })].filter(Boolean).join(", ");
        this.toast(`${l.cancelled ? t("{job} stopped", { job: tx(l.label || "Job") }) : t("{job} done", { job: tx(l.label || "Job") })}${parts ? ": " + parts : ""}`, l.errors && !l.updated && !l.found ? "err" : "ok");
        this.load();
      }
    };
    this._poll = setTimeout(tick, 1200);
  }
  /** Sets just added get their first prices in the background: look every few seconds and show them when they are in. */
  /** Sets just added get their first prices in the background: look every few seconds and show them when they are in. */
  followFirstChecks() {
    if (this._fcPoll) return;
    let left = (this.state.data && this.state.data.first_checks) || [], tries = 0;
    const tick = async () => {                            // _fcPoll stays set while a tick runs: load() below starts no second loop
      if (!this.isConnected) { this._fcPoll = null; return; }
      let info; try { info = await this._hass.callWS({ type: "argus/job" }); } catch (e) { this._fcPoll = null; return; }
      const now = info.first_checks || [], done = left.filter((n) => !now.includes(n));
      const dlg = this.shadowRoot.getElementById("dlg"), typing = this.shadowRoot.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(this.shadowRoot.activeElement.tagName);
      if (done.length && !typing) {
        left = now;
        await this.load();
        if (dlg && dlg.open && done.includes(this._dlgNum)) this.openSet(this._dlgNum);
      } else if (!done.length) left = now;                 // also follow sets added in the meantime
      this._fcPoll = (left.length || done.length) && ++tries < 100 ? setTimeout(tick, 3000) : null;
    };
    this._fcPoll = setTimeout(tick, 3000);
  }
  renderJob() {
    const box = this.shadowRoot.getElementById("jobbar"); if (!box) return;
    const j = this.state.job;
    const d = this.state.data;
    this.shadowRoot.querySelectorAll("[data-act]").forEach((b) => { b.disabled = !!(j && j.running) || (b.dataset.act === "refresh" && !!d && !d.full_refresh); });
    if (!j || !j.running) { box.innerHTML = ""; return; }
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    const el = (j.started && j.done) ? (Date.now() / 1000 - j.started) / j.done * (j.total - j.done) : null;
    const fresh = !box.querySelector(".jobbar");
    box.innerHTML = `<div class="jobbar${fresh ? " in" : ""}"><span class="spin"></span><div style="flex:1;min-width:0"><div class="jt"><b>${esc(tx(j.label))}</b> · ${j.done}/${j.total}${el ? ` · ${t("± {time} left", { time: dur(el) })}` : ""}${j.found ? ` · ${t("{n} found", { n: j.found })}` : ""}${j.updated ? ` · ${t("{n} updated", { n: j.updated })}` : ""}${j.errors ? ` · ${t("{n} errors", { n: j.errors })}` : ""}</div>
      <div class="meter" style="margin:6px 0 3px"><i style="width:${pct}%;animation:none;transition:width .6s"></i></div><div class="muted jt">${esc(tx(j.current || ""))}${j.note ? ` · ${esc(tx(j.note))}` : ""}</div></div><button class="btn ghost sm" id="jobstop">${t("Stop")}</button></div>`;
    box.querySelector("#jobstop").onclick = async () => { await this.svc("cancel_job", {}, true); this.toast(t("The job stops after the current product")); };
  }
  placeIndicator(anim) {
    const seg = this.shadowRoot.querySelector(".seg"); if (!seg) return;
    const on = seg.querySelector("button.on"), ind = seg.querySelector(".ind");
    if (!anim) ind.style.transition = "none";
    ind.style.left = on.offsetLeft + "px"; ind.style.width = on.offsetWidth + "px";
    if (!anim) requestAnimationFrame(() => { ind.style.transition = ""; });
  }
  resetFilters() { Object.assign(this.state.f, { category: null, q: "", shop: null, price: null, status: null }); this.state.f.sort = "score"; }
  subCount(sec, sub) {
    const d = this.state.data; if (!d) return "";
    let n = 0;
    if (sec === "prices" && sub === "today") n = d.products.filter((s) => this.isDeal(s)).length;
    if (sec === "prices" && sub === "all") n = d.products.length;
    if (sec === "manage" && sub === "shops") n = Object.keys(d.paused || {}).length;
    if (sec === "log" && sub === "errors") n = this.errorRows().length;
    if (sec === "manage" && sub === "links") n = d.products.reduce((a, s) => a + (s.offers_suspect || 0), 0);
    return n ? `<span class="count">${n}</span>` : "";
  }
  healthDot() {
    const h = this.state.data.health || {}; const paused = Object.keys(h.paused_hours || {}).length;
    const cls = paused ? "bad" : h.errors ? "warn" : "";
    const txt = paused ? t(paused > 1 ? "{n} shops paused" : "{n} shop paused", { n: paused }) : h.errors ? t(h.errors > 1 ? "{n} errors" : "{n} error", { n: h.errors }) : t("all shops OK");
    return `<span class="pill" title="${esc(this.state.data.transport)}" style="cursor:pointer" data-goto="manage/shops"><span class="dotst ${cls}"></span>${txt}</span>`;
  }
  renderContent(animate = false) {
    const s = this.state, el = this.shadowRoot.getElementById("content"); if (!el) return;
    if (s.err) { el.innerHTML = `<div class="empty"><span class="big">⚠️</span>${t("Could not load data: {error}", { error: esc(s.err) })}<br><br><button class="btn" id="retry">${t("Try again")}</button></div>`; el.querySelector("#retry").onclick = () => this.load(true); return; }
    if (!s.data) { el.innerHTML = `<div class="kpis">${"<div class='skel' style='height:86px'></div>".repeat(4)}</div><div class="grid">${"<div class='skel' style='height:260px'></div>".repeat(8)}</div>`; return; }
    const view = { prices: { today: this.vToday, all: this.vAll, dset: this.vDealSettings }, overview: { cost: this.vCost, shops: this.vShopsOverview }, log: { all: this.vLog, checks: this.vLog, errors: this.vErrors }, manage: { notify: this.vNotify, add: this.vAdd, import: this.vImport, links: this.vLinks, shops: this.vShops, lab: this.vLab, settings: this.vSettings, userscript: this.vUserscript, backup: this.vBackup, legal: this.vLegal, about: this.vAbout, secret: this.vSecret } }[s.section][s.sub[s.section]];
    el.className = animate && !REDUCED ? "enter" : "";
    el.innerHTML = view.call(this);
    this.bindContent(el);
    clearTimeout(this._shopsTimer);
    if (s.section === "manage" && s.sub.manage === "shops") {        // the shop status keeps itself up to date
      this._shopsTimer = setTimeout(() => { const d = this.shadowRoot.getElementById("dlg"); if (this.isConnected && s.section === "manage" && s.sub.manage === "shops" && !(d && d.open)) this.load(); else if (this.isConnected) this.renderContent(); }, 30000);
    }
    this.hookCharts(el); this.tickManual();
    if (animate) this.countUp(el);
  }
  // only the results area (keeps focus in the search box while typing)
  // only the results area (keeps focus in the search box while typing)
  renderResults() {
    const el = this.shadowRoot.getElementById("results"); if (!el) return this.renderContent();
    const fn = el.dataset.fn; el.innerHTML = this[fn](); el.className = ""; this.bindCards(el); this.hookCharts(el);
  }

  // ---------------------------------------------------------------- shared pieces
  // ---------------------------------------------------------------- shared pieces
  kpi(label, value, { fmt = "int", sub = "", color = "", icon = "" } = {}) {
    const shown = fmt === "eur" ? EUR0(value) : fmt === "pct" ? signPct(value) : fmt === "dec" ? (value == null ? "–" : value.toLocaleString(LOC, { maximumFractionDigits: 1 })) : INT(value);
    return `<div class="kpi${color ? " hl" : ""}" style="${color ? `--c:${color}` : ""}"><small>${icon} ${label}</small><b data-to="${value ?? ""}" data-fmt="${fmt}">${shown}</b>${sub ? `<div class="sub2">${sub}</div>` : ""}</div>`;
  }
  countUp(root) {
    if (REDUCED) return;
    root.querySelectorAll("[data-to]").forEach((el) => {
      const to = parseFloat(el.dataset.to); if (isNaN(to) || to === 0) return;
      const fmt = el.dataset.fmt, t0 = performance.now(), ms = 700;
      const f = fmt === "eur" ? EUR0 : fmt === "pct" ? signPct : fmt === "dec" ? (v) => v.toLocaleString(LOC, { maximumFractionDigits: 1 }) : INT;
      const step = (now) => { const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3); el.textContent = f(fmt === "pct" || fmt === "dec" ? Math.round(to * e * 10) / 10 : to * e); if (p < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  }
  /** The conditions of your copies of a set (every copy counts; "Unknown" when none is known). */
  /** Extra filters as drop-downs (shop, price, status, year, location): only choices that occur in the list, with counts. */
  emptyState(icon, text, action = "") { return `<div class="empty"><span class="big">${icon}</span>${text}${action ? `<br><br>${action}` : ""}</div>`; }
  banner() {
    const h = this.state.data.health; if (!h || !h.errors) return "";
    const paused = Object.entries(h.paused_hours || {}).map(([k, v]) => `${esc(k)} (${dur(v * 3600)})`).join(", ");
    return `<div class="banner">⚠️ <span>${t(h.errors === 1 ? "{n} shop price could not be fetched" : "{n} shop prices could not be fetched", { n: h.errors })}${paused ? `; ${t("paused after a block: {shops}", { shops: paused })}` : ""}. <a data-goto="log/errors">${t("Show errors")}</a> · <a data-goto="manage/shops">${t("Shop status")}</a></span></div>`;
  }

  // ---------------------------------------------------------------- DEALS
  // ---------------------------------------------------------------- errors tab
  // ---------------------------------------------------------------- DEALS
  // ---------------------------------------------------------------- errors tab
  errType(o) {
    const e = (o.error || "").toLowerCase();
    if (o.link_status === "suspect") return ["suspect", t("Suspicious link")];
    if (e.startsWith("paused")) return ["paused", t("Shop paused")];
    if (e.includes("blocked")) return ["blocked", t("Blocked by the shop")];
    if (e.includes("suspicious price")) return ["price", t("Suspicious price")];
    if (e.includes("price not found")) return ["noprice", t("Price not found")];
    if (e.includes("404") || e.includes("not found")) return ["gone", t("Page no longer exists")];
    return ["other", t("Other error")];
  }
  errorRows() {
    const out = [], E = this.state.errs;
    for (const s of this.products) {
      const offers = Object.entries(s.offers || {});
      if (!offers.length) out.push({ s, rid: null, o: null, type: "nolinks", label: t("No shop link at all"), msg: t("No shop is linked to this product yet.") });
      for (const [rid, o] of offers) {
        if (!(o.error || o.link_status === "suspect")) continue;
        if (o.ignored && !E.showIgnored) continue;
        const [type, label] = this.errType(o);
        out.push({ s, rid, o, type, label, msg: tx(o.link_status === "suspect" ? o.link_reason : o.error) });
      }
    }
    return out;
  }
  vErrors() {
    const E = this.state.errs, all = this.errorRows(), retailers = this.state.data.retailers;
    const types = {}; all.forEach((r) => { types[r.type] = types[r.type] || [r.label, 0]; types[r.type][1]++; });
    let rows = all.filter((r) => (E.type === "all" || r.type === E.type) && (!E.shop || r.rid === E.shop));
    rows.sort((a, b) => (a.s.name || a.s.id).localeCompare(b.s.name || b.s.id));
    const trs = rows.slice(0, 300).map((r) => {
      const key = `${r.s.id}|${r.rid || ""}`, open = E.open === key;
      const head = `<tr class="click erow${open ? " on" : ""}" data-ekey="${esc(key)}"><td style="width:28px">${open ? "▾" : "▸"}</td><td><a class="setlink" data-set="${esc(r.s.id)}"><b>${esc(r.s.name || r.s.id)}</b></a><div class="muted" style="font-size:12px">${esc(this.catName(r.s.category))}</div></td>
        <td>${r.rid ? esc(retailers[r.rid] || r.rid) : "–"}</td><td><span class="lk ${r.type === "suspect" || r.type === "price" ? "suspect" : "unknown"}">${esc(r.label)}</span>${r.o && r.o.ignored ? ` <span class="muted" style="font-size:11px">(${t("ignored")})</span>` : ""}<div class="err" style="font-size:12px;margin-top:2px">${esc(r.msg || "")}</div>${r.o && r.o.suspect ? `<div style="margin-top:4px">${approveBtn(r.s.id, r.rid, r.o.suspect.price)}</div>` : ""}${r.o && r.o.link_status === "suspect" ? `<div style="margin-top:4px">${doubtBtns(r.s.id, r.rid)}</div>` : ""}</td>
        <td class="num">${r.o && r.o.price != null ? EUR(r.o.price) : "–"}</td></tr>`;
      if (!open) return head;
      return head + `<tr class="efix"><td colspan="5">${this.itemEditorHtml(r.s, r.rid)}</td></tr>`;
    }).join("");
    const chip = (k, l, n) => `<span class="chip ${E.type === k ? "on" : ""}" data-etype="${k}">${esc(l)}${n != null ? ` <span class="muted">${n}</span>` : ""}</span>`;
    return `${this.errorStatsHtml()}<div class="panel"><h3>⚠️ ${t("Open errors")} <span class="muted" style="font-weight:400">${all.length}</span><span class="hsp"></span><label class="chk" style="font-size:13px;font-weight:400;display:flex;gap:6px;align-items:center"><input type="checkbox" id="e_ign" ${E.showIgnored ? "checked" : ""}> ${t("show ignored")}</label></h3>
      <p>${t("Click an error to fix it right away: enter the correct product page and/or the price. Anything you enter by hand wins over automatic values.")} ${t("Does a shop keep blocking? See the alternatives under {link}.", { link: `<a data-goto="manage/shops" style="cursor:pointer">${t("Shops & jobs")}</a>` })}</p>
      <div class="chips">${chip("all", t("All"), all.length)}${Object.entries(types).map(([k, [l, n]]) => chip(k, l, n)).join("")}</div>
      <div class="fbar"><select id="e_shop"><option value="">${t("All shops")}</option>${Object.entries(retailers).map(([k, v]) => `<option value="${k}" ${E.shop === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div></div>
      ${rows.length ? `<div class="panel tscroll"><table class="tbl"><tr><th></th><th>${t("Product")}</th><th>${t("Shop")}</th><th>${t("Error")}</th><th class="num">${t("Last price")}</th></tr>${trs}</table>${rows.length > 300 ? `<p class="muted">${t("First {n} of {total}.", { n: 300, total: rows.length })}</p>` : ""}</div>` : this.emptyState("✅", t("No errors in this selection."))}`;
  }
  // ---------------------------------------------------------------- logbook
  // ---------------------------------------------------------------- logbook
  logQuery() {
    const L = this.state.logv, checks = this.state.sub.log === "checks";
    return { type: "argus/log", level: L.level, kind: checks ? "check" : L.kind, retailer: L.retailer, source: L.source, status: L.status, product: L.product, q: L.q, limit: 100 };
  }
  async loadLog(more = false) {
    const L = this.state.logv, q = this.logQuery();
    if (more && L.data && L.data.entries.length) q.before = L.data.entries[L.data.entries.length - 1].ts;
    try { const r = await this._hass.callWS(q); if (more) { r.entries = L.data.entries.concat(r.entries); } L.data = r; L.err = null; } catch (e) { L.err = e.message; }
    if (this.state.section === "log" && this.state.sub.log !== "errors") this.renderLogList();
  }
  renderLogList() {
    const el = this.shadowRoot.getElementById("loglist"); if (!el) return this.renderContent();
    el.innerHTML = this.logListHtml(); this.bindLogList(el);
  }
  scheduleLine() {
    const sc = (this.state.data.schedule || {}), set = sc.next_product && this.products.find((x) => x.id === sc.next_product);
    if (sc.mode === "spread") {
      return `${t("Spread checks: every product once every {h} h, about {n} products per hour.", { h: (sc.cycle_hours ?? 24).toLocaleString(LOC), n: (sc.per_hour ?? 0).toLocaleString(LOC, { maximumFractionDigits: 1 }) })} ${sc.next ? t("Next check {time}", { time: TIME(sc.next) }) + (set ? `: <a data-set="${esc(set.id)}" class="setlink">${esc(set.name || set.id)}</a>` : "") + "." : ""}`;
    }
    if (sc.mode === "times") return t("Automatic refresh at {times}.", { times: (sc.times || []).join(", ") });
    return t("Automatic checks are off.");
  }
  vLog() {
    const L = this.state.logv, checks = this.state.sub.log === "checks", sc = this.state.data.schedule || {};
    if (!L.data && !L.err) this.loadLog();
    const d = L.data, f = d ? d.facets : { kind: {}, retailer: {}, source: {} }, kinds = d ? d.kinds : {};
    const srcLabel = { server: "Server", schedule: "Schedule (automatic)", panel: "Panel (you)", userscript: "Tampermonkey userscript", relay: "Your browser (relay)", import: "Import", added: "Just added (first check)", update: "Search and price update", rediscover: "Searched again after a blocked link" };
    const opt = (list, cur, all) => `<option value="">${all}</option>` + list.map(([v, l, n]) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(l)}${n != null ? ` (${n})` : ""}</option>`).join("");
    const st = (v, l, cls) => `<span class="chip ${L.status === v ? "on" : ""} ${cls}" data-lstat="${v}">${l}</span>`;
    const errs = this.errorRows().length;
    const kpis = `<div class="kpis">${this.kpi(t("Checked in the last 24 h"), sc.checked_24h ?? null, { icon: "🔄", sub: sc.total != null ? t("of {n} products with shop links", { n: sc.total }) : "" })}${this.kpi(t("Pace"), sc.mode === "spread" ? sc.per_hour ?? null : null, { fmt: "dec", icon: "⏱️", sub: sc.mode === "spread" ? t("products per hour") : t("spread checks are off") })}${this.kpi(t("Open errors"), errs, { icon: "⚠️", color: errs ? "var(--ar-red)" : "var(--ar-green)", sub: `<a data-goto="log/errors" style="cursor:pointer">${t("Show and fix")} →</a>` })}</div>`;
    const filtered = L.level || (!checks && L.kind) || L.retailer || L.source || L.status || L.product || L.q;
    return `${kpis}${this.exportPanel()}<div class="panel"><h3>${checks ? "🔄 " + t("Shop checks") : "📜 " + t("Logbook")}<span class="hsp"></span><button class="btn ghost sm" id="lg_reload">↻ ${t("Refresh")}</button></h3>
      <p>${checks ? t("One line per product check with a result per shop: green = price fetched, red = failed, grey = skipped (shop paused).") : t("Everything the integration does: price changes, shop checks (what works and what doesn't), links found or rejected, prices from Tampermonkey, imports, jobs, notifications and your own actions. Identical repeated messages are merged (×count). Click a line for details and to fix it.")} <span class="muted">${this.scheduleLine()}</span></p>
      <div class="chips">${st("", t("All"), "")}${st("ok", "✓ " + t("Succeeded"), "okc")}${st("fail", "✕ " + t("Failed"), "failc")}${st("suspect", "⚠ " + t("Suspicious prices"), "failc")}</div>
        <div class="muted" style="font-size:12px;margin-top:4px">${t("How a price was read")}: ⌂ ${t("shop site (direct)")} · ⓤ ${t("userscript (your browser)")} </div>
      <div class="fbar"><select id="lg_level" aria-label="${t("Level")}">${opt([["problems", "⚠️ " + t("Errors & warnings")], ["events", "✅ " + t("Events")], ["error", "⛔ " + t("Errors only")]], L.level, t("All levels"))}</select>
      ${checks ? "" : `<select id="lg_kind" aria-label="${t("Kind")}">${opt(Object.entries(kinds).map(([k, l]) => [k, t(l), f.kind[k] || 0]), L.kind, t("All kinds"))}</select>`}
      <select id="lg_shop" aria-label="${t("Shop")}">${opt(Object.entries(this.state.data.retailers).map(([k, l]) => [k, l, f.retailer[k] || 0]), L.retailer, t("All shops"))}</select>
      <select id="lg_src" aria-label="${t("Source")}">${opt(Object.keys(f.source).map((k) => [k, srcLabel[k] ? t(srcLabel[k]) : srcName(k), f.source[k]]), L.source, t("All sources"))}</select>
      <select id="lg_set" aria-label="${t("Product")}"><option value="">${t("All products")}</option>${this.products.slice().sort((a, b) => (a.name || "").localeCompare(b.name || "")).map((s) => `<option value="${esc(s.id)}" ${L.product === s.id ? "selected" : ""}>${esc((s.name || s.id).slice(0, 50))}</option>`).join("")}</select>
      <div class="search" style="min-width:180px"><input id="lg_q" placeholder="${t("Search message or link…")}" value="${esc(L.q)}"></div>
      ${filtered ? `<button class="btn ghost sm" id="lg_clear">✕ ${t("Clear filters")}</button>` : ""}</div></div>
      <div id="loglist">${this.logListHtml()}</div>`;
  }
  shopResults(e, full = false) {
    const retailers = this.state.data.retailers;
    return Object.entries(e.results || {}).map(([rid, r]) => {
      const un = r.unavailable ? unavailableText(r.unavailable) : "";
      const cls = un ? "warn" : r.ok ? "ok" : r.ok === false ? "fail" : "skip", name = esc(retailers[rid] || rid);
      const how = r.ok === undefined || r.ok === null ? "" : viaMark(r.via || (e.source === "relay" || e.source === "userscript" ? e.source : ""));
      const val = un ? `⚠ ${esc(un)}` : r.ok ? `${r.price != null ? EUR(r.price) : "✓"}${r.manual ? " ✎" : ""}` : r.ok === false ? "✕" : "⏸";
      const why = un ? t("No price because the shop says: {reason}. A warning, nothing to fix.", { reason: un }) : r.error ? tx(r.error) : r.manual ? t("manual price wins; the shop said {price}", { price: EUR(r.price) }) : viaTitle(r.via);
      return full ? `<div class="res ${cls}" style="display:flex;gap:8px;align-items:center;margin:3px 0">${how}<b style="min-width:110px">${name}</b><span>${val}</span><span class="muted" style="font-size:12px">${esc(why)}</span></div>`
        : `<span class="res ${cls}" title="${esc(why)}">${how} ${name} <b>${val}</b></span>`;
    }).join(full ? "" : " ");
  }
  logListHtml() {
    const L = this.state.logv;
    if (L.err) return this.emptyState("⚠️", esc(L.err));
    if (!L.data) return `<div class="skel" style="height:200px"></div>`;
    const d = L.data, retailers = this.state.data.retailers;
    if (!d.entries.length) return this.emptyState("📭", t("No log lines with these filters."));
    const icon = { error: "⛔", warning: "⚠️", ok: "✅", info: "ℹ️" };
    const rows = d.entries.map((e) => {
      const s = e.product ? this.products.find((x) => x.id === e.product) : null, open = L.open === e.id;
      const setCell = e.product ? `<a class="setlink" data-set="${esc(e.product)}" title="${t("Open product")}"><b>${esc(e.product)}</b> <span class="muted">${esc(s ? (s.name || "") : "")}</span></a>` : "";
      const pend = s ? Object.entries(s.offers || {}).filter(([r, o]) => o.suspect && (e.retailer ? r === e.retailer : !!(e.results && e.results[r] && /suspicious price/i.test(e.results[r].error || "")))) : [];
      const how = e.kind === "userscript" || e.source === "relay" || e.source === "userscript" ? viaMark("userscript") + " " : "";
      const msg = (e.kind === "check" && e.results ? `<div class="resrow">${this.shopResults(e)}</div>` : `${how}${esc(tx(e.message))}`)
        + pend.map(([r, o]) => ` ${approveBtn(e.product, r, o.suspect.price)}`).join("")
        + (s && e.kind === "link" && e.retailer && (s.offers || {})[e.retailer] && s.offers[e.retailer].link_status === "suspect" && e.url === s.offers[e.retailer].url
          ? `<div style="margin-top:4px">${doubtBtns(e.product, e.retailer)}</div>` : "")
        + (s && e.choice && e.retailer && ((s.offers || {})[e.retailer] || {}).price_choice && s.offers[e.retailer].price_choice.price === e.price
          ? `<div style="margin-top:4px">${choiceBtns(e.product, e.retailer, s.offers[e.retailer].price_choice)}</div>` : "");
      const head = `<tr class="click lrow lv-${esc(e.level)}${open ? " on" : ""}" data-lid="${esc(e.id)}"><td style="white-space:nowrap" class="muted">${DATE(e.ts, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
        <td>${icon[e.level] || ""}</td><td><span class="tag">${esc(t(d.kinds[e.kind] || e.kind))}</span></td>
        <td>${setCell}</td><td>${e.retailer ? esc(retailers[e.retailer] || e.retailer) : ""}</td>
        <td class="${e.level === "error" ? "err" : ""}">${msg}${e.count > 1 ? ` <span class="tag">×${e.count}</span>` : ""}</td></tr>`;
      if (!open) return head;
      const det = `<div class="kv"><span>${t("Time")}</span><b>${DATE(e.ts, { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b></div>
        <div class="kv"><span>${t("Message")}</span><b>${esc(tx(e.message))}</b></div>
        <div class="kv"><span>${t("Source")}</span><b>${esc(srcName(e.source))}</b></div>${e.url ? `<div class="kv"><span>${t("Link")}</span><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url.slice(0, 80))} ↗</a></div>` : ""}
        ${e.price != null ? `<div class="kv"><span>${t("Price")}</span><b>${e.old_price != null ? EUR(e.old_price) + " → " : ""}${EUR(e.price)}</b></div>` : ""}
        ${e.results ? `<h4 style="margin:10px 0 4px">${t("Result per shop")}</h4>${this.shopResults(e, true)}` : ""}
        ${Array.isArray(e.details) && e.details.length ? `<h4 style="margin:10px 0 4px">🧠 ${t("Analysis")}</h4><ul style="margin:0;padding-left:18px">${e.details.map((d) => `<li>${esc(tx(d))}</li>`).join("")}</ul>` : ""}`;
      const failed = e.results ? Object.entries(e.results).find(([, r]) => r.ok === false) : null;
      const rid = e.retailer || (failed ? failed[0] : null);
      const fixable = s && rid && (e.level === "error" || e.level === "warning") && ["fetch", "link", "userscript", "discover", "price", "check"].includes(e.kind);
      const fix = s ? `<h4 style="margin:10px 0 6px">${fixable ? t("Fix it") : t("Product and shops")}</h4>${this.itemEditorHtml(s, rid)}` : "";
      return head + `<tr><td colspan="6"><div class="fixbox" style="background:var(--ar-card);border:1px solid var(--ar-line)">${det}${fix}</div></td></tr>`;
    }).join("");
    return `<div class="panel tscroll"><div class="muted" style="font-size:12px;margin-bottom:6px">${t(d.total === 1 ? "{n} line" : "{n} lines", { n: d.total })}</div><table class="tbl log"><tr><th>${t("Time")}</th><th></th><th>${t("Kind")}</th><th>${t("Product")}</th><th>${t("Shop")}</th><th>${t("Message")}</th></tr>${rows}</table>
      ${d.more ? `<div style="text-align:center;margin-top:10px"><button class="btn ghost" id="lg_more">${t("Load more")}</button></div>` : ""}</div>`;
  }
  bindLogList(el) {
    const L = this.state.logv;
    el.querySelectorAll("tr.lrow").forEach((tr) => tr.addEventListener("click", (e) => { if (e.target.closest("[data-product],a")) return; L.open = L.open === tr.dataset.lid ? null : tr.dataset.lid; this.renderLogList(); }));
    el.querySelectorAll(".item[data-inum]").forEach((b) => this.bindItemEditor(b, () => this.loadLog()));
    this.bindCards(el);
    const more = el.querySelector("#lg_more"); if (more) more.onclick = () => this.busy(more, "…", () => this.loadLog(true));
  }
  /** Logbook → Export: shop checks, price history per set and in total, as CSV with filters. */
  /** Logbook → Export: shop checks, price history per set and in total, as CSV with filters. */
  exportPanel() {
    const x = this.state.exp || (this.state.exp = { open: false, parts: ["checks"] }), items = this.products, has = (p) => x.parts.includes(p);
    const opt = (v, l, sel) => `<option value="${esc(v)}" ${sel ? "selected" : ""}>${esc(l)}</option>`;
    const setOpts = `<option value="">${t("All products")}</option>${items.slice().sort((a, b) => (a.name || "").localeCompare(b.name || "")).map((s) => opt(s.id, (s.name || s.id).slice(0, 60))).join("")}`;
    const shops = Object.entries(this.state.data.retailers).map(([k, v]) => opt(k, v)).join("");
    const cats = Object.entries(this.state.data.categories).map(([k, v]) => opt(k, t(v))).join("");
    const day = (d) => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10);
    return `<details class="panel" id="exp" ${x.open ? "open" : ""}><summary style="cursor:pointer"><b>⬇ ${t("Export (CSV)")}</b> <span class="muted" style="font-size:13px">${t("shop checks and price history, with filters")}</span></summary>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin:12px 0">
        <label class="chk" title="${t("Every check of every shop: when, product, shop, result, price and error")}"><input type="checkbox" class="xp" value="checks" ${has("checks") ? "checked" : ""}> 🔄 ${t("Shop checks")} ⓘ</label>
        <label class="chk" title="${t("Every recorded price per product and per shop")}"><input type="checkbox" class="xp" value="history" ${has("history") ? "checked" : ""}> 📈 ${t("Price history per product")} ⓘ</label>
        <label class="chk" title="${t("Per day: the sum of the lowest price of the chosen products (last known price carried forward), e.g. what everything would cost")}"><input type="checkbox" class="xp" value="total" ${has("total") ? "checked" : ""}> Σ ${t("Price history in total")} ⓘ</label>
        <label class="chk" title="${t("Every 'Problem with this product' report: links, prices, errors and your remark")}"><input type="checkbox" class="xp" value="reports" ${has("reports") ? "checked" : ""}> ⚠ ${t("Problem reports")} ⓘ</label></div>
      <div class="form"><label>${t("From")}<input type="date" id="xp_from" value="${day(30)}"></label><label>${t("To")}<input type="date" id="xp_to" value="${day(0)}"></label>
        <label>${t("Product")}<select id="xp_set">${setOpts}</select></label></div>
      <div class="form" id="xp_checks" ${has("checks") ? "" : "hidden"}><label>${t("Shop")}<select id="xp_shop"><option value="">${t("All shops")}</option>${shops}</select></label>
        <label title="${t("Skipped = not asked, e.g. because the shop was paused after a block")}">${t("Result")} ⓘ<select id="xp_status"><option value="">${t("All")}</option><option value="ok">${t("succeeded")}</option><option value="failed">${t("failed")}</option><option value="skipped">${t("skipped")}</option></select></label></div>
      <div class="form" id="xp_hist" ${has("history") || has("total") ? "" : "hidden"}>
        <label>${t("Category")}<select id="xp_cat"><option value="">${t("All categories")}</option>${cats}</select></label>
        <label>${t("Priority")}<select id="xp_prio"><option value="">–</option><option value="1">★</option><option value="2">★★</option><option value="3">★★★</option></select></label></div>
      <button class="btn" id="xp_go">⬇ ${t("Download CSV")}</button> <span class="muted" id="xp_res" style="font-size:13px"></span></details>`;
  }
  bindExport(root, $) {
    const x = this.state.exp, box = $("exp"); if (!box) return;
    box.addEventListener("toggle", () => { x.open = box.open; });
    const parts = () => [...root.querySelectorAll(".xp")].filter((c) => c.checked).map((c) => c.value);
    root.querySelectorAll(".xp").forEach((c) => c.addEventListener("change", () => { x.parts = parts(); $("xp_checks").hidden = !x.parts.includes("checks"); $("xp_hist").hidden = !(x.parts.includes("history") || x.parts.includes("total")); }));
    $("xp_go").onclick = () => this.busy($("xp_go"), "…", async () => {
      const p = parts(); if (!p.length) { this.toast(t("Choose at least one part to export."), "err"); return; }
      const ts = (id, endOfDay) => { const v = $(id).value; return v ? new Date(v + (endOfDay ? "T23:59:59" : "T00:00:00")).getTime() / 1000 : undefined; };
      const f = { products: $("xp_set").value ? [$("xp_set").value] : [], shops: $("xp_shop").value ? [$("xp_shop").value] : [], status: $("xp_status").value || undefined,
        category: $("xp_cat").value || undefined, priority: +$("xp_prio").value || undefined };
      const r = await this._hass.callWS({ type: "argus/logs/export", parts: p, start: ts("xp_from"), end: ts("xp_to", true), filters: f });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["\ufeff" + r.csv], { type: "text/csv;charset=utf-8" }));
      a.download = `argus-logbook-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      $("xp_res").textContent = Object.entries(r.counts).map(([k, n]) => `${t({ checks: "Shop checks", history: "Price history per product", total: "Price history in total", reports: "Problem reports" }[k])}: ${n}`).join(" · ");
    });
  }
  bindLog(root, $) {
    this.bindExport(root, $);
    const L = this.state.logv;
    const refilter = () => { L.open = null; this.loadLog(); };
    for (const [id, key] of [["lg_level", "level"], ["lg_kind", "kind"], ["lg_shop", "retailer"], ["lg_src", "source"]]) if ($(id)) $(id).addEventListener("change", (e) => { L[key] = e.target.value; refilter(); });
    root.querySelectorAll("[data-lstat]").forEach((c) => c.addEventListener("click", () => { L.status = c.dataset.lstat; root.querySelectorAll("[data-lstat]").forEach((x) => x.classList.toggle("on", x === c)); refilter(); }));
    let tm; const typed = (key) => (e) => { L[key] = e.target.value; clearTimeout(tm); tm = setTimeout(refilter, 350); };
    $("lg_set").addEventListener("change", (e) => { L.product = e.target.value; refilter(); }); $("lg_q").addEventListener("input", typed("q"));
    $("lg_reload").onclick = () => this.busy($("lg_reload"), "…", async () => { await this.load(); await this.loadLog(); });
    if ($("lg_clear")) $("lg_clear").onclick = () => { Object.assign(L, { level: "", kind: "", retailer: "", source: "", status: "", product: "", q: "", data: null }); this.renderContent(); };
    const list = this.shadowRoot.getElementById("loglist"); if (list) this.bindLogList(list);
  }
  /** Filter the logbook on one set and jump there (used from the set dialog). */
  /** Filter the logbook on one set and jump there (used from the set dialog). */
  showLogFor(num) {
    Object.assign(this.state.logv, { level: "", kind: "", retailer: "", source: "", status: "", product: num, q: "", data: null, open: null });
    this.state.section = "log"; this.state.sub.log = "all"; this.persist(); this.closeDialog(); this.render(true);
  }
  /** Logbook → Open errors: how many were solved and how many came in (today, 7 and 30 days), charts per
   * day / week / month, and the latest solved or new errors (click to open the set). */
  /** Logbook → Open errors: how many were solved and how many came in (today, 7 and 30 days), charts per
   * day / week / month, and the latest solved or new errors (click to open the set). */
  /** Logbook → Open errors: how many were solved and how many came in (today, 7 and 30 days), charts per
   * day / week / month, and the latest solved or new errors (click to open the set). */
  /** Logbook → Open errors: how many were solved and how many came in (today, 7 and 30 days), charts per
   * day / week / month, and the latest solved or new errors (click to open the set). */
  errorStatsHtml() {
    const S = this.state.estats;
    if (!S || Date.now() - S.at > 60000) {
      if (!this._esLoading) {
        this._esLoading = true;
        this._hass.callWS({ type: "argus/error_stats" }).then((r) => { this.state.estats = { ...r, at: Date.now() }; })
          .catch((e) => { this.state.estats = { days: {}, solved: [], new: [], err: e.message, at: Date.now() }; })
          .finally(() => { this._esLoading = false; if (this.state.section === "log" && this.state.sub.log === "errors") this.renderContent(); });
      }
      if (!S) return `<div class="panel"><div class="skel" style="height:160px"></div></div>`;
    }
    const E = this.state.errs, per = E.per || "day", days = S.days || {};
    const iso = (d) => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); };
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const sum = (from) => { let a = 0, b = 0; for (const [k, v] of Object.entries(days)) if (k >= from) { a += v.solved || 0; b += v.new || 0; } return [a, b]; };
    const back = (n) => { const d = new Date(today); d.setDate(d.getDate() - n); return iso(d); };
    const [s0, n0] = sum(iso(today)), [s7, n7] = sum(back(6)), [s30, n30] = sum(back(29));
    const rows = [];
    if (per === "day") for (let i = 29; i >= 0; i--) { const k = back(i), v = days[k] || {}; rows.push({ label: DATE(new Date(k + "T12:00").getTime() / 1000, { day: "numeric", month: "numeric" }), a: v.solved || 0, b: v.new || 0 }); }
    else if (per === "week") for (let i = 11; i >= 0; i--) {
      const start = new Date(today); start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 7 * i); const end = new Date(start); end.setDate(end.getDate() + 6);
      let a = 0, b = 0; for (const [k, v] of Object.entries(days)) if (k >= iso(start) && k <= iso(end)) { a += v.solved || 0; b += v.new || 0; }
      rows.push({ label: DATE(start.getTime() / 1000, { day: "numeric", month: "numeric" }), a, b });
    } else for (let i = 11; i >= 0; i--) {
      const m = new Date(today.getFullYear(), today.getMonth() - i, 1), key = iso(m).slice(0, 7);
      let a = 0, b = 0; for (const [k, v] of Object.entries(days)) if (k.startsWith(key)) { a += v.solved || 0; b += v.new || 0; }
      rows.push({ label: DATE(m.getTime() / 1000, { month: "short" }), a, b });
    }
    const kpi = (label, a, b, k) => `<button class="kpi click" type="button" data-elist="${k}" style="text-align:left;border:0;font:inherit;color:inherit;cursor:pointer${E.list === k ? ";outline:2px solid var(--ar-accent)" : ""}"><div class="muted" style="font-size:12px">${esc(label)}</div>
      <b style="color:var(--ar-green)">✓ ${a}</b> <span class="muted">${esc(t("solved"))}</span><br><b style="color:var(--ar-red)">＋ ${b}</b> <span class="muted">${esc(t("new"))}</span></button>`;
    const chip = (k, l) => `<span class="chip ${per === k ? "on" : ""}" data-eper="${k}">${esc(l)}</span>`;
    const list = E.list ? (E.list === "new" ? S.new : S.solved) : null;
    const listHtml = list ? `<div class="tscroll" style="margin-top:10px"><table class="tbl"><tr><th>${t("When")}</th><th>${t("Product")}</th><th>${t("Shop")}</th><th>${E.list === "new" ? t("Error") : t("Was open")}</th></tr>
      ${list.slice(0, 100).map((x) => `<tr class="click" data-set="${esc(x.product)}"><td>${esc(DATE(x.ts, { day: "numeric", month: "short" }))} ${esc(TIME(x.ts))}</td><td><b>${esc(x.name || x.product)}</b></td><td>${esc(x.shop || "–")}</td>
        <td>${E.list === "new" ? esc(x.kind === "nolinks" ? t("No shop link at all") : x.kind === "suspect" ? t("Suspicious") : t("Error")) : esc(x.open_for != null ? dur(x.open_for) : "")}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${t("Nothing yet.")}</td></tr>`}</table></div>` : "";
    return `<div class="panel"><h3>📉 ${t("Progress")} <span class="muted" style="font-weight:400;font-size:13px">${t("{n} open now", { n: S.open ?? 0 })}</span></h3>
      <p class="muted" style="font-size:13px;margin-top:0">${t("Every error that is solved (a price came in, a link was fixed or found) and every new one is counted. Click a block to see which products.")}${S.since ? " " + t("Counting since {date}.", { date: DATE(S.since, { day: "numeric", month: "short", year: "numeric" }) }) : ""}</p>
      <div class="kpis">${kpi(t("Today"), s0, n0, "solved")}${kpi(t("Last 7 days"), s7, n7, "solved")}${kpi(t("Last 30 days"), s30, n30, "solved")}
        <button class="kpi click" type="button" data-elist="new" style="text-align:left;border:0;font:inherit;color:inherit;cursor:pointer${E.list === "new" ? ";outline:2px solid var(--ar-accent)" : ""}"><div class="muted" style="font-size:12px">${esc(t("Latest new errors"))}</div><b>${(S.new || []).length}</b> <span class="muted">→</span></button></div>
      <div class="chips" style="margin-top:12px">${chip("day", t("Per day"))}${chip("week", t("Per week"))}${chip("month", t("Per month"))}</div>
      ${pairBars(rows)}${listHtml}</div>`;
  }
  bindErrors(root, $) {
    const E = this.state.errs;
    root.querySelectorAll("[data-eper]").forEach((c) => c.addEventListener("click", () => { E.per = c.dataset.eper; this.renderContent(); }));
    root.querySelectorAll("[data-elist]").forEach((c) => c.addEventListener("click", () => { E.list = E.list === c.dataset.elist ? null : c.dataset.elist; this.renderContent(); }));
    root.querySelectorAll("[data-etype]").forEach((c) => c.addEventListener("click", () => { E.type = c.dataset.etype; E.open = null; this.renderContent(); }));
    $("e_shop").addEventListener("change", (e) => { E.shop = e.target.value; this.renderContent(); });
    $("e_ign").addEventListener("change", (e) => { E.showIgnored = e.target.checked; this.renderContent(); });
    root.querySelectorAll("tr.erow").forEach((tr) => tr.addEventListener("click", (e) => { if (e.target.closest("[data-product],a")) return; E.open = E.open === tr.dataset.ekey ? null : tr.dataset.ekey; this.renderContent(); const u = this.shadowRoot.querySelector(".f_url"); if (u) u.focus(); }));
    root.querySelectorAll(".item[data-inum]").forEach((box) => this.bindItemEditor(box, () => this.renderContent()));
  }
  // ---------------------------------------------------------------- notifications tab
  // ---------------------------------------------------------------- notifications tab
  async loadNotify() {
    const N = this.state.notif;
    try { N.data = await this._hass.callWS({ type: "argus/notify/get" }); N.err = null; } catch (e) { N.err = e.message || String(e); }
    if (this.state.section === "manage" && this.state.sub.manage === "notify") this.renderContent();
  }
  ruleTemplate(kind) {
    const o = this.state.notif.data.options, mob = o.notify.find((n) => n.kind === "mobile");
    const targets = mob ? [{ type: "mobile", service: mob.service }] : [{ type: "persistent" }];
    const base = { enabled: true, scope: { type: "all", categories: [], products: [] }, params: {}, shops: [], targets, cooldown_hours: 24, quiet: null, image: true, link: true };
    return {
      deals: { ...base, name: t("All deals"), triggers: ["target_hit", "all_time_low", "discount"], params: { discount_pct: this.state.data.threshold } },
      target: { ...base, name: t("Target price reached"), triggers: ["target_hit"] },
      priority: { ...base, name: t("Priority products: lowest price"), scope: { type: "priority", categories: [], products: [] }, triggers: ["all_time_low", "target_hit", "price_drop"], params: { drop_pct: 10 } },
      category: { ...base, name: t("Category below an amount"), scope: { type: "categories", categories: Object.keys(o.categories).slice(0, 1), products: [] }, triggers: ["price_below"], params: { price_below: 50 } },
      product: { ...base, name: t("Specific products"), scope: { type: "products", categories: [], products: [] }, triggers: ["price_below", "price_drop"], params: { price_below: 50, drop_pct: 10 } },
      digest: { ...base, name: t("Daily digest"), triggers: ["digest"], cooldown_hours: 0, image: false, link: false },
      dotd: { ...base, name: t("Deal of the day"), triggers: ["deal_of_day"], params: { dotd_time: "09:00" }, cooldown_hours: 0 },
      problems: { ...base, name: t("Report problems"), triggers: ["problems"], targets: [{ type: "persistent" }], image: false, link: false },
    }[kind];
  }
  ruleSummary(r) {
    const o = this.state.notif.data.options, trg = o.triggers, p = r.params || {};
    const cat = (c) => t(o.categories[c] || c), prod = (id) => o.products[id] || id;
    const scope = { all: t("all products"), priority: t("priority products (★★ and ★★★)"), categories: `${t("categories")}: ${(r.scope.categories || []).map(cat).join(", ")}`,
      products: `${t("products")}: ${(r.scope.products || []).slice(0, 5).map(prod).join(", ")}${(r.scope.products || []).length > 5 ? "…" : ""}` }[r.scope.type];
    const trig = r.triggers.map((k) => { const x = trg[k] || { label: k }; const v = { discount_pct: `≥ ${p.discount_pct}%`, price_below: `≤ €${p.price_below}`, drop_pct: `≥ ${p.drop_pct}%`, min_score: `≥ ${p.min_score}` }[x.param] || ""; return `${t(x.label)}${v ? " " + v : ""}`; });
    const tgt = r.targets.map((x) => this.targetLabel(x));
    return `<span class="tag">🎯 ${esc(scope)}</span>${trig.map((x) => `<span class="tag">⚡ ${esc(x)}</span>`).join("")}${r.shops && r.shops.length ? `<span class="tag">🏪 ${r.shops.map((x) => esc(o.retailers[x] || x)).join(", ")}</span>` : ""}<br>${tgt.map((x) => `<span class="tag">➜ ${esc(x)}</span>`).join("")}${r.quiet ? `<span class="tag">🌙 ${t("quiet {from}–{to}", { from: r.quiet.from, to: r.quiet.to })}</span>` : ""}`;
  }
  targetLabel(x) {
    const o = this.state.notif.data.options, svc = (s) => (o.notify.find((n) => n.service === s) || {}).label || s;
    return { mobile: `📱 ${svc(x.service)}`, notify: `💬 ${svc(x.service)}`, email: `✉️ ${(x.to || []).join(", ")}`, persistent: "🔔 " + t("Notification in Home Assistant"),
      entity: `📣 ${(o.notify_entities.find((e) => e.entity_id === x.entity_id) || {}).label || x.entity_id}`, tts: `🔊 ${(o.media_players.find((e) => e.entity_id === x.media_player) || {}).label || x.media_player}`, event: "⚡ " + t("Event only (automations)") }[x.type] || x.type;
  }
  vNotify() {
    const N = this.state.notif;
    if (N.err) return this.emptyState("🔒", `${t("Notifications not available: {error}", { error: esc(tx(N.err)) })}<br>${t("Only administrators can set up notifications.")}`);
    if (!N.data) { this.loadNotify(); return `<div class="skel" style="height:300px"></div>`; }
    if (N.edit) return this.vRuleEditor();
    const d = N.data;
    const list = d.rules.map((r, i) => `<div class="rule ${r.enabled ? "" : "off"}" data-ri="${i}"><label class="switch" title="${t("On/off")}"><input type="checkbox" class="r_on" ${r.enabled ? "checked" : ""}><i></i></label>
      <div style="flex:1;min-width:0"><b>${esc(r.name)}</b>${d.queued[r.id] ? ` <span class="tag">🌙 ${t("{n} queued", { n: d.queued[r.id] })}</span>` : ""}<div class="sum">${this.ruleSummary(r)}</div></div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end"><button class="btn ghost sm r_edit">✎ ${t("Edit")}</button><button class="btn ghost sm r_test" title="${t("Send a test notification")}">🔔</button><button class="btn ghost sm r_dup" title="${t("Duplicate")}">⧉</button><button class="btn danger sm r_del" title="${t("Delete")}">🗑</button></div></div>`).join("");
    const tpl = [["deals", "🏷️ " + t("All deals")], ["target", "🎯 " + t("Target price reached")], ["priority", "★ " + t("Priority products: lowest price")], ["category", "🗂 " + t("Category below an amount")], ["product", "👁 " + t("Specific products")], ["dotd", "⭐ " + t("Deal of the day")], ["digest", "🗞️ " + t("Daily digest")], ["problems", "⚠️ " + t("Problems")]];
    const log = d.log.slice(0, 15).map((l) => `<li><span class="ic">${l.queued ? "🌙" : l.ok ? "✅" : "⚠️"}</span><div><b>${esc(tx(l.title))}</b><div>${esc(tx(l.message.split("\n")[0]))}</div><div class="t">${esc(l.rule)} · ${DATE(l.ts, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</div></div></li>`).join("");
    return `<div class="cols" data-nf="1"><div><div class="panel"><h3>🔔 ${t("Notification rules")}<span class="hsp"></span></h3><p>${t("Each rule decides for which products, when, and to whom and how you get a notification. Every notification also fires the event {event} for your own automations, and ends up in the Logbook.", { event: "<code>argus_notification</code>" })}</p>
      ${list || this.emptyState("🔕", t("No rules yet. Pick a template below."))}</div>
      <div class="panel"><h3>＋ ${t("New rule")}</h3><div class="chips">${tpl.map(([k, l]) => `<span class="chip" data-tpl="${k}">${l}</span>`).join("")}</div></div></div>
      <aside><div class="panel"><h3>📜 ${t("Recently sent")}</h3>${log ? `<ul class="tl">${log}</ul>` : `<p>${t("Nothing sent yet.")}</p>`}</div></aside></div>`;
  }
  vRuleEditor() {
    const N = this.state.notif, r = N.edit, o = N.data.options, p = r.params || (r.params = {});
    const opt = (list, cur, ph) => `${ph ? `<option value="">${ph}</option>` : ""}${list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(l)}</option>`).join("")}`;
    const cats = Object.entries(o.categories);
    const scopeBox = r.scope.type === "categories"
      ? `<div class="fbar"><select id="n_theme_add">${opt(cats.filter(([k]) => !r.scope.categories.includes(k)).map(([k, v]) => [k, `${CATEGORY_ICONS[k] || ""} ${t(v)}`]), "", t("Choose a category…"))}</select><button class="btn ghost sm" id="n_theme_btn">＋ ${t("Add")}</button></div>
         <div class="chips">${r.scope.categories.map((c) => `<span class="chip on" data-rmtheme="${esc(c)}">${esc(t(o.categories[c] || c))} ✕</span>`).join("") || `<span class="muted">${t("No category chosen yet.")}</span>`}</div>`
      : r.scope.type === "products"
      ? `<div class="fbar"><select id="n_set_pick" style="min-width:260px">${opt(Object.entries(o.products).filter(([id]) => !r.scope.products.includes(id)).sort((a, b) => a[1].localeCompare(b[1])).map(([id, n]) => [id, n.slice(0, 70)]), "", t("Choose a product…"))}</select><button class="btn ghost sm" id="n_set_btn">＋</button></div>
         <div class="chips">${r.scope.products.map((id) => `<span class="chip on" data-rmset="${esc(id)}">${esc((o.products[id] || "(" + t("not tracked") + ")").slice(0, 40))} ✕</span>`).join("") || `<span class="muted">${t("No product chosen yet.")}</span>`}</div>`
      : "";
    const pc = (k, list) => `<select data-param="${k}">${opt(list.map((v) => [v, k !== "min_score" ? `${v}%` : v]), p[k] ?? list[Math.floor(list.length / 2)])}</select>`;
    const trigRow = (k) => { const tg = o.triggers[k]; const on = r.triggers.includes(k);
      const par = { discount_pct: pc("discount_pct", [10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70]), drop_pct: pc("drop_pct", [5, 10, 15, 20, 25, 30, 40, 50]), min_score: pc("min_score", [45, 50, 60, 70, 80, 90]),
        dotd_time: `<span style="display:flex;gap:4px;align-items:center">${t("at")} <select data-param="dotd_time" data-str="1">${opt(Array.from({ length: 48 }, (_, i) => { const v = `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`; return [v, v]; }), p.dotd_time || "09:00")}</select></span>`,
        price_below: `<span style="display:flex;gap:4px;align-items:center">€ <input data-param="price_below" type="number" min="1" step="1" value="${esc(p.price_below ?? "")}" placeholder="${t("amount")}" style="width:90px"></span>` }[tg.param] || "";
      return `<div class="trig"><input type="checkbox" data-trig="${k}" ${on ? "checked" : ""}><label style="cursor:pointer" data-trigl="${k}">${esc(t(tg.label))}${tg.per_product ? "" : ` <span class="muted" style="font-size:12px">(${t("general")})</span>`}</label><div>${par}</div></div>`; };
    const perSet = Object.keys(o.triggers).filter((k) => o.triggers[k].per_product), general = Object.keys(o.triggers).filter((k) => !o.triggers[k].per_product);
    const mobiles = o.notify.filter((n) => n.kind === "mobile"), mails = o.notify.filter((n) => n.kind === "email");
    const tgtRow = (x, i) => {
      let body = "";
      if (x.type === "mobile") body = mobiles.length ? `<select data-tf="service">${opt(mobiles.map((n) => [n.service, n.label]), x.service, t("Choose a device…"))}</select>` : `<span class="err">${t("No Home Assistant app found. Install the Companion app on your phone.")}</span>`;
      if (x.type === "notify") body = `<select data-tf="service">${opt(o.notify.map((n) => [n.service, `${n.label} (${n.service})`]), x.service, t("Choose a notify service…"))}</select>`;
      if (x.type === "email") body = `<select data-tf="service" title="${t("Service that sends the e-mail")}">${opt((mails.length ? mails : o.notify).map((n) => [n.service, `${n.label} (${n.service})`]), x.service, t("Send via…"))}</select><input data-tf="to" placeholder="name@example.com, …" value="${esc((x.to || []).join(", "))}" style="min-width:220px">${mails.length ? "" : `<span class="muted" style="font-size:12px">${t("Tip: add the SMTP integration to send e-mails.")}</span>`}`;
      if (x.type === "entity") body = o.notify_entities.length ? `<select data-tf="entity_id">${opt(o.notify_entities.map((n) => [n.entity_id, n.label]), x.entity_id, t("Choose a notify entity…"))}</select>` : `<span class="muted">${t("No notify entities found.")}</span>`;
      if (x.type === "tts") body = `<select data-tf="tts">${opt(o.tts.map((n) => [n.entity_id, n.label]), x.tts, t("Speech service…"))}</select><select data-tf="media_player">${opt(o.media_players.map((n) => [n.entity_id, n.label]), x.media_player, t("Speaker…"))}</select>`;
      if (x.type === "persistent") body = `<span class="muted">${t("Appears among the notifications in Home Assistant.")}</span>`;
      if (x.type === "event") body = `<span class="muted">${t("Only the event {event}, for your own automations.", { event: "<code>argus_notification</code>" })}</span>`;
      return `<div class="tgt" data-ti="${i}"><select data-tf="type">${opt([["mobile", "📱 " + t("Mobile app")], ["email", "✉️ " + t("E-mail")], ["notify", "💬 " + t("Notify service (Telegram, Signal, …)")], ["entity", "📣 " + t("Notify entity")], ["persistent", "🔔 " + t("Notification in Home Assistant")], ["tts", "🔊 " + t("Speech on a speaker")], ["event", "⚡ " + t("Event only")]], x.type)}</select>${body}<span style="flex:1"></span><button class="btn ghost sm" data-rmt="${i}">✕</button></div>`;
    };
    const hours = Array.from({ length: 24 }, (_, h) => [`${String(h).padStart(2, "0")}:00`, `${String(h).padStart(2, "0")}:00`]);
    return `<div data-nf="1"><div class="panel"><h3>${N.idx == null ? "＋ " + t("New rule") : "✎ " + t("Edit rule")}<span class="hsp"></span><button class="btn ghost sm" id="n_cancel">← ${t("Back")}</button></h3>
      <div class="form"><label style="grid-column:span 2">${t("Name")}<input id="n_name" value="${esc(r.name)}" maxlength="60"></label><label class="chk" style="align-self:end"><input type="checkbox" id="n_enabled" ${r.enabled ? "checked" : ""}> ${t("rule is on")}</label></div></div>
      <div class="panel"><h3>1 · ${t("For which products?")}</h3><div class="fbar"><select id="n_scope">${opt([["all", t("All tracked products")], ["priority", "★ " + t("Priority products (★★ and ★★★)")], ["categories", "🗂 " + t("Certain categories")], ["products", "👁 " + t("Certain products")]], r.scope.type)}</select></div>${scopeBox}</div>
      <div class="panel"><h3>2 · ${t("When?")}</h3><p style="margin-bottom:4px">${t("Per product:")}</p>${perSet.map(trigRow).join("")}<p style="margin:12px 0 4px">${t("General:")}</p>${general.map(trigRow).join("")}
        <div class="fbar" style="margin-top:10px"><span class="muted">${t("In which shops?")}</span><select id="n_shop_add">${opt(Object.entries(o.retailers).filter(([k]) => !r.shops.includes(k)), "", r.shops.length ? "＋ " + t("add a shop") : t("All shops (or choose…)"))}</select>
        ${r.shops.map((k) => `<span class="chip on" data-rmshop="${k}">${esc(o.retailers[k] || k)} ✕</span>`).join("")}</div></div>
      <div class="panel"><h3>3 · ${t("To whom and how?")}</h3>${r.targets.map(tgtRow).join("")}<button class="btn ghost sm" id="n_tadd">＋ ${t("Add a recipient")}</button>
        <div class="form" style="margin-top:12px"><label>${t("Don't notify again within")}<select id="n_cool">${opt([[0, t("always notify")], [1, t("1 hour")], [6, t("{n} hours", { n: 6 })], [12, t("{n} hours", { n: 12 })], [24, t("1 day")], [72, t("{n} days", { n: 3 })], [168, t("1 week")]], r.cooldown_hours)}</select></label>
        <label>${t("Quiet hours")}<select id="n_qon">${opt([["", t("none")], ["1", t("on")]], r.quiet ? "1" : "")}</select></label>
        ${r.quiet ? `<label>${t("from")}<select id="n_qf">${opt(hours, r.quiet.from)}</select></label><label>${t("to")}<select id="n_qt">${opt(hours, r.quiet.to)}</select></label>` : ""}</div>
        <div class="form"><label class="chk"><input type="checkbox" id="n_img" ${r.image ? "checked" : ""}> ${t("include an image")}</label><label class="chk"><input type="checkbox" id="n_link" ${r.link ? "checked" : ""}> ${t("link to the shop")}</label></div>
        <p style="font-size:12px">${t("During quiet hours notifications are collected and sent afterwards in one message (the Home Assistant notification and the event come right away).")}</p></div>
      <div class="panel" style="position:sticky;bottom:12px;z-index:2;display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="n_save">💾 ${t("Save rule")}</button><button class="btn ghost" id="n_test">🔔 ${t("Test notification")}</button><button class="btn ghost" id="n_cancel2">${t("Cancel")}</button></div></div>`;
  }
  async saveRules(rules, msg) {
    const N = this.state.notif;
    const r = await this._hass.callWS({ type: "argus/notify/set", rules });
    N.data.rules = r.rules; if (msg) this.toast(msg, "ok");
  }
  bindNotify(root, $) {
    const N = this.state.notif, d = N.data;
    root.querySelectorAll("[data-tpl]").forEach((c) => c.addEventListener("click", () => { N.edit = JSON.parse(JSON.stringify(this.ruleTemplate(c.dataset.tpl))); N.idx = null; this.renderContent(true); }));
    root.querySelectorAll(".rule[data-ri]").forEach((el) => {
      const i = +el.dataset.ri, q = (c) => el.querySelector("." + c);
      q("r_on").addEventListener("change", (e) => { const rules = JSON.parse(JSON.stringify(d.rules)); rules[i].enabled = e.target.checked; this.saveRules(rules, e.target.checked ? t("Rule switched on") : t("Rule switched off")).then(() => this.renderContent()).catch((err) => this.toast(tx(err.message), "err")); });
      q("r_edit").onclick = () => { N.edit = JSON.parse(JSON.stringify(d.rules[i])); N.idx = i; this.renderContent(true); };
      q("r_dup").onclick = () => { const c = JSON.parse(JSON.stringify(d.rules[i])); delete c.id; c.name += " (" + t("copy") + ")"; N.edit = c; N.idx = null; this.renderContent(true); };
      q("r_del").onclick = () => { if (!confirm(t("Delete rule “{name}”?", { name: d.rules[i].name }))) return; const rules = d.rules.filter((_, j) => j !== i); this.busy(q("r_del"), "", async () => { await this.saveRules(rules, t("Rule deleted")); this.renderContent(); }); };
      q("r_test").onclick = () => this.testRule(d.rules[i], q("r_test"));
    });
    if (!N.edit) return;
    const r = N.edit;
    const sync = () => {
      const v = (id) => (root.querySelector("#" + id) || {}).value;
      if ($("n_name")) r.name = $("n_name").value; if ($("n_enabled")) r.enabled = $("n_enabled").checked;
      root.querySelectorAll("[data-trig]").forEach((c) => { const k = c.dataset.trig; r.triggers = r.triggers.filter((x) => x !== k); if (c.checked) r.triggers.push(k); });
      root.querySelectorAll("[data-param]").forEach((c) => { r.params[c.dataset.param] = c.value === "" ? undefined : c.dataset.str ? c.value : +c.value; });
      root.querySelectorAll(".tgt").forEach((el) => { const tg = r.targets[+el.dataset.ti]; el.querySelectorAll("[data-tf]").forEach((f) => { if (f.dataset.tf === "type") return; tg[f.dataset.tf] = f.dataset.tf === "to" ? f.value.split(/[,;\s]+/).filter(Boolean) : f.value; }); });
      if ($("n_cool")) r.cooldown_hours = +v("n_cool");
      if ($("n_qon")) r.quiet = v("n_qon") ? { from: v("n_qf") || "22:00", to: v("n_qt") || "07:00" } : null;
      if ($("n_img")) r.image = $("n_img").checked; if ($("n_link")) r.link = $("n_link").checked;
    };
    const rerender = () => { sync(); this.renderContent(); };
    root.querySelectorAll("[data-trigl]").forEach((l) => l.addEventListener("click", () => { const c = root.querySelector(`[data-trig="${l.dataset.trigl}"]`); c.checked = !c.checked; }));
    $("n_scope").addEventListener("change", (e) => { sync(); r.scope.type = e.target.value; this.renderContent(); });
    if ($("n_theme_btn")) $("n_theme_btn").onclick = () => { const th = $("n_theme_add").value; if (!th) return this.toast(t("Choose a category first"), "err"); sync(); r.scope.categories.push(th); this.renderContent(); };
    if ($("n_theme_add")) $("n_theme_add").addEventListener("change", () => $("n_theme_btn").click());
    root.querySelectorAll("[data-rmtheme]").forEach((c) => c.onclick = () => { sync(); r.scope.categories = r.scope.categories.filter((th) => th !== c.dataset.rmtheme); this.renderContent(); });
    const addSet = (n) => { if (!n) return; if (r.scope.products.includes(n)) return this.toast(t("Already in the list"), "err"); sync(); r.scope.products.push(n); this.renderContent(); };
    if ($("n_set_btn")) $("n_set_btn").onclick = () => addSet($("n_set_pick").value);
    if ($("n_set_pick")) $("n_set_pick").addEventListener("change", (e) => e.target.value && addSet(e.target.value));
    root.querySelectorAll("[data-rmset]").forEach((c) => c.onclick = () => { sync(); r.scope.products = r.scope.products.filter((x) => x !== c.dataset.rmset); this.renderContent(); });
    $("n_shop_add").addEventListener("change", (e) => { if (!e.target.value) return; sync(); r.shops.push(e.target.value); this.renderContent(); });
    root.querySelectorAll("[data-rmshop]").forEach((c) => c.onclick = () => { sync(); r.shops = r.shops.filter((x) => x !== c.dataset.rmshop); this.renderContent(); });
    root.querySelectorAll('.tgt [data-tf="type"]').forEach((sel) => sel.addEventListener("change", (e) => { sync(); r.targets[+e.target.closest(".tgt").dataset.ti] = { type: e.target.value }; this.renderContent(); }));
    root.querySelectorAll("[data-rmt]").forEach((b) => b.onclick = () => { sync(); r.targets.splice(+b.dataset.rmt, 1); this.renderContent(); });
    $("n_tadd").onclick = () => { sync(); const mob = d.options.notify.find((n) => n.kind === "mobile"); r.targets.push(mob ? { type: "mobile", service: mob.service } : { type: "persistent" }); this.renderContent(); };
    $("n_qon").addEventListener("change", rerender);
    const back = () => { N.edit = null; N.idx = null; this.renderContent(true); };
    $("n_cancel").onclick = back; $("n_cancel2").onclick = back;
    $("n_save").onclick = () => {
      sync();
      Object.keys(r.params).forEach((k) => { if (r.params[k] == null || isNaN(r.params[k])) delete r.params[k]; });
      const rules = JSON.parse(JSON.stringify(d.rules)); if (N.idx == null) rules.push(r); else rules[N.idx] = r;
      this.busy($("n_save"), t("Saving…"), async () => { await this.saveRules(rules, t("Rule saved")); back(); });
    };
    $("n_test").onclick = () => { sync(); this.testRule(r, $("n_test")); };
  }
  testRule(rule, btn) {
    const r = JSON.parse(JSON.stringify(rule)); Object.keys(r.params || {}).forEach((k) => { if (r.params[k] == null) delete r.params[k]; });
    return this.busy(btn, "…", async () => {
      const res = (await this._hass.callWS({ type: "argus/notify/test", rule: r })).results;
      const bad = res.filter((x) => !x.ok);
      if (bad.length) this.toast(t("Failed: {list}", { list: bad.map((x) => `${this.targetLabel(x.target)} (${tx(x.error)})`).join("; ") }), "err");
      else this.toast(t(res.length > 1 ? "Test notification sent to {n} recipients" : "Test notification sent to {n} recipient", { n: res.length }), "ok");
    });
  }
  vLinks() {
    const L = this.state.links, rows = [];
    for (const s of this.products) {
      for (const [rid, o] of Object.entries(s.offers || {})) {
        const st = o.link_status || "unknown";
        if (L.status !== "all" && !(L.status === st || (L.status === "ok" && st === "confirmed"))) continue;
        rows.push({ s, rid, o, st });
      }
    }
    const count = (st) => this.products.reduce((a, s) => a + Object.values(s.offers || {}).filter((o) => (o.link_status || "unknown") === st || (st === "ok" && o.link_status === "confirmed")).length, 0);
    const chip = (k, l) => `<span class="chip ${L.status === k ? "on" : ""}" data-lstatus="${k}">${l}${k !== "all" ? ` <span class="muted">${count(k)}</span>` : ""}</span>`;
    const trs = rows.slice(0, 400).map(({ s, rid, o, st }) => {
      const key = `${s.id}|${rid}`, open = L.edit === key;
      return `<tr class="click lrow2${open ? " on" : ""}" data-key="${esc(key)}"><td style="min-width:150px"><span class="muted">${open ? "▾" : "▸"}</span> <a class="setlink" data-set="${esc(s.id)}"><b>${esc((s.name || s.id).slice(0, 60))}</b></a><div class="muted" style="font-size:12px">${esc(this.catName(s.category))}${s.ean ? ` · ${esc(s.ean)}` : ""}</div></td>
        <td>${esc(o.label)}</td><td><span class="lk ${st}">${{ ok: "✓ " + t("correct"), confirmed: "✓ " + t("approved"), suspect: "⚠ " + t("suspicious"), unknown: "? " + t("unknown") }[st]}</span><div class="${st === "suspect" ? "err" : "muted"}" style="font-size:12px;margin-top:3px">${esc(tx(o.link_reason || ""))}</div></td>
        <td style="max-width:280px;font-size:13px">${o.title ? esc(o.title.slice(0, 120)) : `<span class="muted">${o.url ? esc(decodeURIComponent(o.url.replace(/^https?:\/\/(www\.)?/, "")).slice(0, 70)) : ""}</span>`}</td>
        <td class="num">${o.price != null ? EUR(o.price) : o.low != null ? `<span class="muted">${EUR(o.low)}</span>` : "–"}</td>
        <td style="white-space:nowrap">${o.url ? `<a class="btn ghost sm" href="${esc(o.url)}" target="_blank" rel="noopener noreferrer">↗</a> ` : ""}${st !== "confirmed" ? `<button class="btn ghost sm lok" title="${t("Correct")}">✓</button> ` : ""}<button class="btn ghost sm ledit" title="${t("Edit name, links and prices; fetch per shop")}">✎</button> <button class="btn ghost sm lrm" title="${t("Remove")}">🗑</button></td></tr>${open ? `<tr class="efix"><td colspan="6">${this.itemEditorHtml(s, rid)}</td></tr>` : ""}`;
    }).join("");
    return `<div class="panel"><h3>🔗 ${t("Link check")}<span class="hsp"></span><button class="btn ghost sm" id="lverify">↺ ${t("Judge again")}</button></h3>
      <p>${t("Checks whether every shop link points to the same product: the barcode on the page must match, else the title must cover the product's name and model number, and it must not be an accessory (case, cable, spare part…). A far too low price is suspicious too. Suspicious links don't count for prices until you approve them. For a marketplace the title is only known after a price check.")}</p>
      <div class="chips">${chip("suspect", "⚠ " + t("Suspicious"))}${chip("unknown", "? " + t("Not checked"))}${chip("ok", "✓ " + t("OK"))}${chip("all", t("All"))}</div></div>
      ${rows.length ? `<div class="panel tscroll"><table class="tbl"><tr><th>${t("Product")}</th><th>${t("Shop")}</th><th>${t("Verdict")}</th><th>${t("Product title / URL")}</th><th class="num">${t("Price")}</th><th></th></tr>${trs}</table>${rows.length > 400 ? `<p class="muted">${t("First {n} of {total}.", { n: 400, total: rows.length })}</p>` : ""}</div>` : this.emptyState("✅", L.status === "suspect" ? t("No suspicious links. Nice!") : t("No links in this selection."))}`;
  }
  // ---------------------------------------------------------------- settings
  // ---------------------------------------------------------------- settings
  async loadSettings() {
    try { this.state.settings = await this._hass.callWS({ type: "argus/settings/get" }); this.state.settingsErr = null; }
    catch (e) { this.state.settingsErr = e.message || String(e); }
    this.state.draft = null;
    this.state.dfDraft = null;
    if ((this.state.section === "manage" && ["settings", "secret"].includes(this.state.sub.manage)) || (this.state.section === "prices" && this.state.sub.prices === "dset")) this.renderContent();
  }
  vSettings() {
    const st = this.state.settings;
    if (this.state.settingsErr) return this.emptyState("🔒", `${t("Settings not available: {error}", { error: esc(tx(this.state.settingsErr)) })}<br>${t("Only administrators can change settings.")}`);
    if (!st) { this.loadSettings(); return `<div class="skel" style="height:300px"></div>`; }
    const d = this.state.draft || (this.state.draft = { shops: st.shops.map((x) => ({ ...x })), custom: st.shops.filter((x) => !x.builtin).map((x) => ({ id: x.id, name: x.label, domain: x.domain, search: x.search, categories: x.categories })), mode: st.refresh_mode || "spread" });
    const cats = st.categories || {}, catIcons = (x) => (x.categories && x.categories.length ? x.categories : Object.keys(cats)).map((c) => CATEGORY_ICONS[c] || "").join(" ");
    const shopRows = d.shops.map((x) => `<tr data-shop="${esc(x.id)}"><td><label class="chk" style="display:flex;gap:8px;align-items:center"><input type="checkbox" class="s_on" ${x.enabled ? "checked" : ""}> <b>${esc(x.label)}</b></label><div class="muted" style="font-size:12px">${x.builtin ? "" : t("own shop") + " · "}${esc(x.domain)} · ${catIcons(x)}</div></td>
      <td>${x.paused_hours > 0 ? `<span class="lk suspect">${t("paused {time}", { time: dur(x.paused_hours * 3600) })}</span> <button class="btn ghost sm" data-resume="${esc(x.id)}">▶ ${t("Resume")}</button>` : `<span class="lk ok">${t("active")}</span>`}${x.blocks ? `<div class="muted" style="font-size:12px">${t("blocked {n}×", { n: x.blocks })}</div>` : ""}</td>
      <td><label class="chk" style="display:flex;gap:8px;align-items:center" title="${t("After a block (403/captcha) leave this shop alone for a while")}"><input type="checkbox" class="s_ap" ${x.autopause ? "checked" : ""}> ${t("pause automatically")}</label></td>
      <td style="min-width:300px"><div style="display:flex;gap:4px"><input class="s_search" value="${esc(x.search || "")}" placeholder="${esc(x.default_search || "https://…{query}")}" style="flex:1;min-width:220px;font-size:12px">${x.default_search ? `<button class="btn ghost sm s_reset" title="${t("Back to the default: {url}", { url: esc(x.default_search) })}" ${x.search === x.default_search ? "hidden" : ""}>↺</button>` : ""}</div><div class="s_prev muted" style="font-size:11px;margin-top:3px">${this.searchPreview(x.search || x.default_search)}</div></td>
      <td>${x.builtin ? "" : `<button class="btn danger sm s_del" title="${t("Remove shop")}">🗑</button>`}</td></tr>`).join("");
    const langs = st.languages || {}, mode = d.mode, dev = st.dev || {};
    return `${this.colorsPanel()}<div class="panel"><h3>🌐 ${t("Language")}</h3><div class="form" style="max-width:520px"><label>${t("Language of the panel, notifications and userscript")}<select id="o_lang"><option value="auto" ${st.language === "auto" ? "selected" : ""}>${t("Automatic (Home Assistant language)")}</option>${Object.entries(langs).map(([k, l]) => `<option value="${k}" ${st.language === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label></div></div>
      <div class="panel"><h3>🔔 ${t("Notifications")}</h3><p class="muted" style="font-size:13px">${t("What counts as a deal is set under Prices → Deal settings.")} <a data-goto="prices/dset" style="cursor:pointer">🏷️ ${t("Deal settings")} →</a></p>
        <div class="form"><label>${t("Notifications")}<a class="btn ghost sm" data-goto="manage/notify" style="cursor:pointer;margin-top:4px;align-self:flex-start">🔔 ${t("Go to Notifications")}</a><input id="o_notify" type="hidden" value="${esc(st.notify_service)}"></label>
        <label>${t("Daily digest at")}<input id="o_digest" type="time" value="${esc(st.digest_time)}"></label></div></div>
      <div class="panel"><h3>⏰ ${t("Automatic price checks")}</h3><div class="radio">
        <label class="${mode === "spread" ? "on" : ""}"><input type="radio" name="rmode" value="spread" ${mode === "spread" ? "checked" : ""}><b>🔄 ${t("Spread over the day")}</b><span>${t("Every product is checked once per cycle at every shop, evenly spread (e.g. 240 products in 24 h = 10 products per hour). Gentle on the shops, fewer blocks.")}</span></label>
        <label class="${mode === "times" ? "on" : ""}${dev.dev_fixed_times ? "" : " dis"}" title="${dev.dev_fixed_times ? "" : t("Switched off to protect the traffic to and the load on the shops.")}"><input type="radio" name="rmode" value="times" ${mode === "times" ? "checked" : ""} ${dev.dev_fixed_times ? "" : "disabled"}><b>🕖 ${t("At fixed times")}</b><span>${dev.dev_fixed_times ? t("A full round of all products at the times you choose.") : t("Not available, to protect the traffic to and the load on the shops.")}</span></label>
        <label class="${mode === "off" ? "on" : ""}"><input type="radio" name="rmode" value="off" ${mode === "off" ? "checked" : ""}><b>⏸ ${t("Off")}</b><span>${t("Only when you fetch a product yourself (↻ in the product window).")}</span></label></div>
        <div class="form" id="rm_spread" ${mode === "spread" ? "" : "hidden"}>
          <label title="${t("How often every product is checked at every shop. Shorter = fresher prices, but more load on the shops.")}">${t("Cycle: every product once every … hours")} ⓘ${dev.dev_free_cycle ? `<input id="o_spread" type="number" min="1" max="168" value="${st.spread_hours}">` : `<select id="o_spread">${(st.cycle_choices || [2, 3, 4, 6, 12, 24]).map((h) => `<option value="${h}" ${+st.spread_hours === h ? "selected" : ""}>${t("{n} h", { n: h })}</option>`).join("")}</select>`}<span class="hint" id="o_spread_hint"></span></label>
          <label title="${t("Products with a priority of ★★ or ★★★ can be checked more often than the rest (never less often).")}">${t("Priority products: every product once every …")} ⓘ<select id="o_wcycle">${(st.watch_cycle_choices || [0]).map((m) => `<option value="${m}" ${+st.watch_cycle_min === m ? "selected" : ""}>${m ? (m < 60 ? t("{n} min", { n: m }) : t("{n} h", { n: m / 60 })) : t("like the other products")}</option>`).join("")}</select><span class="hint" id="o_wcycle_hint"></span></label>
          <div class="hint" id="o_total_hint" style="align-self:end;grid-column:1/-1"></div></div>
        <div class="form" id="rm_times" ${mode === "times" ? "" : "hidden"}><label style="grid-column:span 2">${t("Times (1 to 6, separated by commas)")}<input id="o_times" value="${esc(st.refresh_times)}" placeholder="07:30, 19:30"></label></div>
        <p class="muted" style="font-size:12px">${this.scheduleLine()} <a data-goto="log/checks" style="cursor:pointer">${t("See the shop checks")} →</a></p></div>
      <div class="panel"><h3>🔁 ${t("Browser relay")}</h3>
        <p>${t("With the userscript installed, your own browser fetches the shop pages that fail on the server in the background while Home Assistant is open, and sends the prices. Your browser is a normal visitor, so it is rarely blocked. See Manage → Userscript.")}</p>
        <div class="form"><label class="chk"><input type="checkbox" id="o_relay" ${st.browser_relay ? "checked" : ""}> ${t("Browser relay on")}</label>
        <label>${t("At most every … hours")}<input id="o_relayh" type="number" min="1" max="168" value="${st.relay_hours}"></label></div></div>
      <div class="panel"><h3>📈 ${t("Ticker")}</h3>
        <p>${t("The bar at the bottom of the screen. Click an item to open the product, or a news item to read it.")}</p>
        <div class="tscroll"><table class="tbl"><tr><th></th><th class="num">${t("At most")}</th></tr>
        ${[["drops", t("Products whose price dropped lately or is good (🔥 or better)")], ["deals", t("Deals (deal score at least the minimum under Prices → Deal settings)")], ["news", t("News")]].map(([k, l]) => `<tr><td><label class="chk" style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="o_tk_${k}" ${(st.ticker || {})[k] ? "checked" : ""}> ${esc(l)}</label></td>
          <td class="num"><input id="o_tkn_${k}" type="text" inputmode="numeric" autocomplete="off" style="width:70px" value="${(st.ticker || {})["max_" + k] ?? 3}"></td></tr>`).join("")}</table></div>
        <label class="chk" style="margin-top:8px"><input type="checkbox" id="o_tk_shuffle" ${(st.ticker || {}).shuffle !== false ? "checked" : ""}> ${t("Mix news, deals and price drops")}</label></div>
      <div class="panel"><h3>🏪 ${t("Shops")}</h3><p>${t("Tick the shops to check. “Pause automatically” pauses a shop after a block (1 → 3 → 6 → 12 → 24 h); switch it off if you don't want that (more risk of stricter blocks).")}</p>
        <p>${t("The search address decides how ARGUS finds a product at a shop; every shop has a default that you can change. Easiest: search the shop for the word {word}, copy the address bar and paste it here — the word is replaced by {query} automatically. {query} = the product's name, {ean} = its barcode. ↺ restores the default.", { word: "<code>ARGUSTEST</code>", query: "<code>{query}</code>", ean: "<code>{ean}</code>" })}</p>
        <div class="tscroll"><table class="tbl"><tr><th>${t("Shop")}</th><th>${t("Status")}</th><th>${t("Pause")}</th><th>${t("Search URL")}</th><th></th></tr>${shopRows}</table></div>
        <h3 style="margin-top:16px">＋ ${t("Add your own shop")}</h3><div class="form"><label>${t("Name")}<input id="n_name" placeholder="${t("e.g. {example}", { example: "Example Shop" })}"></label><label>${t("Domain")}<input id="n_domain" placeholder="example-shop.be"></label>
        <label style="grid-column:span 2">${t("Search URL")}<input id="n_search" placeholder="https://www.example-shop.be/search?q=ARGUSTEST"><div class="hint muted" id="n_search_prev"></div></label>
        <div style="grid-column:1/-1"><div class="muted" style="font-size:13px;margin-bottom:4px">${t("Which categories does it sell?")}</div><div class="chips">${Object.entries(cats).map(([k, v]) => `<label class="chk"><input type="checkbox" class="n_cat" value="${esc(k)}" checked> ${CATEGORY_ICONS[k] || ""} ${esc(t(v))}</label>`).join(" ")}</div></div></div>
        <p style="font-size:12px">${t("Prices are read from the standard product data (JSON-LD/meta) that most web shops have.")}</p><button class="btn ghost" id="n_add">＋ ${t("Add to the list")}</button></div>
      ${(st.finders || []).length ? `<div class="panel"><h3>🧭 ${t("Finders")}</h3>
        <p>${t("Besides the shops' own search, ARGUS finds a product's page through a web search for “brand name shop” (the first results on the shop's domain) and through price-comparison sites, whose sponsored links lead to the shops too. Whatever they return is only a suggestion: the shop's own page is always fetched and checked (barcode, model number, title) before it is linked, and prices are always read from the shop.")}</p>
        <div class="tscroll"><table class="tbl"><tr><th>${t("Finder")}</th><th>${t("Kind")}</th><th>${t("Status")}</th></tr>${(st.finders || []).map((x) => `<tr><td><label class="chk" style="display:flex;gap:8px;align-items:center"><input type="checkbox" class="f_on" value="${esc(x.id)}" ${x.enabled ? "checked" : ""}> <b>${esc(x.name)}</b></label><div class="muted" style="font-size:12px">${esc(x.domain)}</div></td>
          <td>${x.kind === "websearch" ? t("web search") : t("price comparison")}</td><td>${x.paused_hours > 0 ? `<span class="lk suspect">${t("paused {time}", { time: dur(x.paused_hours * 3600) })}</span>` : `<span class="lk ok">${t("active")}</span>`}</td></tr>`).join("")}</table></div></div>` : ""}
      <div class="panel"><h3>🚫 ${t("Product filter")}</h3>
        <p>${t("A page whose title contains one of these words is never taken as the same product (e.g. a case or a spare part for your product): it is skipped in shop searches and the link check. Words that are in your product's own name are always allowed.")}</p>
        <details style="margin:0 0 10px"><summary class="muted" style="cursor:pointer">${t("Built-in words ({n})", { n: (st.builtin_words || []).length })}</summary>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">${(st.builtin_words || []).map((w) => `<span class="abadge">${esc(w)}</span>`).join("")}</div></details>
        <div class="form">
          <label style="grid-column:span 2">${t("Extra words (one per line)")}<textarea id="o_block" rows="5" placeholder="refurbished&#10;tweedehands&#10;onderdeel*">${esc((st.block_words || []).join("\n"))}</textarea>
            <span class="hint muted">${t("Not case-sensitive, whole words; * at the end matches any ending.")}</span></label>
          <label style="grid-column:span 2">${t("Exceptions (one per line)")}<textarea id="o_allow" rows="5" placeholder="hoes&#10;case">${esc((st.allow_words || []).join("\n"))}</textarea>
            <span class="hint muted">${t("Words or phrases that may appear in the title of a real product.")}</span></label>
          <label style="grid-column:1/-1">${t("Try a product title")}<input id="o_ftest" placeholder="Beschermhoesje voor Apple iPhone 15"><span class="hint" id="o_fres"></span></label>
        </div></div>
      <div class="panel"><h3>🛠️ ${t("Technical")}</h3><div class="form"><label class="chk"><input type="checkbox" id="o_imp" ${st.use_impersonation ? "checked" : ""}> ${t("Imitate the Chrome browser (curl_cffi) – now: {transport}", { transport: esc(st.transport) })}</label></div></div>
      <div class="panel" style="position:sticky;bottom:12px;z-index:2;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button class="btn" id="o_save">💾 ${t("Save settings")}</button><span class="muted" style="font-size:13px">${t("After saving the integration restarts briefly (a running job stops).")}</span></div>`;
  }
  /** Turn a pasted search-result URL into a template: the word ARGUSTEST becomes {query}, a barcode {ean}. */
  /** Turn a pasted search-result URL into a template: the word ARGUSTEST becomes {query}, a barcode {ean}. */
  toTemplate(url) {
    url = (url || "").trim();
    if (!url || /\{(query|ean)\}/.test(url)) return url;
    if (/ARGUSTEST/i.test(url)) return url.replace(/ARGUSTEST/gi, "{query}");
    const n = url.match(/([=/])(\d{8,14})(?=[&#/]|$)/);
    if (n) return url.replace(n[0], `${n[1]}{ean}`);
    return url;
  }
  searchPreview(tpl) {
    if (!tpl) return "";
    if (!/\{(query|ean)\}/.test(tpl)) return `<span class="err">${t("Must contain {query} or {ean}", { query: "{query}", ean: "{ean}" })}</span>`;
    const ex = tpl.replace("{query}", "sony+wh-1000xm5").replace("{ean}", "4548736132580");
    return `${t("Example")}: <a href="${esc(ex)}" target="_blank" rel="noopener noreferrer">${esc(ex.length > 70 ? ex.slice(0, 70) + "…" : ex)} ↗</a>`;
  }
  vUserscript() {
    const origin = location.origin, url = `${origin}/api/argus/argus.user.js`, last = this.state.data.userscript_last;
    const ua = navigator.userAgent, browser = /Edg\//.test(ua) ? "edge" : /Firefox\//.test(ua) ? "firefox" : /Safari\//.test(ua) && !/Chrome\//.test(ua) ? "safari" : "chrome";
    const stores = { chrome: ["Chrome", "https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo"], edge: ["Edge", "https://microsoftedge.microsoft.com/addons/detail/tampermonkey/iikmkjmpaadaobahmlepeloendndfphd"], firefox: ["Firefox", "https://addons.mozilla.org/firefox/addon/tampermonkey/"], safari: ["Safari", "https://www.tampermonkey.net/?browser=safari"] };
    const step = (n, title, body) => `<div class="action" style="--i:${n}"><b><span class="st ok" style="margin-right:6px">${n}</span>${title}</b>${body}</div>`;
    setTimeout(() => this.relayPing(), 50);
    const how = [t("Links that never had a price come first."), t("Then products without any price: the shops that have no link yet are searched in your browser; a product found there is linked and fetched right away."),
      t("Then links the server can't fetch (blocked, paused, errors), each at most every 6 hours."), t("Calm: every site at most twice a minute, a search at most once every 2 minutes per site, 4–9 s between pages; a site that blocks your browser twice is left alone for an hour."),
      t("Prices from your browser get the mark ⓤ next to the price (product → Shops, and on the cards)."),
      t("Shops whose search is built with JavaScript can be searched in a background tab: switch it on below.")];
    return `<div class="panel"><h3>♾️ ${t("Continuous check")}</h3><p>${t("The userscript can also keep checking by itself, as long as a Home Assistant tab is open in that browser. It focuses on what the server can't do:")}</p>
      <ol style="margin:0 0 10px;padding-left:20px">${how.map((x) => `<li>${x}</li>`).join("")}</ol><div id="contbox">${this.contBoxInner()}</div></div>
      <div class="panel"><h3>🔁 ${t("Browser relay")}</h3><p>${t("While Home Assistant is open in a browser with the userscript, that browser fetches the shop pages that fail on the server in the background, calmly one by one, and sends the prices to Home Assistant. It runs automatically at most every few hours (Settings), or now with the button.")}</p><div id="relaybox">${this.relayBoxInner()}</div></div>
      <div class="panel"><h3>🧩 ${t("Send prices from your own browser")}</h3><p>${t("Shops block servers, but not your browser. The userscript reads the price and product title on every product page you visit and sends them to Home Assistant. That also works for shops that block servers, and the title helps the link check. Only products that are already tracked (same link or product code) are updated.")}</p>
      ${last ? `<div class="banner" style="background:color-mix(in srgb,var(--ar-green) 12%,var(--ar-card));border-color:color-mix(in srgb,var(--ar-green) 40%,transparent)">✅ ${t("Works: last price received {when} (product {number}, {price} at {shop}).", { when: ago(last.ts), number: esc(last.id), price: EUR(last.price), shop: esc(this.state.data.retailers[last.retailer] || last.retailer) })} <a data-goto="log/all" style="cursor:pointer">${t("Logbook")} →</a></div>` : `<div class="banner">${t("No price received through the userscript yet.")}</div>`}</div>
      <div class="actions">
      ${step(1, t("Install Tampermonkey"), `<p>${t("Free browser extension. For your browser ({browser}):", { browser: stores[browser][0] })}</p><a class="btn" href="${stores[browser][1]}" target="_blank" rel="noopener noreferrer">${t("Tampermonkey for {browser}", { browser: stores[browser][0] })} ↗</a><p style="font-size:12px">${t("Other browsers:")} ${Object.entries(stores).filter(([k]) => k !== browser).map(([, [n, u]]) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${n}</a>`).join(" · ")}. ${t("In Chrome/Edge also switch on “Allow user scripts” for the extension, or developer mode.")}</p>`)}
      ${step(2, t("Install the userscript"), `<p>${t("Tampermonkey opens an install screen: click Install there. The script is made for your Home Assistant ({origin}) and your shops.", { origin: esc(origin) })}</p><a class="btn" href="${esc(url)}" target="_blank" rel="noopener">⬇ ${t("Install userscript")}</a><p style="font-size:12px">${t("Adding shops or changing the language later? Install it again (Tampermonkey also updates it by itself).")}</p>`)}
      ${step(3, t("Create a token"), `<p>${t("In Home Assistant: your profile → Security → Long-lived access tokens → Create token (name e.g. “ARGUS userscript”). Copy the token, you only see it once.")}</p><a class="btn ghost" href="/profile/security" target="_blank" rel="noopener">${t("Go to profile → Security")} ↗</a>`)}
      ${step(4, t("Enter the token"), `<p>${t("In your browser click the Tampermonkey icon → ARGUS settings. The address is already filled in ({origin}); then paste the token.", { origin: esc(origin) })}</p>`)}
      ${step(5, t("Test"), `<p>${t("Open a product page of a product you track (click a product → Shops → “open ↗”). After a few seconds a green message appears at the bottom right, and “✅ Works” appears above.")}</p>`)}
      ${step(6, t("Switch on the continuous check"), `<p>${t("Come back to this page (reload it once after installing) and press “Switch on in this browser” above, or use the Tampermonkey menu → “Continuous check: switch on / off”. The setting is kept in Tampermonkey: it starts again by itself every time you open Home Assistant in this browser.")}</p>`)}
      ${step(7, t("Keep it running"), `<p>${t("The check only runs while a Home Assistant tab is open (any page of Home Assistant). Tips:")}</p><ul style="margin:0;padding-left:18px;font-size:13px">
        <li>${t("Pin a tab with Home Assistant (right-click the tab → Pin).")}</li>
        <li>${t("Chrome: Settings → Performance → Memory Saver → “Always keep these sites active” → add {origin}. Edge: Settings → System and performance → Sleeping tabs → “Never put these sites to sleep”.", { origin: esc(origin) })}</li>
        <li>${t("A computer that sleeps stops the check; it continues when it wakes up. Several tabs or windows are fine: only one tab of a browser does the work.")}</li>
        <li>${t("Several browsers or computers may run it too: each paces itself, so keep it to one or two.")}</li></ul>`)}
      ${step(8, t("Check that it works"), `<p>${t("Above you see “a browser is checking” with its last sign of life and what it is doing. In the logbook the entries have the source “relay”, and the prices get the mark ⓤ.")}</p>`)}
      </div>
      <div class="panel" style="margin-top:16px"><h3>🛠 ${t("If it doesn't work")}</h3><ul style="margin:0;padding-left:18px">
        <li><b>${t("“userscript not detected in this browser”")}</b>: ${t("reload this page; in Chrome/Edge switch on “Allow user scripts” for Tampermonkey (Extensions → Tampermonkey → Details); check that the script is enabled in the Tampermonkey dashboard.")}</li>
        <li><b>${t("“no token yet” or HTTP 401")}</b>: ${t("enter the token again via the Tampermonkey menu → ARGUS settings; a revoked token stops everything.")}</li>
        <li><b>${t("A shop keeps failing")}</b>: ${t("some shops block your browser too, or load their search results with JavaScript (then nothing can be found by searching). Open the shop under Shops & jobs to see why, and paste the product link in the product yourself.")}</li>
        <li><b>${t("Nothing happens")}</b>: ${t("the browser relay may be off under Settings; or there is simply nothing to do (it looks again every 10 minutes).")}</li></ul></div>
      <div class="panel" style="margin-top:16px"><h3>🔒 ${t("Security")}</h3><p>${t("The script contains no token: that is only stored in Tampermonkey on your device. It only runs on the shop domains in your list and on your Home Assistant pages (for the browser relay), and only sends the barcode, URL, title and price to your own Home Assistant. You can revoke the token in your profile at any time.")}</p></div>`;
  }
  vShops() {
    const st = this.state.data.retailer_stats || {};
    const cards = Object.entries(st).map(([rid, r], i) => {
      const ratio = r.offers ? r.ok / r.offers : 0;
      const state = !r.enabled ? ["", t("disabled")] : r.paused_hours > 0 ? ["bad", t("paused ({time})", { time: dur(r.paused_hours * 3600) })] : r.errors ? ["warn", t(r.errors > 1 ? "{n} errors" : "{n} error", { n: r.errors })] : ["", r.offers ? t("works") : t("no links")];
      return `<div class="shop click" style="--i:${i}" data-shop="${esc(rid)}" tabindex="0" title="${esc(t("Click for the last requests of this shop: what was asked, what came back and why it failed"))}"><h4><span class="dotst ${state[0]}"></span>${esc(r.label)}</h4><div class="muted" style="font-size:13px">${state[1]}${r.paused_hours > 0 ? ` <button class="btn ghost sm" data-resume="${esc(rid)}">▶ ${t("Resume")}</button>` : ""}</div>
        <div class="meter"><i style="width:${Math.round(ratio * 100)}%"></i></div>
        <div class="kv"><span>${t("Links")}</span><b>${r.offers}</b></div><div class="kv"><span>${t("With a price")}</span><b>${r.ok}</b></div><div class="kv"><span>${t("Cheapest for")}</span><b>${t("{n} products", { n: r.cheapest })}</b></div><div class="kv"><span>${t("Last success")}</span><b>${ago(r.last_ok)}</b></div>
        ${r.errors ? `<a class="muted" style="font-size:12px;cursor:pointer" data-shoplog="${esc(rid)}">📜 ${t("Show failed checks")} →</a>` : ""}</div>`;
    }).join("");
    const failing = Object.entries(st).flatMap(([rid, r]) => (r.failing || []).map((f) => ({ ...f, rid, shop: r.label })));
    const d = this.state.data, last = d.last;
    const lastTxt = last ? `${esc(tx(last.label))}: ${last.cancelled ? t("stopped") : t("done")} ${ago(last.finished)} · ${last.done}/${last.total}${last.updated ? ` · ${t("{n} updated", { n: last.updated })}` : ""}${last.found ? ` · ${t("{n} found", { n: last.found })}` : ""}${last.errors ? ` · ${t("{n} errors", { n: last.errors })}` : ""}` : t("no job run since the last restart");
    const pausedTxt = Object.entries(d.paused || {}).map(([k, h]) => `${esc(k)} (${dur(h * 3600)})`).join(", ");
    const actions = `<div class="panel"><h3>⚡ ${t("Actions")}</h3><div class="actions">
      <div class="action"><b>🔎 ${t("Find missing shop links")}</b><p>${t("Searches the shops of the product's category for a product page of each product without a link. Every title found is checked for the barcode, accessories and knock-off brands.")}</p><button class="btn" data-act="discover">${t("Find links")}</button></div>
      <div class="action"><b>↻ ${t("Refresh shop prices")}</b><p>${t("Fetches the price for every linked page. Shops are queried in parallel, each shop calmly one after another.")}</p><button class="btn" data-act="refresh" ${this.fullRefreshAttr("")}>${t("Refresh prices")}</button></div>
      <div class="action"><b>🔗 ${t("Check links")}</b><p>${t("Judges all links again and shows suspicious or unchecked links, so you can approve or replace them.")}</p><button class="btn" data-goto="manage/links">${t("Go to link check")}</button></div></div></div>
      <div class="panel"><h3>⏰ ${t("Automatic checks")}</h3><p>${this.scheduleLine()} <a data-goto="manage/settings" style="cursor:pointer">${t("Change under Settings")} →</a></p>
      <p><b>${t("Last job:")}</b> ${lastTxt}</p>${pausedTxt ? `<p><b>${t("Paused after a block:")}</b> ${pausedTxt}. ${t("With the buttons you can choose to try anyway.")} <button class="btn ghost sm" data-resume="">▶ ${t("Lift all pauses")}</button></p>` : ""}</div>`;
    return `${this.shopSettingsPanel()}${actions}<div class="panel"><h3>🏪 ${t("Shop status")}<span class="hsp"></span><span class="pill">${esc(this.state.data.transport)}</span></h3><p>${t("After a block a shop is paused automatically for a while (1 → 3 → 6 → 12 → 24 h) so the protection doesn't get stricter.")}</p></div>
      <div class="shops">${cards}</div>
      <div class="panel" style="margin-top:16px"><h3>⚠️ ${t("Offers without a price")} <span class="muted" style="font-weight:400">${failing.length}</span><span class="hsp"></span>${failing.length ? `<a class="btn ghost sm" data-goto="log/errors">${t("Fix in the logbook")} →</a>` : ""}</h3>${failing.length ? `<div class="tscroll"><table class="tbl"><tr><th>${t("Product")}</th><th>${t("Shop")}</th><th>${t("Message")}</th></tr>${failing.map((f) => `<tr class="click" data-set="${esc(f.product)}"><td><b>${esc(f.name || f.product)}</b></td><td>${esc(f.shop)}</td><td class="err">${esc(tx(f.error))}${f.suspect != null ? ` ${approveBtn(f.product, f.rid, f.suspect)}` : ""}</td></tr>`).join("")}</table></div>` : `<p class="ok">${t("All OK.")}</p>`}</div>
      <div class="panel"><h3>🧩 ${t("Does a shop keep blocking?")}</h3><p>1. ${t("Enter the price by hand: click a product → Shops → price field. A manual price always wins.")}<br>2. ${t("Install the {link} in Tampermonkey: your own browser sends the price when you visit a product page.", { link: `<a data-goto="manage/userscript" style="cursor:pointer">${t("userscript")}</a>` })}<br>3. ${t("Or switch off “pause automatically” per shop under {link}.", { link: `<a data-goto="manage/settings" style="cursor:pointer">${t("Settings")}</a>` })}<br>4. ${t("Use the action {action} from an automation or n8n.", { action: "<code>argus.report_price</code>" })}</p></div>`;
  }
  /** The legal terms, in full (Manage → Legal, the import wizard and the one-time acceptance). */
  /** The legal terms, in full (Manage → Legal, the import wizard and the one-time acceptance). */
  legalHtml() {
    const sec = [
      ["About this software", "ARGUS (Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden) is free software that runs entirely on your own Home Assistant. It contains no list of shops or websites and contacts no website by itself: which websites are contacted is decided only by the shop settings you import or enter yourself."],
      ["Example settings", "The example shop settings file only shows how settings can be written. It is not a recommendation, not an instruction and not a statement that any website allows its pages to be read automatically. Whether and how you use it is your own decision."],
      ["Your responsibility", "Everything that happens between your Home Assistant and the websites in your settings (page requests, searches, the browser relay and the userscript) happens on your initiative, from your own network and under your own responsibility. You are responsible for respecting the terms of use of those websites, their robots.txt and the law that applies to you, including copyright, database rights, rules on unauthorised access to computer systems and consumer law. Use the software only for personal, non-commercial purposes and keep the number of requests moderate."],
      ["No warranty", "The software is provided \"as is\", without any warranty, express or implied, including fitness for a particular purpose and non-infringement. Prices, availability and deals can be wrong, incomplete or out of date, and a product found at another shop can be a different product: always check them at the shop before you buy."],
      ["Limitation of liability", "To the fullest extent permitted by the applicable law, the author and the contributors are not liable for any damage, loss, claim, fine or other consequence arising from the use of the software or of shop settings, including claims by website operators or other third parties. Such claims concern the user who chose and used the settings. Nothing in these terms limits a liability that cannot be limited by law."],
      ["Indemnity", "As far as the law allows, you hold the author and the contributors harmless from claims by third parties that arise from your use of the software or of your shop settings."],
      ["Trademarks", "Names of shops, websites and products are trademarks of their owners; this project is not affiliated with, sponsored or endorsed by any of them."],
      ["Your data", "Your products, prices and settings stay on your own Home Assistant. The software does not send your list or settings to its author; it only fetches a public news file to show news in the panel."],
      ["Acceptance and withdrawal", "By importing shop settings you confirm that you have read and accept these terms, that you bear all legal consequences of your settings and their use yourself, and that the author cannot be held liable. You can withdraw at any time under Manage → Legal: from then on no website from your settings is contacted."],
      ["No legal advice", "These terms are no legal advice. If you are unsure what is allowed where you live, ask a lawyer before you use shop settings."],
    ];
    return sec.map(([h, p]) => `<h4 style="margin:12px 0 4px">${t(h)}</h4><p style="margin:0">${t(p)}</p>`).join("");
  }
  shopSettingsPanel() {
    const ss = this.state.data.shop_settings || {};
    const when = ss.accepted ? new Date(ss.accepted * 1000).toLocaleString(LANG) : null;
    const state = ss.ready ? `✅ ${t("{n} shops from your shop settings; terms accepted on {when}.", { n: ss.shops, when: esc(when) })}`
      : ss.imported ? `⚠️ ${t("Shop settings present, terms not accepted yet: nothing is fetched.")}` : `⚠️ ${t("No shop settings imported: nothing is fetched.")}`;
    return `<div class="panel"><h3>🗂️ ${t("Shop settings")}</h3><p>${state}</p><p class="muted">${t("Which shops your Home Assistant contacts, with their addresses and categories, comes from a shop settings file you import. Export it to keep a copy or to move it to another installation.")}</p>
      <button class="btn" id="ss_import">⬆ ${t("Import shop settings")}</button> ${ss.imported && !ss.ready ? `<button class="btn" id="ss_accept">⚖️ ${t("Read and accept")}</button> ` : ""}${ss.imported ? `<button class="btn ghost" id="ss_export">⬇ ${t("Export shop settings")}</button> <button class="btn ghost" id="ss_withdraw">✋ ${t("Withdraw and stop fetching")}</button>` : ""}</div>`;
  }
  /** Manage → About ARGUS: what the name stands for, the version, the notice and links. */
  /** Manage → About ARGUS: what the name stands for, the version, the notice and links. */
  vAbout() {
    const d = this.state.data || {}, v = d.version || "";
    const letters = [["A", "Altijd", "Always", "Always looking around: every shop of the right category is searched for your product."],
      ["R", "Rondkijken", "Look around", "Not only one shop: ARGUS compares the same product (checked by barcode) over many shops."],
      ["G", "Goedkoopste", "Cheapest", "The cheapest offer is picked out, with a history chart so you see whether it is really a good price."],
      ["U", "Uitzoeken", "Pick", "Deal score, target price and the lowest point of the past months tell you when to buy."],
      ["S", "Snel", "Quickly", "Quickly told: a notification as soon as the price drops below your target or below its lowest point."],
      ["", "Melden", "Report", "Reported by notification, daily digest, ticker and Home Assistant sensors."]];
    return `<div class="panel about"><div class="about-head"><img src="/argus_static/logo.png${v ? `?v=${encodeURIComponent(v)}` : ""}" alt="ARGUS" class="about-logo">
        <div><h2 style="margin:0">ARGUS</h2><div class="muted">Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden</div>
        <div style="margin-top:6px">${t("ARGUS watches the price of a product over several shops, keeps a price history chart and alerts you when the price drops below your target or below the lowest point of the past months. Like the Greek giant with a hundred eyes, never all of them asleep at once.")}</div>${v ? `<div class="muted" style="font-size:13px;margin-top:4px">${t("Version {version}", { version: esc(v) })}</div>` : ""}</div></div></div>
      <div class="panel"><h3>👁 ${t("What the name stands for")}</h3><div class="about-letters">${letters.map(([l, w, en, d]) => `<div class="about-letter"><b class="about-l">${l || "…"}</b><div><b>${esc(w)}</b> <span class="muted">· ${t(en)}</span><div style="font-size:13px">${t(d)}</div></div></div>`).join("")}</div></div>
      <div class="panel"><h3>👤 ${t("Who makes ARGUS?")}</h3>
        <p>${t("ARGUS is made by {name} from Belgium, a Home Assistant user who wanted to keep an eye on prices without checking shop after shop. I work on it in my spare time, together with a group of beta testers whose reports make it better every week.", { name: "<b>Emery Frijters</b>" })}</p>
        <p class="muted" style="font-size:13px">${t("Found a bug or have an idea? Preferably report it on GitHub, so others can follow along.")}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><a class="btn ghost sm" href="https://github.com/emeryf81" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
          <a class="coffee" href="https://www.buymeacoffee.com/emeryf" target="_blank" rel="noopener noreferrer">☕ ${t("Buy me a coffee")}</a></div></div>
      <div class="panel"><h3>ℹ️ ${t("About this software")}</h3><p>${t("Free software that runs entirely on your own Home Assistant: your products, prices and settings stay with you. It contains no list of shops; you choose which websites it contacts in your shop settings.")}</p>
        <p class="muted" style="font-size:13px">${t("ARGUS is independent software. The names of shops, websites and products belong to their owners.")}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn ghost sm" href="https://github.com/emeryf81/argus" target="_blank" rel="noopener noreferrer">GitHub ↗</a><a class="btn ghost sm" href="https://github.com/emeryf81/argus/issues" target="_blank" rel="noopener noreferrer">${t("Report a problem or an idea")} ↗</a><button class="btn ghost sm" data-goto="manage/legal" type="button">⚖️ ${t("Legal")}</button></div></div>`;
  }
  vLegal() {
    return `${this.shopSettingsPanel()}<div class="panel"><h3>⚖️ ${t("Legal information")}</h3>${this.legalHtml()}<p class="muted" style="margin-top:12px">${t("Terms version {v}.", { v: (this.state.data.shop_settings || {}).legal_version || 1 })}</p></div>`;
  }
  /** First step (no shop settings yet: import + accept) or the one-time acceptance (settings carried over). */
  /** First step (no shop settings yet: import + accept) or the one-time acceptance (settings carried over). */
  openShopSettings(forceImport = false) {
    const ss = (this.state.data || {}).shop_settings || {}, accept = ss.imported && !ss.ready && !forceImport;
    const dlg = this.shadowRoot.getElementById("dlg");
    this._dlgGen = (this._dlgGen || 0) + 1; clearInterval(this._shopTimer);
    let payload = null;
    const intro = accept ? t("Your shop settings are present, but before anything is fetched you have to read and accept the terms below once.")
      : t("ARGUS contains no shops of its own: you choose which websites your Home Assistant contacts by importing a shop settings file. An example file shows how such a file is written.");
    dlg.innerHTML = `<div class="dhead" style="grid-template-columns:1fr auto"><div><h2>⚖️ ${t(accept ? "Accept the terms" : "Import shop settings")}</h2><div class="muted">${t("Nothing is fetched until you agree.")}</div></div><div><button class="x" id="x" aria-label="${t("Not now")}" title="${t("Not now")}">✕</button></div></div>
      <div class="dbody"><p>${intro}</p>
      ${accept ? `<p><b>${t("Shops in your settings:")}</b> ${Object.values(this.state.data.retailers || {}).map(esc).join(", ")}</p>`
        : `<label class="drop" id="ss_drop" style="padding:18px;display:block"><span class="big" style="font-size:26px">🗂️</span><span id="ss_name">${t("Choose or drop a shop settings file (.json)")}</span><input type="file" id="ss_file" accept=".json,application/json" hidden></label>
      <p class="muted"><a href="https://github.com/emeryf81/argus/blob/main/examples/argus-shops.example.json" target="_blank" rel="noopener noreferrer">${t("Example of a shop settings file")} ↗</a></p><div id="ss_info"></div>`}
      <div style="max-height:260px;overflow:auto;border:1px solid var(--ar-line);border-radius:10px;padding:4px 12px 12px;margin:10px 0;font-size:13px">${this.legalHtml()}</div>
      <label class="chk" style="display:flex;gap:8px;align-items:flex-start;margin:10px 0"><input type="checkbox" id="ss_ok" style="margin-top:3px"> <span>${t("I have read and accept these terms. I alone am responsible for what my Home Assistant does with these shop settings and I bear all legal consequences; the author of ARGUS cannot be held liable.")}</span></label>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="ss_go" disabled>${t(accept ? "Accept" : "Import")}</button><button class="btn ghost" id="ss_later">${t("Not now")}</button>${accept ? `<button class="btn ghost" id="ss_other">⬆ ${t("Import other shop settings")}</button>` : ""}</div></div>`;
    if (!dlg.open) dlg.showModal();
    const q = (id) => dlg.querySelector("#" + id), ok = q("ss_ok"), go = q("ss_go");
    const sync = () => { go.disabled = !ok.checked || (!accept && !payload); };
    ok.onchange = sync;
    q("x").onclick = q("ss_later").onclick = () => this.closeDialog();
    if (q("ss_other")) q("ss_other").onclick = () => this.openShopSettings(true);
    if (!accept) {
      const drop = q("ss_drop");
      const pick = async (f) => {
        if (!f) return;
        try {
          const j = JSON.parse(await f.text());
          if (!j || !["argus-shop-settings"].includes(j.format) || !Array.isArray(j.shops)) throw new Error("format");
          payload = j; q("ss_name").textContent = f.name;
          q("ss_info").innerHTML = `<p><b>${t("{n} shops", { n: j.shops.length })}:</b> ${j.shops.map((x) => esc(x.name || x.id)).join(", ")}${(j.finders || []).length ? `<br><b>${t("{n} finders", { n: j.finders.length })}:</b> ${j.finders.map((x) => esc(x.name || x.id)).join(", ")}` : ""}</p>`;
        } catch (e) { payload = null; q("ss_info").innerHTML = ""; this.toast(t("This is not a shop settings file for this integration."), "err"); }
        sync();
      };
      ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", (e) => pick(e.dataTransfer.files[0])); q("ss_file").addEventListener("change", (e) => pick(e.target.files[0]));
    }
    go.onclick = () => this.busy(go, "…", async () => {
      if (accept) await this._hass.callWS({ type: "argus/shop_settings/accept", accept: ok.checked });
      else { const r = await this._hass.callWS({ type: "argus/shop_settings/import", settings: payload, accept: ok.checked }); this.toast(t("{n} shops imported", { n: r.shops }), "ok"); }
      this.closeDialog(); await new Promise((res) => setTimeout(res, 1500)); await this.load();
    });
  }
  vBackup() {
    return `<div class="two"><div class="panel"><h3>⬇ ${t("Export")}</h3><p>${t("Full backup (products, shop links, price history, timeline) as JSON, or only your products as CSV (can be imported again).")}</p><button class="btn" id="expjson">⬇ ${t("Backup (JSON)")}</button> <button class="btn ghost" id="expcsv">⬇ ${t("Products (CSV)")}</button></div>
      <div class="panel"><h3>⬆ ${t("Restore")}</h3><p>${t("The backup is fully checked first (structure, barcodes, URLs, price history) before anything changes.")}</p><label class="drop" id="jdrop" style="padding:18px"><span class="big" style="font-size:26px">🗂️</span><span id="jname">${t("Choose or drop a backup file (.json)")}</span><input type="file" id="jsonfile" accept=".json,application/json" hidden></label>
      <label class="chk" style="display:flex;gap:8px;align-items:center;margin:10px 0"><input type="checkbox" id="merge" checked> ${t("merge with the current data (otherwise: replace everything)")}</label><button class="btn" id="impjson" disabled>${t("Restore")}</button></div></div>`;
  }

  // ---------------------------------------------------------------- events
  // ---------------------------------------------------------------- events
  bindCards(root) {
    root.querySelectorAll("[data-set]").forEach((el) => {
      el.addEventListener("click", (e) => { if (e.target.closest("[data-stop]")) return; this.openSet(el.dataset.set); });
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") this.openSet(el.dataset.set); });
    });
  }
  /** Settings → Colours: a slider (and swatches) to switch the colours of the whole panel, in this browser. */
  colorsPanel() {
    const cur = this.colorTheme(), i = COLOR_THEMES.findIndex(([k]) => k === cur);
    return `<div class="panel"><h3>🎨 ${t("Colours")}</h3><p>${t("Slide to switch the colours of the whole panel. “Home Assistant” (the default) follows the theme of your Home Assistant; the choice is kept in this browser.")}</p>
      <label style="display:block"><b id="col_name">${esc(t(COLOR_THEMES[i][1]))}</b><input type="range" class="colrange" id="col_range" min="0" max="${COLOR_THEMES.length - 1}" step="1" value="${i}" aria-label="${esc(t("Colours"))}"></label>
      <div class="colrow">${COLOR_THEMES.map(([k, l, sw], j) => `<button class="colsw${k === cur ? " on" : ""}" data-col="${j}" type="button"><i>${sw.map((c) => `<b style="background:${c}"></b>`).join("")}</i>${esc(t(l))}</button>`).join("")}</div></div>`;
  }
  bindColors(root) {
    const rng = root.querySelector("#col_range"); if (!rng) return;
    const pick = (j) => {
      const [k, l] = COLOR_THEMES[j];
      try { if (k === "ha") localStorage.removeItem("argus_colors"); else localStorage.setItem("argus_colors", k); } catch (e) { /* private window */ }
      this.applyColors(k); rng.value = j; root.querySelector("#col_name").textContent = t(l);
      root.querySelectorAll(".colsw").forEach((b) => b.classList.toggle("on", +b.dataset.col === j));
    };
    rng.addEventListener("input", () => pick(+rng.value));
    root.querySelectorAll(".colsw").forEach((b) => b.onclick = () => pick(+b.dataset.col));
  }
  bindSettings(root, $) {
    this.bindColors(root);
    const lines = (v) => v.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);
    let ft;
    const ftest = () => { clearTimeout(ft); ft = setTimeout(async () => {
      const title = $("o_ftest").value.trim(), out = $("o_fres");
      if (!title) { out.textContent = ""; return; }
      try {
        const r = await this._hass.callWS({ type: "argus/filter/test", title, block_words: lines($("o_block").value), allow_words: lines($("o_allow").value) });
        out.className = "hint " + (r.word ? "bad" : "ok");
        out.textContent = r.word ? "🚫 " + t("skipped: “{word}”", { word: r.word }) : "✓ " + t("allowed (can be the product)");
      } catch (e) { out.textContent = String(e.message || e); }
    }, 300); };
    for (const id of ["o_ftest", "o_block", "o_allow"]) if ($(id)) $(id).addEventListener("input", ftest);
    const d = this.state.draft, st = this.state.settings;
    const syncShops = () => root.querySelectorAll("tr[data-shop]").forEach((tr) => {
      const x = d.shops.find((y) => y.id === tr.dataset.shop); if (!x) return;
      x.enabled = tr.querySelector(".s_on").checked; x.autopause = tr.querySelector(".s_ap").checked;
      const se = tr.querySelector(".s_search"); if (se) { x.search = se.value.trim() || x.default_search || ""; const c = d.custom.find((y) => y.id === x.id); if (c) c.search = x.search; }
    });
    const radios = (name) => root.querySelectorAll(`input[name=${name}]`).forEach((r) => r.addEventListener("change", () => r.closest(".radio").querySelectorAll("label").forEach((l) => l.classList.toggle("on", l.querySelector("input").checked))));
    radios("rmode");
    root.querySelectorAll("input[name=rmode]").forEach((r) => r.addEventListener("change", () => { d.mode = r.value; $("rm_spread").hidden = r.value !== "spread"; $("rm_times").hidden = r.value !== "times"; }));
    const rateHints = () => {
      const r = (this.state.data.schedule || {}).rates, fastN = r ? r.priority : this.products.filter((x) => (x.priority || 0) >= 2).length;
      const all = r ? r.products + r.priority : this.products.length, h = +$("o_spread").value, wm = +$("o_wcycle").value;
      const wh = wm ? Math.min(wm / 60, h) : 0, main = h >= 1 ? (wh ? all - fastN : all) / h : 0, fast = wh ? fastN / wh : 0;
      const f = (v) => (Math.round(v * 10) / 10).toLocaleString(LOC);
      $("o_spread_hint").textContent = t("≈ {n} products per hour", { n: f(main) }) + (wh ? ` (${t("{n} products", { n: all - fastN })})` : "");
      $("o_wcycle_hint").textContent = wh ? t("≈ {n} priority products per hour ({m} products)", { n: f(fast), m: fastN }) : "";
      $("o_total_hint").textContent = wh ? t("Together ≈ {n} checks per hour, each at every shop.", { n: f(main + fast) }) : "";
    };
    if ($("o_wcycle")) { rateHints(); $("o_wcycle").addEventListener("change", rateHints); $("o_spread").addEventListener("change", rateHints); }
    // search URLs: paste a result page, the search word becomes {query}; live example link
    root.querySelectorAll(".s_search").forEach((i) => {
      const tr = i.closest("tr"), x = d.shops.find((y) => y.id === tr.dataset.shop), prev = tr.querySelector(".s_prev"), reset = tr.querySelector(".s_reset");
      const upd = () => { prev.innerHTML = this.searchPreview(i.value.trim() || x.default_search); if (reset) reset.hidden = !x.default_search || (i.value.trim() || x.default_search) === x.default_search; };
      i.addEventListener("input", upd);
      i.addEventListener("change", () => { const v = this.toTemplate(i.value); if (v !== i.value.trim()) { i.value = v; this.toast(t("Search word replaced by {query}", { query: "{query}" }), "ok"); } upd(); });
    });
    root.querySelectorAll(".s_reset").forEach((b) => b.addEventListener("click", () => { const tr = b.closest("tr"), i = tr.querySelector(".s_search"), x = d.shops.find((y) => y.id === tr.dataset.shop); i.value = x.default_search; x.search = x.default_search; i.dispatchEvent(new Event("input")); }));
    root.querySelectorAll(".s_del").forEach((b) => b.addEventListener("click", () => { syncShops(); const id = b.closest("tr").dataset.shop; d.shops = d.shops.filter((x) => x.id !== id); d.custom = d.custom.filter((x) => x.id !== id); this.renderContent(); this.toast(t("Shop removed from the list; press Save to confirm")); }));
    const ns = $("n_search"); ns.addEventListener("change", () => { ns.value = this.toTemplate(ns.value); $("n_search_prev").innerHTML = this.searchPreview(ns.value.trim()); });
    ns.addEventListener("input", () => { $("n_search_prev").innerHTML = this.searchPreview(this.toTemplate(ns.value)); });
    $("n_add").addEventListener("click", () => {
      syncShops();
      const name = $("n_name").value.trim(), domain = $("n_domain").value.trim().replace(/^https?:\/\/(www\.)?/, "").split("/")[0].toLowerCase(), search = this.toTemplate($("n_search").value);
      if (!name || !/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(domain)) return this.toast(t("Enter a name and a valid domain (e.g. example-shop.be)"), "err");
      if (search && (!search.startsWith("https://") || !/\{(query|ean)\}/.test(search) || !search.includes(domain))) return this.toast(t("Search URL: https://, on the shop's domain and with {query}", { query: "{query}" }), "err");
      const id = "c_" + (name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "shop").slice(0, 30);
      if (d.shops.some((x) => x.id === id)) return this.toast(t("This shop is already in the list"), "err");
      const categories = [...root.querySelectorAll(".n_cat")].filter((c) => c.checked).map((c) => c.value);
      d.custom.push({ id, name, domain, search, categories: categories.length === Object.keys(st.categories).length ? [] : categories });
      d.shops.push({ id, label: name, builtin: false, generic: true, domain, search, categories, enabled: true, autopause: true, paused_hours: 0, blocks: 0 });
      this.renderContent(); this.toast(t("{name} added; press Save", { name }), "ok");
    });
    $("o_save").addEventListener("click", () => {
      syncShops();
      const f = {
        notify_service: $("o_notify").value.trim(),
        digest_time: $("o_digest").value, refresh_mode: d.mode, spread_hours: +$("o_spread").value, watch_cycle_min: +$("o_wcycle").value,
        ...(d.mode === "times" ? { refresh_times: $("o_times").value } : {}), use_impersonation: $("o_imp").checked,
        retailers: d.shops.filter((x) => x.enabled).map((x) => x.id), no_autopause: d.shops.filter((x) => !x.autopause).map((x) => x.id),
        custom_shops: d.custom, shop_search: Object.fromEntries(d.shops.filter((x) => x.builtin).map((x) => [x.id, x.search === x.default_search ? "" : this.toTemplate(x.search || "")])),
        language: $("o_lang").value,
      };
      // a number field some phone keyboards leave empty: keep the saved number instead of 0
      const tkn = (k) => { const v = parseInt(String($("o_tkn_" + k).value).replace(/\D/g, ""), 10); return Number.isFinite(v) ? Math.max(0, Math.min(50, v)) : ((st.ticker || {})["max_" + k] ?? 3); };
      f.ticker = { ...Object.fromEntries(["drops", "deals", "news"].flatMap((k) => [[k, $("o_tk_" + k).checked], ["max_" + k, tkn(k)]])), shuffle: $("o_tk_shuffle").checked };
      if (st.finders && st.finders.length) f.finders = [...root.querySelectorAll(".f_on")].filter((c) => c.checked).map((c) => c.value);
      f.browser_relay = $("o_relay").checked; f.relay_hours = +$("o_relayh").value || 6;
      f.block_words = lines($("o_block").value); f.allow_words = lines($("o_allow").value);
      if (!f.retailers.length) return this.toast(t("Switch on at least one shop"), "err");
      if (d.mode === "spread" && !(f.spread_hours >= 1 && f.spread_hours <= 168)) return this.toast(t("Cycle: between 1 and 168 hours"), "err");
      const langChanged = f.language !== st.language;
      this.busy($("o_save"), t("Saving…"), async () => {
        await this._hass.callWS({ type: "argus/settings/set", fields: f });
        this._tickerAt = 0;                                // the ticker follows the new settings
        await new Promise((r) => setTimeout(r, 1500));   // entry reloads
        this.state.settings = null; this.state.logv.data = null; await this.load(langChanged);
        this.toast(t("Settings saved"), "ok");
      });
    });
  }
  hookCharts(root) {
    root.querySelectorAll("svg.chart").forEach((svg) => {
      const m = CHARTS[svg.dataset.id]; if (!m) return;
      const tip = svg.parentElement.querySelector(".tip"), hv = svg.querySelector(".hv");
      const move = (clientX) => {
        const box = svg.getBoundingClientRect(), x = ((clientX - box.left) / box.width) * m.W;
        if (x < m.P.l || x > m.W - m.P.r) return;
        const t = m.x0 + ((x - m.P.l) / (m.W - m.P.l - m.P.r)) * (m.x1 - m.x0);
        const rows = m.series.map((s) => { const p = lastAt(s.points, t); return p ? `<div><i style="background:${s.color}"></i>${esc(s.name)}: <b>${m.money ? EUR(p[1]) : p[1]}</b></div>` : ""; }).join("");
        hv.setAttribute("x1", m.sx(t)); hv.setAttribute("x2", m.sx(t)); hv.style.display = "";
        tip.innerHTML = `<div class="muted" style="margin-bottom:3px">${DATE(t, { day: "numeric", month: "short", year: "numeric" })}</div>${rows}`;
        tip.style.display = ""; tip.style.left = Math.min(box.width - 200, Math.max(40, clientX - box.left + 14)) + "px";
      };
      if (m.zoom) {             // drag across the chart to zoom in on that period
        const sel = svg.querySelector(".zsel"), tAt = (clientX) => { const box = svg.getBoundingClientRect(), x = Math.min(m.W - m.P.r, Math.max(m.P.l, ((clientX - box.left) / box.width) * m.W)); return [x, m.x0 + ((x - m.P.l) / (m.W - m.P.l - m.P.r)) * (m.x1 - m.x0)]; };
        let start = null;
        svg.addEventListener("pointerdown", (e) => { if (e.button > 0) return; start = tAt(e.clientX); try { svg.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ } });
        svg.addEventListener("pointermove", (e) => { if (!start) return; const [x] = tAt(e.clientX); sel.setAttribute("x", Math.min(x, start[0])); sel.setAttribute("width", Math.abs(x - start[0])); sel.style.display = ""; });
        const end = (e) => { if (!start) return; const [x, t1] = tAt(e.clientX), [x0, t0] = start; start = null; sel.style.display = "none"; if (Math.abs(x - x0) > 12) m.zoom(Math.min(t0, t1), Math.max(t0, t1)); };
        svg.addEventListener("pointerup", end); svg.addEventListener("pointercancel", () => { start = null; sel.style.display = "none"; });
      }
      svg.addEventListener("mousemove", (e) => move(e.clientX));
      svg.addEventListener("touchmove", (e) => move(e.touches[0].clientX), { passive: true });
      svg.addEventListener("mouseleave", () => { tip.style.display = "none"; hv.style.display = "none"; });
    });
  }

  // ---------------------------------------------------------------- edit all (Manage → Edit all)
  /** A working copy of every set (and every copy you own), edited in place and saved in one go. */
  // ---------------------------------------------------------------- parser lab (Manage → Parser lab)
  // ---------------------------------------------------------------- edit all (Manage → Edit all)
  /** A working copy of every set (and every copy you own), edited in place and saved in one go. */
  // ---------------------------------------------------------------- parser lab (Manage → Parser lab)
  labRuns() {
    if (!this._labRuns) { try { this._labRuns = JSON.parse(localStorage.getItem("argus_lab") || "[]"); } catch (e) { this._labRuns = []; } }
    return this._labRuns;
  }
  saveLabRuns() { try { localStorage.setItem("argus_lab", JSON.stringify(this._labRuns.slice(0, 50))); } catch (e) { /* private window */ } }
  /** One result: verdict, what was read, the analysis in plain words and the amounts found on the page. */
  /** One result: verdict, what was read, the analysis in plain words and the amounts found on the page. */
  labResultHtml(r) {
    const verdict = { ok: ["ok", "✅", t("Price read")], unavailable: ["warn", "ℹ️", t("No price on purpose (not in stock / out of the range)")],
      suspect: ["warn", "⚠️", t("Price read, but it looks wrong")], no_price: ["bad", "⛔", t("No price read")],
      blocked: ["bad", "🛡️", t("Blocked by the shop")], error: ["bad", "⛔", t("Page not fetched")] }[r.verdict] || ["", "", r.verdict];
    const icon = { ok: "✅", info: "ℹ️", warn: "⚠️", bad: "⛔" };
    const row = (k, v) => (v == null || v === "" ? "" : `<div class="kv"><span>${k}</span><b>${v}</b></div>`);
    return `<div class="labres lv-${verdict[0]}"><h4 style="margin:0 0 8px">${verdict[1]} ${esc(verdict[2])}${r.price != null ? ` · ${EUR(r.price)}` : ""}</h4>
      <div class="labgrid"><div>
        ${row(t("Shop"), esc(r.shop || r.retailer))}${row(t("Product"), esc(r.id || ""))}
        ${row(t("Address"), r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url.slice(0, 70))} ↗</a>` : (r.pasted ? t("pasted HTML") : ""))}
        ${row(t("Title"), esc(r.title || ""))}${row(t("Price"), r.price != null ? EUR(r.price) : "–")}${row(t("Regular price"), r.list_price != null ? EUR(r.list_price) : "")}
        ${row(t("reference price"), r.ref_price != null ? EUR(r.ref_price) : "")}${row(t("Last price of this link"), r.known != null ? EUR(r.known) : "")}
        ${row("HTTP", r.status != null ? esc(r.status) : "")}${row(t("Size"), r.size ? `${Math.round(r.size / 1024)} KB` : "")}${row(t("Time"), r.ms ? `${r.ms} ms` : "")}
        ${row(t("Ended up at"), r.final_url && r.final_url !== r.url ? esc(r.final_url.slice(0, 90)) : "")}${row(t("Error"), r.error ? esc(tx(r.error)) : "")}
      </div>${r.image ? `<img src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" style="max-width:120px;max-height:120px;object-fit:contain;border-radius:8px;background:#fff">` : ""}</div>
      <h4 style="margin:12px 0 6px">🧠 ${t("Analysis")}</h4><ul class="labfind">${(r.findings || []).map((f) => `<li class="lv-${esc(f.level)}"><span>${icon[f.level] || "•"}</span> ${esc(tx(f.text))}</li>`).join("")}</ul>
      ${(r.amounts || []).length ? `<details><summary style="cursor:pointer">${t("Amounts found on the page ({n})", { n: r.amounts.length })}</summary><table class="tbl" style="margin-top:6px">${r.amounts.map((a) => `<tr><td class="num"><b>${EUR(a.price)}</b></td><td class="num muted">×${a.count}</td><td class="muted" style="font-size:12px">…${esc(a.context)}…</td></tr>`).join("")}</table></details>` : ""}
      ${r.head ? `<details><summary style="cursor:pointer">${t("Start of the page (HTML)")}</summary><pre class="labhead">${esc(r.head)}</pre></details>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button class="btn ghost sm" data-lablog="${esc(String(r.ts))}" type="button">📜 ${t("Send to the logbook")}</button>
        <button class="btn ghost sm" data-labcsv="${esc(String(r.ts))}" type="button">⬇ ${t("Export (CSV)")}</button></div></div>`;
  }
  vLab() {
    const L = (this.state.lab = this.state.lab || { shop: "", num: "", url: "", paste: false, links: null, cur: null }), runs = this.labRuns();
    const shops = Object.entries(this.state.data.retailers).sort((a, b) => a[1].localeCompare(b[1]));
    const sets = this.products.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    const lk = L.links || {}, chip = (k, label) => (lk[k] ? `<button class="chip${L.url === lk[k] ? " on" : ""}" data-labchip="${esc(lk[k])}" type="button">${label}</button>` : "");
    const verdictIcon = { ok: "✅", unavailable: "ℹ️", suspect: "⚠️", no_price: "⛔", blocked: "🛡️", error: "⛔" };
    return `<div class="panel"><h3>🔬 ${t("Parser lab")}</h3>
      <p>${t("Test how a shop page is read: pick a shop and a product, the address is filled in (your link, the product page or the shop's search page). Change it if you like, then fetch it. You see what is read and, below it, an analysis of what goes wrong when there is no price or a price that looks wrong.")}</p>
      <div class="form labform">
        <label>${t("Shop")}<select id="lb_shop"><option value="">–</option>${shops.map(([k, v]) => `<option value="${esc(k)}" ${L.shop === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <label>${t("Product")}<select id="lb_num"><option value="">–</option>${sets.map((x) => `<option value="${esc(x.id)}" ${L.num === x.id ? "selected" : ""}>${esc((x.name || x.id).slice(0, 60))}</option>`).join("")}</select></label>
        <label style="grid-column:1/-1">${t("Address")}<input id="lb_url" value="${esc(L.url)}" placeholder="https://…" inputmode="url"></label>
      </div>
      <div class="chips" style="margin:6px 0 10px">${chip("link", "🔗 " + t("Your link"))}${chip("product", "👁 " + t("Product page"))}${chip("search", "🔍 " + t("Search page"))}</div>
      <label class="chk" style="display:flex;gap:6px;align-items:center;margin-bottom:8px"><input type="checkbox" id="lb_paste" ${L.paste ? "checked" : ""}> ${t("Paste the HTML myself (e.g. from your browser: right-click → View page source)")}</label>
      <textarea id="lb_html" rows="5" ${L.paste ? "" : "hidden"} style="width:100%;font-family:monospace;font-size:12px" placeholder="&lt;html&gt;…"></textarea>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="btn" id="lb_go" type="button">🔬 ${t("Test and analyse")}</button></div>
      <div id="lb_res" style="margin-top:12px">${L.cur ? this.labResultHtml(L.cur) : ""}</div></div>
      <div class="panel"><h3>🗂️ ${t("Tests in this browser ({n})", { n: runs.length })}</h3>
        ${runs.length ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px"><button class="btn ghost sm" id="lb_csv" type="button">⬇ ${t("Export all (CSV)")}</button><button class="btn ghost sm" id="lb_logall" type="button">📜 ${t("Send the failed ones to the logbook")}</button><button class="btn ghost sm" id="lb_clear" type="button">🗑 ${t("Clear")}</button></div>
        <div class="tscroll"><table class="tbl"><tr><th>${t("Time")}</th><th>${t("Shop")}</th><th>${t("Product")}</th><th></th><th class="num">${t("Price")}</th><th>${t("Analysis")}</th></tr>${runs.map((r) => `<tr class="click" data-labopen="${esc(String(r.ts))}"><td class="muted" style="white-space:nowrap">${DATE(r.ts, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td><td>${esc(r.shop || r.retailer)}</td><td><b>${esc(r.id || "")}</b></td><td>${verdictIcon[r.verdict] || ""}</td><td class="num">${r.price != null ? EUR(r.price) : "–"}</td><td class="ell muted" style="font-size:12px;max-width:360px">${esc(tx(((r.findings || []).find((f) => f.level === "bad" || f.level === "warn") || (r.findings || [])[0] || {}).text || ""))}</td></tr>`).join("")}</table></div>`
        : `<p class="muted">${t("No tests yet. Every test is kept here (in this browser) so you can compare and export them.")}</p>`}</div>`;
  }
  labCsv(runs) {
    const cell = (v) => { const x = v == null ? "" : String(v); return /[";\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x; };
    const head = ["time", "shop", "set", "url", "http", "verdict", "price", "regular_price", "ref_price", "last_price", "title", "size_kb", "ms", "final_url", "error", "analysis", "amounts"];
    const rows = runs.map((r) => [new Date(r.ts * 1000).toISOString(), r.shop || r.retailer, r.id, r.url, r.status, r.verdict, r.price, r.list_price, r.ref_price, r.known, r.title,
      r.size ? Math.round(r.size / 1024) : "", r.ms, r.final_url, r.error, (r.findings || []).map((f) => `[${f.level}] ${tx(f.text)}`).join(" | "),
      (r.amounts || []).map((a) => `${a.price}×${a.count}`).join(" ")].map(cell).join(";"));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + [head.join(";"), ...rows].join("\n")], { type: "text/csv;charset=utf-8" }));
    a.download = `argus-parser-lab-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  bindLab(root, $) {
    const L = this.state.lab, ws = (args) => this._hass.callWS({ type: "argus/lab", ...args });
    const fill = async () => {
      L.links = null;
      if (L.shop && L.num) {
        try { L.links = await ws({ action: "links", retailer: L.shop, product: L.num }); L.url = L.links.suggested || L.url; } catch (e) { this.toast(tx(e.message), "err"); }
      }
      this.renderContent();
    };
    $("lb_shop").onchange = (e) => { L.shop = e.target.value; fill(); };
    $("lb_num").onchange = (e) => { L.num = e.target.value; fill(); };
    $("lb_url").oninput = (e) => { L.url = e.target.value; };
    $("lb_paste").onchange = (e) => { L.paste = e.target.checked; $("lb_html").hidden = !L.paste; };
    root.querySelectorAll("[data-labchip]").forEach((b) => b.onclick = () => { L.url = b.dataset.labchip; this.renderContent(); });
    const find = (ts) => (L.cur && String(L.cur.ts) === ts ? L.cur : this.labRuns().find((r) => String(r.ts) === ts));
    const toLog = async (r) => { const { head, ...rest } = r; await ws({ action: "log", result: rest }); };
    const bindRes = (el) => {
      el.querySelectorAll("[data-lablog]").forEach((b) => b.onclick = () => this.busy(b, "…", async () => { await toLog(find(b.dataset.lablog)); this.toast(t("In the logbook"), "ok"); }));
      el.querySelectorAll("[data-labcsv]").forEach((b) => b.onclick = () => this.labCsv([find(b.dataset.labcsv)]));
    };
    bindRes(root);
    $("lb_go").onclick = () => this.busy($("lb_go"), "…", async () => {
      const html = L.paste ? $("lb_html").value : "";
      if (!L.url && !html) { this.toast(t("Give an address, or paste the HTML."), "err"); return; }
      const r = await ws({ action: "run", retailer: L.shop || null, product: L.num || null, url: L.url, html });
      L.cur = r;
      const runs = this.labRuns(); runs.unshift({ ...r, head: undefined }); runs.splice(50); this.saveLabRuns();
      this.renderContent();
    });
    const csv = $("lb_csv"); if (csv) csv.onclick = () => this.labCsv(this.labRuns());
    const la = $("lb_logall"); if (la) la.onclick = () => this.busy(la, "…", async () => {
      const bad = this.labRuns().filter((r) => !["ok", "unavailable"].includes(r.verdict));
      for (const r of bad) await toLog(r);
      this.toast(t("{n} sent to the logbook", { n: bad.length }), "ok");
    });
    const cl = $("lb_clear"); if (cl) cl.onclick = () => { if (!confirm(t("Clear") + "?")) return; this._labRuns = []; this.saveLabRuns(); L.cur = null; this.renderContent(); };
    root.querySelectorAll("[data-labopen]").forEach((tr) => tr.onclick = () => { L.cur = find(tr.dataset.labopen); this.renderContent(); });
  }
  // ---------------------------------------------------------------- secret options (hidden link in the Manage tabs)
  // ---------------------------------------------------------------- secret options (hidden link in the Manage tabs)
  vSecret() {
    const st = this.state.settings;
    if (this.state.settingsErr) return this.emptyState("🔒", t("Only administrators can change settings."));
    if (!st) { this.loadSettings(); return `<div class="skel" style="height:200px"></div>`; }
    const dv = st.dev || {};
    const devRow = (k, label, help) => `<label class="chk" style="display:flex;gap:10px;align-items:flex-start;margin:6px 0"><input type="checkbox" class="x_dev" data-key="${k}" ${dv[k] ? "checked" : ""}><span><b>${label}</b><br><span class="muted" style="font-size:12px">${help}</span></span></label>`;
    const devPanel = `<div class="panel"><h3>🛠️ ${t("Developer mode")}</h3>
      ${devRow("dev_fixed_times", t("Allow checks at fixed times"), t("Full rounds of all products at fixed times (Settings → Automatic price checks)."))}
      ${devRow("dev_full_refresh", t("Allow “Refresh prices”"), t("A full round of all products by hand or by service, at most once a minute."))}
      ${devRow("dev_free_cycle", t("Free cycle"), t("Any cycle from 1 to 168 hours instead of 2/3/4/6/12/24."))}
      ${devRow("dev_unlimited", t("No product limit"), t("More than {n} products.", { n: st.product_limit || 200 }))}</div>`;
    const resets = [["relay_searched", t("Browser searches")], ["shop_js", t("JavaScript shops")], ["cooldowns", t("Shop pauses")],
      ["manual", t("Waiting times")], ["trace", t("Request trace")], ["suspects", t("Suspicious / approved prices")]];
    const tools = `<div class="panel"><h3>🧰 ${t("Tools")}</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
        <button class="btn ghost sm" id="d_stats" type="button">📊 ${t("Storage")}</button>
        <button class="btn ghost sm" id="d_queue" type="button">📋 ${t("Userscript queue")}</button>
        <button class="btn ghost sm" id="d_out" type="button">📉 ${t("Find outlier prices")}</button>
        <button class="btn ghost sm" id="d_health" type="button">🩺 ${t("Data check")}</button>
        <button class="btn ghost sm" id="d_sched" type="button">🗓 ${t("What runs when")}</button>
        <button class="btn ghost sm" id="d_jobs" type="button">🧾 ${t("Last jobs")}</button>
        <button class="btn ghost sm" id="d_dump" type="button">⬇ ${t("Debug dump (JSON)")}</button>
        <label class="chk" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="d_debug"> ${t("Debug logging")}</label></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px"><b style="font-size:13px">${t("Reset")}:</b>
        ${resets.map(([k, l]) => `<button class="btn ghost sm d_reset" data-what="${k}" type="button">↺ ${esc(l)}</button>`).join("")}</div>
      <p class="muted" style="font-size:12px">🔬 ${t("Testing a shop page: Manage → Parser lab.")}</p>
      <div id="d_res" style="margin-top:8px"></div></div>`;
    return devPanel + tools;
  }
  bindSecret(root, $) {
    const ws = (args) => this._hass.callWS({ type: "argus/dev/tool", ...args }), out = $("d_res");
    const show = (title, data) => { out.innerHTML = `<h4 style="margin:0 0 6px">${esc(title)}</h4><pre class="labhead" style="max-height:340px;overflow:auto">${esc(JSON.stringify(data, null, 2))}</pre>`; };
    const tool = (id, title, args, after) => { const b = $(id); if (b) b.onclick = () => this.busy(b, "…", async () => { const r = await ws(args); show(title, r); if (after) after(r); }); };
    tool("d_stats", t("Storage"), { action: "stats" });
    tool("d_queue", t("Userscript queue"), { action: "queue" });
    tool("d_sched", t("What runs when"), { action: "schedule" });
    tool("d_jobs", t("Last jobs"), { action: "jobs" });
    tool("d_health", t("Data check"), { action: "health" });
    tool("d_out", t("Find outlier prices"), { action: "outliers" });
    $("d_dump").onclick = () => this.busy($("d_dump"), "…", async () => {
      const r = await ws({ action: "dump" }), a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(r, null, 2)], { type: "application/json" }));
      a.download = `argus-debug-${new Date().toISOString().slice(0, 10)}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    });
    $("d_debug").onchange = (e) => ws({ action: "debug", on: e.target.checked }).then((r) => this.toast(r.debug ? t("Debug logging on") : t("Debug logging off"), "ok"));
    root.querySelectorAll(".d_reset").forEach((b) => b.onclick = () => this.busy(b, "…", async () => { const r = await ws({ action: "reset", what: b.dataset.what }); await this.load(); this.toast(t("{n} removed", { n: r.removed }), "ok"); }));
    root.querySelectorAll(".x_dev").forEach((c) => c.onchange = () => this._hass.callWS({ type: "argus/settings/set", fields: { [c.dataset.key]: c.checked } }).then(async () => { await new Promise((r) => setTimeout(r, 1500)); this.state.settings = null; await this.load(); this.renderContent(); }));
  }
  // ---------------------------------------------------------------- shop table (dialog + item editor)
  /** Every shop with a link plus the enabled shops without one: link, price, and per-shop actions. */
  // ---------------------------------------------------------------- shop table (dialog + item editor)
  /** Every shop with a link plus the enabled shops without one: link, price, and per-shop actions. */
  shopTableHtml(s, focus = null) {
    const stats = this.state.data.retailer_stats || {}, retailers = this.state.data.retailers;
    const rids = Object.keys(retailers).filter((rid) => (s.offers || {})[rid] || (stats[rid] && stats[rid].enabled));
    if (!rids.length) return `<div class="empty small">${t("No shops enabled.")} <a data-goto="manage/settings" style="cursor:pointer">${t("Settings")}</a></div>`;
    const cheapest = Math.min(...Object.values(s.offers || {}).map((o) => o.price ?? Infinity));
    const lk = (o) => { const st = o.link_status || "unknown"; return `<span class="lk ${st}" title="${esc(tx(o.link_reason || ""))}">${{ ok: "✓ " + t("correct"), confirmed: "✓ " + t("approved"), suspect: "⚠ " + t("suspicious"), unknown: "? " + t("not checked") }[st] || st}</span>`; };
    const man = `<span class="mbadge" title="${t("Entered by hand: always wins over automatic values")}">✎ ${t("manual")}</span>`, auto = `<span class="abadge">${t("auto")}</span>`;
    const paused = stats;
    const fetchBtn = (rid, has) => `<button class="btn ghost sm fetchb" data-rid="${rid}" ${this.mLeft(rid) ? this.mAttr(rid) : `title="${esc(has ? t("Fetch this shop now (also when it is paused)") : t("Search this shop for the product and fetch the price now"))}"`}>${has ? "↻" : "🔎"} ${esc(has ? t("Fetch") : t("Find"))}</button>`;
    const rows = rids.map((rid) => {
      const o = (s.offers || {})[rid], p = (paused[rid] || {}).paused_hours > 0 ? ` <span class="lk suspect" title="${t("paused after a block: {shops}", { shops: retailers[rid] })}">⏸</span>` : "";
      if (!o) return `<tr class="orow${focus === rid ? " focus" : ""}" data-rid="${rid}"><td><b>${esc(retailers[rid])}</b>${p}<div class="muted" style="font-size:12px">${t("no link yet")}</div></td>
        <td><input class="ou" data-orig="" placeholder="${t("product URL, product code or search URL")}" title="${t("Paste the product page (or a marketplace product code) and save, or paste a search page of this shop and press 🔎 Find: the product is then looked for on that page.")}"></td><td class="num"><input class="op" type="text" inputmode="decimal" autocomplete="off" data-money data-orig="" placeholder="€" disabled title="${t("Add a link first")}"></td><td class="oact">${fetchBtn(rid, false)}</td></tr>`;
      const autoP = o.manual_price != null ? o.auto_price : o.price;
      return `<tr class="orow${focus === rid ? " focus" : ""}" data-rid="${rid}"><td><b>${esc(o.label)}</b>${p} ${lk(o)}${o.title ? `<div class="muted" style="font-size:12px;max-width:240px">${esc(o.title.slice(0, 90))}</div>` : ""}${o.link_status === "suspect" ? `<div class="err">${esc(tx(o.link_reason || ""))}</div><div style="margin:4px 0">${doubtBtns(s.id, rid)}</div>` : ""}${o.unavailable ? `<div class="warn" style="font-size:12px">⚠ ${esc(unavailableText(o.unavailable))}</div>` : ""}${o.held ? `<div class="warn" style="font-size:12px">⚠ ${esc(t("temporarily unavailable: the last price is kept"))}</div>` : ""}${o.error ? `<div class="err">${esc(tx(o.error))}${o.ignored ? ` <span class="muted">(${t("ignored")})</span>` : ""}</div>` : ""}${o.suspect ? `<div style="margin-top:4px">${approveBtn(s.id, rid, o.suspect.price)}</div>` : ""}${o.price_choice ? `<div class="warn" style="font-size:12px;margin-top:4px">⚠ ${esc(t("The shop now says {price}", { price: EUR(o.price_choice.price) }))}</div><div style="margin-top:4px">${choiceBtns(s.id, rid, o.price_choice)}</div>` : ""}${o.approved ? `<div class="muted" style="font-size:11px">✓ ${esc(t("approved around {price}", { price: EUR(o.approved) }))}</div>` : ""}</td>
        <td><div style="display:flex;gap:6px;align-items:center">${o.manual_url ? man : auto}${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener noreferrer" data-stop style="font-size:12px;white-space:nowrap">${t("open")} ↗</a>` : ""}</div><input class="ou" value="${esc(o.url || "")}" data-orig="${esc(o.url || "")}" placeholder="${t("empty = search automatically")}" style="margin-top:4px"></td>
        <td class="num"><div>${o.manual_price != null ? man : auto} ${o.price != null ? `<b class="${o.price === cheapest ? "ok" : ""}">${EUR(o.price)}</b>${viaBadge(o.via)}` : "–"}</div>
          <input class="op" type="text" inputmode="decimal" autocomplete="off" data-money value="${o.manual_price ?? ""}" data-orig="${o.manual_price ?? ""}" placeholder="${autoP != null ? EUR(autoP) : t("auto")}" title="${t("empty = automatic price")}" style="margin-top:4px">
          <div class="muted" style="font-size:11px;margin-top:2px">${o.manual_price != null ? t("shop: {price}", { price: EUR(autoP) }) + " · " : ""}${t("low {price}", { price: EUR(o.low) })} · ${ago(o.checked)}</div></td>
        <td class="oact">${fetchBtn(rid, true)}${o.link_status !== "confirmed" ? `<button class="btn ghost sm okb" data-rid="${rid}" title="${t("This link is the right product")}">✓</button>` : ""}${o.error ? `<button class="btn ghost sm ignb" data-rid="${rid}" title="${esc(o.ignored ? t("Stop ignoring") : t("Ignore"))}">${o.ignored ? "👁" : "🙈"}</button>` : ""}<button class="btn ghost sm rmb" data-rid="${rid}" title="${t("Remove wrong link and never link it again")}">🗑</button></td></tr>`;
    }).join("");
    return `<div class="tscroll"><table class="tbl otbl"><tr><th>${t("Shop")}</th><th>${t("Link")}</th><th class="num">${t("Price")}</th><th></th></tr>${rows}</table></div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap"><button class="btn osave" type="button" disabled>💾 ${t("Save shop changes")}</button><span class="muted odirty" style="font-size:12px"></span><span class="hsp" style="flex:1"></span><button class="btn ghost sm fetchall" type="button" title="${t("Fetch every shop of this product now, one after another (also paused shops)")}">↻ ${t("Fetch all shops")}</button></div>`;
  }
  /** Binds a shop table inside root. reopen() re-renders after a change. Returns { changes } for combined saves. */
  /** Binds a shop table inside root. reopen() re-renders after a change. Returns { changes } for combined saves. */
  bindShopTable(root, s, reopen) {
    const num = s.id, retailers = this.state.data.retailers, q = (c) => root.querySelector("." + c);
    const rows = [...root.querySelectorAll("tr.orow")];
    const changes = () => rows.map((tr) => {
      const u = tr.querySelector(".ou"), p = tr.querySelector(".op"), ch = {};
      if (u.value.trim() !== u.dataset.orig) ch.url = u.value.trim();
      if (money(p.value) !== money(p.dataset.orig)) ch.manual_price = p.value.trim() === "" ? null : money(p.value);
      return [tr, ch];
    }).filter(([, ch]) => Object.keys(ch).length);
    const mark = () => {
      const list = changes(), dirty = new Set(list.map(([tr]) => tr));
      rows.forEach((tr) => { tr.classList.toggle("dirty", dirty.has(tr)); const p = tr.querySelector(".op"); if (p.disabled && tr.querySelector(".ou").value.trim()) { p.disabled = false; p.title = ""; } });
      if (q("osave")) { q("osave").disabled = !list.length; q("odirty").textContent = list.length ? t(list.length === 1 ? "{n} shop changed" : "{n} shops changed", { n: list.length }) : ""; }
    };
    const send = async (list) => {
      for (const [tr, ch] of list) {
        const msg = { type: "argus/offer/update", product: num, retailer: tr.dataset.rid };
        if ("url" in ch) msg.url = ch.url;
        if ("manual_price" in ch && ch.url !== "") msg.manual_price = ch.manual_price === null ? null : +ch.manual_price;
        await this._hass.callWS(msg);
      }
    };
    const check = (list) => {
      for (const [, ch] of list) if (ch.manual_price != null && !(+ch.manual_price > 0 && +ch.manual_price <= 10000)) { this.toast(t("Invalid price"), "err"); return false; }
      const odd = list.find(([, ch]) => ch.manual_price != null && s.ref_price && (+ch.manual_price < s.ref_price * 0.2 || +ch.manual_price > s.ref_price * 4));
      if (odd && !confirm(t("{price} is very different from the reference price {rrp}. Save anyway?", { price: EUR(+odd[1].manual_price), rrp: EUR(s.ref_price) }))) return false;
      const cleared = list.filter(([tr, ch]) => ch.url === "" && tr.querySelector(".ou").dataset.orig);
      return !(cleared.length && !confirm(t("Remove the link of {shops}? The shop may be searched automatically again.", { shops: cleared.map(([tr]) => retailers[tr.dataset.rid]).join(", ") })));
    };
    const save = () => { const list = changes(); if (!list.length || !check(list)) return; this.busy(q("osave"), t("Saving…"), async () => { await send(list); await this.load(); this.toast(t("Shop links and prices saved"), "ok"); reopen(); }); };
    rows.forEach((tr) => tr.querySelectorAll("input").forEach((i) => { i.addEventListener("input", mark); i.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } }); }));
    if (q("osave")) q("osave").onclick = save;
    const fetchOne = async (rid) => {
      // what was pasted in this shop's link field (and not saved yet) is used: a product page becomes the link,
      // a search page of the shop is searched
      const tr = root.querySelector(`.orow[data-rid="${rid}"]`), inp = tr && tr.querySelector(".ou");
      const pasted = inp && inp.value.trim() !== (inp.dataset.orig || "") ? inp.value.trim() : "";
      const r = await this._hass.callWS({ type: "argus/offer/fetch", product: num, retailer: rid, ...(pasted ? { url: pasted } : {}) });
      const res = r.result, shop = retailers[rid] || rid;
      this.toast(res.ok ? `${shop}: ${res.price != null ? EUR(res.price) : t("no price")}${res.found ? " · " + t("link found") : ""}` : `${shop}: ${tx(res.error || "")}`, res.ok ? "ok" : "err");
      return res;
    };
    root.querySelectorAll(".fetchb").forEach((b) => b.onclick = () => this.busy(b, "", async () => { await fetchOne(b.dataset.rid); await this.load(); reopen(); }));
    const all = q("fetchall"); if (all) all.onclick = () => this.busy(all, t("Fetching…"), async () => {
      let ok = 0; const ids = rows.map((tr) => tr.dataset.rid).filter((rid) => !this.mLeft(rid));
      if (!ids.length) { this.toast(this.mTitle(Math.max(...rows.map((tr) => this.mLeft(tr.dataset.rid)))), "err"); return; }
      for (const rid of ids) { try { if ((await fetchOne(rid)).ok) ok++; } catch (e) { this.toast(tx(e.message), "err"); } }
      this.toast(t("{ok} of {n} shops OK", { ok, n: ids.length }), ok ? "ok" : "err"); await this.load(); reopen();
    });
    root.querySelectorAll(".okb").forEach((b) => b.onclick = () => this.busy(b, "", async () => { await this.svc("confirm_offer", { product: num, retailer: b.dataset.rid }); await this.load(); reopen(); }));
    root.querySelectorAll(".ignb").forEach((b) => b.onclick = () => this.busy(b, "", async () => { const o = (s.offers || {})[b.dataset.rid] || {}; await this._hass.callWS({ type: "argus/ignore_error", product: num, retailer: b.dataset.rid, ignore: !o.ignored }); await this.load(); reopen(); }));
    root.querySelectorAll(".rmb").forEach((b) => b.onclick = () => { if (!confirm(t("Remove this link? It will not be linked automatically again."))) return; this.busy(b, "", async () => { await this.svc("remove_offer", { product: num, retailer: b.dataset.rid }); await this.load(); this.toast(t("Link removed"), "ok"); reopen(); }); });
    return { changes, send, check };
  }
  // ---------------------------------------------------------------- item editor (errors, link check, logbook)
  /** Inline editor for one product: name and every shop with its own buttons. */
  // ---------------------------------------------------------------- item editor (errors, link check, logbook)
  /** Inline editor for one product: name and every shop with its own buttons. */
  // ---------------------------------------------------------------- item editor (errors, link check, logbook)
  /** Inline editor for one product: name and every shop with its own buttons. */
  // ---------------------------------------------------------------- item editor (errors, link check, logbook)
  /** Inline editor for one product: name and every shop with its own buttons. */
  itemEditorHtml(s, focus = null) {
    return `<div class="item" data-inum="${esc(s.id)}"><div class="itemhead">${s.image ? `<img src="${esc(thumb(s.image, 160))}" alt="" loading="lazy" decoding="async">` : `<span class="ph">👁</span>`}
        <div style="flex:1;min-width:0"><div class="form" style="margin:0"><label style="grid-column:span 2">${t("Name")}${s.name_source === "user" ? ` <span class="mbadge">✎ ${t("manual")}</span>` : ""}<input class="i_name" value="${esc(s.name || "")}" data-orig="${esc(s.name || "")}" placeholder="${t("empty = filled in automatically")}"></label></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px"><button class="btn sm i_save" disabled>💾 ${t("Save name")}</button><button class="btn ghost sm" data-set="${esc(s.id)}">${t("Open product")}</button><button class="btn ghost sm i_log">📜 ${t("Logbook")}</button></div>
        <div class="muted" style="font-size:12px;margin-top:4px">${esc(s.ean || s.id)} · ${esc(t((this.state.data.categories || {})[s.category] || "Other"))}${s.ref_price ? " · " + t("reference price {price}", { price: EUR(s.ref_price) }) : ""}${s.image_source ? " · 🖼 " + esc(s.image_source === "shop" ? t("image from a shop") : srcName(s.image_source)) : ""}</div></div></div>
      ${this.shopTableHtml(s, focus)}</div>`;
  }
  bindItemEditor(box, after) {
    const num = box.dataset.inum, s = this.products.find((x) => x.id === num); if (!s) return;
    const q = (c) => box.querySelector("." + c), name = q("i_name");
    name.addEventListener("input", () => { q("i_save").disabled = name.value.trim() === name.dataset.orig; });
    const saveName = () => this.busy(q("i_save"), t("Saving…"), async () => { await this._hass.callWS({ type: "argus/update_product", product: num, fields: { name: name.value.trim() } }); await this.load(); this.toast(name.value.trim() ? t("Saved") : t("The name is filled in automatically again"), "ok"); after(); });
    q("i_save").onclick = saveName;
    name.addEventListener("keydown", (e) => { if (e.key === "Enter" && !q("i_save").disabled) saveName(); });
    q("i_log").onclick = () => this.showLogFor(num);
    this.bindShopTable(box, s, after);
  }
  /** 'Problem with this product': what is wrong (checkboxes, shops, remark) → logbook and/or CSV with everything known. */
  /** 'Problem with this product': what is wrong (checkboxes, shops, remark) → logbook and/or CSV with everything known. */
  reportForm(box, s) {
    if (!box.hidden) { box.hidden = true; return; }
    const probs = [["link", t("Link")], ["shop", t("Shop")], ["price", t("Price")], ["data", t("Product details (name, reference price, …)")], ["image", t("Image")], ["other", t("Something else")]];
    const shops = Object.entries(s.offers || {});
    box.innerHTML = `<div class="panel" style="margin:6px 0 10px;background:var(--ar-soft)"><h3 style="margin-top:0">⚠ ${t("Problem with this product")}</h3>
      <p class="muted" style="font-size:12px;margin:0 0 8px">${t("All links, prices, errors and the recent log of this product are added automatically.")}</p>
      <div class="chips" style="margin:0 0 8px">${probs.map(([k, l]) => `<label class="chk"><input type="checkbox" class="rp_p" value="${k}"> ${l}</label>`).join(" ")}</div>
      ${shops.length ? `<div class="muted" style="font-size:12px;margin:4px 0">${t("Which shops? (optional)")}</div><div class="chips" style="margin:0 0 8px">${shops.map(([rid, o]) => `<label class="chk"><input type="checkbox" class="rp_s" value="${esc(rid)}"> ${esc(o.label || rid)}</label>`).join(" ")}</div>` : ""}
      <label style="display:block">${t("What is wrong?")}<textarea id="rp_c" rows="3" maxlength="2000" style="width:100%;box-sizing:border-box;font:inherit;margin-top:4px" placeholder="${esc(t("e.g. the price is from another product, the link goes to an accessory, …"))}"></textarea></label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="btn sm" type="button" id="rp_log">📜 ${t("Write to the logbook")}</button><button class="btn ghost sm" type="button" id="rp_csv">⬇ ${t("Download as CSV")}</button><button class="btn ghost sm" type="button" id="rp_x">${t("Cancel")}</button></div></div>`;
    box.hidden = false;
    const pick = (cls) => [...box.querySelectorAll(cls)].filter((c) => c.checked).map((c) => c.value);
    const send = (save, btn) => this.busy(btn, "…", async () => {
      const problems = pick(".rp_p"), comment = box.querySelector("#rp_c").value.trim();
      if (!problems.length && !comment) { this.toast(t("Tick what is wrong or write a remark."), "err"); return; }
      const r = await this._hass.callWS({ type: "argus/report", product: s.id, problems, shops: pick(".rp_s"), comment, save });
      if (!save) {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob(["\ufeff" + r.csv], { type: "text/csv;charset=utf-8" }));
        a.download = `argus-problem-${s.id}-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      }
      this.toast(save ? t("Problem written to the logbook") : t("CSV downloaded"), "ok");
      box.hidden = true;
    });
    box.querySelector("#rp_log").onclick = (e) => send(true, e.currentTarget);
    box.querySelector("#rp_csv").onclick = (e) => send(false, e.currentTarget);
    box.querySelector("#rp_x").onclick = () => { box.hidden = true; };
  }
  /** Shops → click a shop: the last requests (what was asked, what came back, why it failed), a diagnosis and
   * its recent log. Refreshed every 5 s while open. */
  /** Shops → click a shop: the last requests (what was asked, what came back, why it failed), a diagnosis and
   * its recent log. Refreshed every 5 s while open. */
  /** Shops → click a shop: the last requests (what was asked, what came back, why it failed), a diagnosis and
   * its recent log. Refreshed every 5 s while open. */
  /** Shops → click a shop: the last requests (what was asked, what came back, why it failed), a diagnosis and
   * its recent log. Refreshed every 5 s while open. */
  async openShop(rid, refresh = false) {
    // a newer open / close makes this request stale: its answer must not reopen or overwrite the dialog
    const gen = refresh ? this._dlgGen : (this._dlgGen = (this._dlgGen || 0) + 1);
    const dlg = this.shadowRoot.getElementById("dlg");
    clearInterval(this._shopTimer);
    let d; try { d = await this._hass.callWS({ type: "argus/shop/detail", retailer: rid }); } catch (e) { if (gen === this._dlgGen) this.toast(tx(e.message), "err"); return; }
    if (gen !== this._dlgGen) return;
    const scroll = dlg.open ? dlg.scrollTop : 0, r = d.stats || {};
    const at = (ts) => (ts ? `${DATE(ts, { day: "numeric", month: "short" })} ${TIME(ts)}` : "–");
    const secs = (x) => (x > 0 ? t("in {s} s", { s: Math.ceil(x) }) : t("now"));
    const kind = { page: t("price page"), search: t("search") };
    const trace = d.trace.length ? `<div class="tscroll"><table class="tbl"><tr><th>${t("When")}</th><th>${t("What")}</th><th>HTTP</th><th>${t("Size")}</th><th>${t("Result")}</th></tr>${d.trace.map((x) => `<tr><td style="white-space:nowrap">${at(x.ts)}<div class="muted" style="font-size:11px">${x.ms} ms</div></td>
        <td>${esc(kind[x.kind] || x.kind)}${x.product ? ` <b>${esc(x.product)}</b>` : ""}<div style="font-size:11px;word-break:break-all"><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 90))}</a></div></td>
        <td class="num ${x.status >= 400 || !x.status ? "err" : ""}">${x.status ?? "–"}</td><td class="num">${x.size ? `${Math.round(x.size / 1024)} kB` : "–"}</td>
        <td class="${x.error ? "err" : "ok"}" style="font-size:12px">${esc(tx(x.error || x.result || "OK"))}</td></tr>`).join("")}</table></div>` : `<p class="muted">${t("No requests to this shop since the last restart of Home Assistant.")}</p>`;
    const log = d.log.length ? `<ul class="tl">${d.log.slice(0, 25).map((e) => { const res = (e.results || {})[rid]; return `<li ${e.product ? `data-set="${esc(e.product)}"` : ""}><span class="ic">${{ ok: "✅", error: "❌", warning: "⚠️" }[e.level] || "•"}</span><div><b>${esc(e.product || "")}</b> ${esc(tx(e.message))}${res ? `<div class="${res.ok === false ? "err" : "muted"}" style="font-size:12px">${res.price != null ? EUR(res.price) : ""}${res.error ? " " + esc(tx(res.error)) : ""}${res.via ? ` · ${t("via {source}", { source: esc(res.via) })}` : ""}</div>` : ""}<div class="t">${at(e.ts)}</div></div></li>`; }).join("")}</ul>` : `<p class="muted">${t("Nothing in the logbook for this shop yet.")}</p>`;
    const kv = (k, v) => `<div class="stat"><small>${k}</small><b>${v}</b></div>`;
    dlg.innerHTML = `<div class="dhead" style="grid-template-columns:1fr auto"><div><h2>🏪 ${esc(d.label)}</h2><div class="muted">${esc(d.site)} · ${d.enabled ? t("active") : t("switched off")}${d.paused_until ? ` · ⏸ ${t("paused until {time}", { time: at(d.paused_until) })}` : ""}</div>
        <div class="muted" style="font-size:12px;margin-top:4px">🔄 ${t("Updates every 5 seconds")} · ${t("updated {time}", { time: TIME(d.now) })}</div></div><div><button class="x" id="x" aria-label="${t("Close")}">✕</button></div></div>
      <div class="dbody">${d.hints.length ? `<div class="panel" style="background:var(--ar-soft)"><h3 style="margin-top:0">🩺 ${t("Diagnosis")}</h3><ul style="margin:0;padding-left:18px">${d.hints.map((h) => `<li>${esc(tx(h))}</li>`).join("")}</ul></div>` : ""}
        <div class="pstats">${kv(t("Links"), r.offers ?? 0)}${kv(t("With a price"), r.ok ?? 0)}${kv(t("Errors"), r.errors ?? 0)}${kv(t("Cheapest for"), t("{n} products", { n: r.cheapest ?? 0 }))}${kv(t("Last success"), ago(r.last_ok))}${kv(t("Blocks in a row"), d.blocks)}${kv(t("Last request"), at(d.last_request))}${kv(t("Next request possible"), secs(d.next_free))}${kv(t("Next search possible"), secs(d.next_search))}</div>
        ${d.search ? `<p class="muted" style="font-size:12px;margin:10px 0 0">${t("Search URL")}: <code style="word-break:break-all">${esc(d.search)}</code>${d.js ? ` · ⚠ ${t("built with JavaScript")}` : ""}</p>` : ""}
        <h3>📡 ${t("Last requests")}</h3>${trace}
        <h3>📜 ${t("Logbook")}</h3>${log}</div>`;
    if (!dlg.open) dlg.showModal();
    dlg.scrollTop = scroll;
    dlg.querySelector("#x").onclick = () => { clearInterval(this._shopTimer); this.closeDialog(); };
    dlg.querySelectorAll("[data-set]").forEach((el) => el.onclick = () => { clearInterval(this._shopTimer); this.openSet(el.dataset.set); });
    this._shopTimer = setInterval(() => { if (!dlg.open || !dlg.querySelector("#x") || !this.isConnected || gen !== this._dlgGen) { clearInterval(this._shopTimer); return; } this.openShop(rid, true); }, 5000);
  }
  // ---------------------------------------------------------------- set dialog
  // ---------------------------------------------------------------- set dialog
  closeDialog(instant = false) { this._dlgGen = (this._dlgGen || 0) + 1; clearInterval(this._shopTimer); const d = this.shadowRoot.getElementById("dlg"); if (!d || !d.open) return; if (instant || REDUCED) { d.close(); return; } d.classList.add("closing"); setTimeout(() => { d.classList.remove("closing"); d.close(); }, 170); }
  /** One copy in the set window's collection table. */
}
if (!customElements.get("argus-panel")) customElements.define("argus-panel", ArgusPanel);
