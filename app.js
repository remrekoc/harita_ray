/* Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE) */
/* Türkiye Raylı Sistemler: every passenger railway in Turkey on one map, intercity and urban.
   data/lines.json holds the cities, one record per line or service (with sourced ridership) and national totals;
   data/network.geojson holds each line's route and stations in running order; data/base.geojson the rest of the
   rail network. MapLibre draws OpenFreeMap vector tiles (or Esri imagery) and the network on top. The panel lists
   the lines, a city, a line or a station; the buttons along the top focus the map on one city. */
(() => {
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const phone = () => innerWidth <= 760;
const norm = s => String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/\p{M}/gu, "").replace(/ı/g, "i");
const slug = s => norm(s).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const nf = (n, d = 1) => n.toLocaleString("tr-TR", { maximumFractionDigits: d });
const store = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };
const rad = d => d * Math.PI / 180;
const dist = (a, b) => Math.hypot(rad(b[0] - a[0]) * Math.cos(rad((a[1] + b[1]) / 2)), rad(b[1] - a[1])) * 6371000;
const easeOut = t => 1 - (1 - t) ** 3;

/* ---------- vocabulary ---------- */
// Two groups the user can switch as a whole; each holds its line types. Banliyö sits with şehir içi: it is commuter
// rail inside one city (Marmaray, İZBAN, Başkentray, Gaziray, Adaray).
const TYPES = [
  { k: "hst", g: "inter", label: "Hızlı tren", hint: "YHT", c: "#d7192d" },
  { k: "main", g: "inter", label: "Ana hat", hint: "ekspres trenler", c: "#24324d" },
  { k: "regional", g: "inter", label: "Bölgesel", hint: "bölge trenleri", c: "#7c8aa3" },
  { k: "suburban", g: "urban", label: "Banliyö", hint: "Marmaray, İZBAN, Başkentray…", c: "#0f86a8" },
  { k: "metro", g: "urban", label: "Metro", hint: "hafif metro dahil", c: "#7a3c9a" },
  { k: "tram", g: "urban", label: "Tramvay", hint: "", c: "#2f9c6a" },
  { k: "cable", g: "urban", label: "Füniküler, teleferik", hint: "", c: "#a07f4f" },
];
const TY = Object.fromEntries(TYPES.map((t, i) => [t.k, { ...t, i }]));
const GROUPS = [
  { k: "inter", label: "Şehirlerarası", sub: "YHT, ana hat ve bölgesel trenler" },
  { k: "urban", label: "Şehir içi", sub: "Banliyö, metro, tramvay, füniküler" },
];
const STATUS = [
  { k: "open", label: "İşletmede", c: "#1a1a1a", dash: "" },
  { k: "construction", label: "İnşa halinde", c: "#e07000", dash: "6 4" },
  { k: "planned", label: "Planlanan", c: "#9a9da0", dash: ".1 5.5" },
];
const ST = Object.fromEntries(STATUS.map(s => [s.k, s]));
const RANK = { open: 0, construction: 1, planned: 2 };
const NONE = ["==", ["get", "line"], ""];
const TURKEY = [[25.7, 35.8], [44.8, 42.1]];
// Türkiye with about 50 km to spare on every side: the middle of the map the panel leaves free is never taken past it
const TR = [[25, 35.3], [45.5, 42.7]];
const TOP3 = ["istanbul", "ankara", "izmir"];

const ICON_BACK = `<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8.5 2.5L4 7l4.5 4.5"/></svg>`;
const ICON_TRAIN = `<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="1.8" width="9" height="9.6" rx="2.4"/><path d="M3.8 7h8.4M6 13.8l-1.2 1.4M10 13.8l1.2 1.4"/><circle cx="6" cy="9.2" r=".5" fill="currentColor"/><circle cx="10" cy="9.2" r=".5" fill="currentColor"/></svg>`;
// a line's badge: its code on its colour, like the station signs; intercity trains carry a train glyph
function badge(l, cls = "", tag = "span") {
  const ghost = l.status !== "open" && cls.includes("sm");
  const inner = l.type === "hst" ? "YHT" : l.city ? esc(l.code) : ICON_TRAIN;
  return `<${tag} class="bd ${cls}${ghost ? " ghost" : ""}${!l.city ? " ic" : ""}" style="--c:${l.color};--on:${l.on}"${tag === "button" ? ` data-line="${l.id}" title="${esc(lineTitle(l))}"` : ""}>${inner}</${tag}>`;
}
const lineTitle = l => (l.city ? l.code + " " : "") + l.name + (l.alias ? ` (${l.alias})` : "");
const swatch = (t, w = 30) => {
  const s = TY[t];
  if (["hst", "main", "regional"].includes(t)) return `<svg class="sw" width="${w}" height="10" viewBox="0 0 ${w} 10" aria-hidden="true"><path d="M3 5h${w - 6}" stroke="#fff" stroke-width="${t === "hst" ? 6 : 5}" stroke-linecap="round"/><path d="M3 5h${w - 6}" stroke="${s.c}" stroke-width="${t === "hst" ? 3.6 : t === "main" ? 2.6 : 2}" stroke-linecap="round"/></svg>`;
  // urban lines are drawn in their own colours: a little bundle of three
  const sw = { suburban: 2.6, metro: 2.6, tram: 2, cable: 1.6 }[t], cols = { suburban: ["#0f86a8", "#77787c", "#00a49f"], metro: ["#ee3124", "#009944", "#1b64b6"], tram: ["#004f7d", "#f47e46", "#2f9c6a"], cable: ["#7c7358", "#a07f4f", "#7c7358"] }[t];
  return `<svg class="sw" width="${w}" height="10" viewBox="0 0 ${w} 10" aria-hidden="true">${cols.map((c, i) => `<path d="M${3 + i * (w - 6) / 3 + (i ? 1 : 0)} 5h${(w - 6) / 3 - (i ? 1 : 0)}" stroke="${c}" stroke-width="${sw}" stroke-linecap="${t === "cable" ? "butt" : "round"}"${t === "cable" ? ' stroke-dasharray="2 1.2"' : ""}/>`).join("")}</svg>`;
};
const statusSwatch = (s, w = 30) => `<svg class="sw" width="${w}" height="8" viewBox="0 0 ${w} 8" aria-hidden="true"><path d="M3 4h${w - 6}" fill="none" stroke="${s.c}" stroke-width="3" stroke-linecap="${s.k === "construction" ? "butt" : "round"}"${s.dash ? ` stroke-dasharray="${s.dash}"` : ""}/></svg>`;

// ridership numbers, Turkish style: "163,1 milyon", "445.763", "≈ 6 milyon", "220 milyondan fazla"
function big(n) {
  if (n >= 1e9) return `${nf(n / 1e9, 2)} milyar`;
  if (n >= 1e6) return `${nf(n / 1e6, n >= 1e8 ? 0 : 1)} milyon`;
  return nf(Math.round(n), 0);
}
const shortN = n => n >= 1e6 ? `${nf(n / 1e6, n >= 1e7 ? 0 : 1)} mn` : n >= 1e3 ? `${nf(n / 1e3, n >= 1e4 ? 0 : 1)} bin` : nf(n, 0);
const prec = (p, s) => p === "approx" ? `≈ ${s}` : p === "lower" ? `${s}+` : s;

/* ---------- data ---------- */
let LINES = [], BY = {}, CITIES = [], CITY = {}, GROUPFIG = [], STA = [], CX = [];
const CX_BY_SLUG = {};
function prep(data, net) {
  LINES = data.lines; CITIES = data.cities; GROUPFIG = data.groups || [];
  for (const c of CITIES) { CITY[c.key] = c; c.lineObjs = []; }
  for (const l of LINES) {
    BY[l.id] = l; l.parts = []; l.stations = [];
    const [r, g, b] = [1, 3, 5].map(i => parseInt(l.color.slice(i, i + 2), 16) / 255);
    const lum = .2126 * r + .7152 * g + .0722 * b;
    l.on = lum > .6 ? "#1a1a1a" : "#fff";
    // a mid-grey line (İstanbul's B1 and B2) would pass for a road; the map draws it darker, with a railway's ties
    l.gray = !!l.city && Math.max(r, g, b) - Math.min(r, g, b) < .06 && lum > .3 && lum < .75;
    if (!l.opened && l.status === "open" && l.history) { const y = l.history[0].date.match(/\b(1[89]\d\d|20\d\d)\b/); if (y) l.opened = +y[1]; }
    l.g = TY[l.type].g;
    if (!l.city) { l.color = TY[l.type].c; l.on = "#fff"; }
    if (l.city && CITY[l.city]) CITY[l.city].lineObjs.push(l);
  }
  for (const f of net.features) {
    const l = BY[f.properties.line]; if (!l) continue;
    if (f.geometry.type === "Point") {
      const s = { i: STA.length, line: l, name: f.properties.name, existing: !!f.properties.existing, at: f.geometry.coordinates };
      STA.push(s); l.stations.push(s);
    } else {
      const c = f.geometry.coordinates, cum = [0];
      for (let i = 1; i < c.length; i++) cum.push(cum[i - 1] + dist(c[i - 1], c[i]));
      l.parts.push({ c, cum, len: cum[cum.length - 1] });
    }
  }
  for (const l of LINES) {
    l.count = l.stations.filter(s => !s.existing).length;
    const all = l.parts.flatMap(p => p.c);
    l.bounds = [[Math.min(...all.map(c => c[0])), Math.min(...all.map(c => c[1]))], [Math.max(...all.map(c => c[0])), Math.max(...all.map(c => c[1]))]];
    l.q = norm([l.code, l.name, l.alias, l.project, l.city && CITY[l.city]?.name, l.operator, l.network].join(" "));
    l.daily = l.ride?.daily || 0;
  }
  // a station complex: stops of the same name within a short walk (Yenikapı on M1A, M1B, M2, Marmaray)
  const byName = new Map();
  for (const s of STA) { const k = norm(s.name); if (!byName.has(k)) byName.set(k, []); byName.get(k).push(s); }
  for (const list of byName.values()) {
    const groups = [];
    for (const s of list) { const g = groups.find(g => g.some(m => dist(m.at, s.at) < 520)); if (g) g.push(s); else groups.push([s]); }
    for (const members of groups) {
      const lead = [...members].sort((a, b) => RANK[a.line.status] - RANK[b.line.status] || a.existing - b.existing || !!a.line.city - !!b.line.city)[0];
      const c = { id: CX.length, name: lead.name, at: lead.at, members };
      c.lines = [...new Set(members.map(m => m.line))].sort(byLine);
      c.codes = new Set(c.lines.map(l => l.city ? l.code : l.id));
      let sl = slug(c.name), n = 2;
      while (CX_BY_SLUG[sl]) sl = slug(c.name) + "-" + n++;
      c.slug = sl; CX_BY_SLUG[sl] = c; c.q = norm(c.name);
      for (const m of members) m.cx = c;
      CX.push(c);
    }
  }
  for (const c of CITIES) {
    const own = c.lineObjs.filter(l => l.status === "open");
    const pts = own.flatMap(l => l.stations.map(s => s.at));
    // the view a city opens with frames its metro and trams; long commuter lines (İZBAN, Marmaray) may run off the edge
    const core = c.lineObjs.filter(l => l.status === "open" && l.type !== "suburban");
    const built = c.lineObjs.filter(l => l.status !== "planned");
    c.bounds = unionBounds(core.length ? core : built.length ? built : c.lineObjs);
    c.mark = pts.length ? [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length] : c.center;
    c.servingSet = new Set(c.serving);
    c.annual = c.ride?.annual || own.reduce((a, l) => a + (l.ride?.annual && !l.ride.partial && !l.ride.season ? l.ride.annual : 0), 0);
    c.q = norm(c.name);
  }
  // presets: İstanbul, Ankara, İzmir first, then the other cities by yearly ridership
  CITIES.sort((a, b) => (TOP3.includes(b.key) - TOP3.includes(a.key)) || (TOP3.indexOf(a.key) - TOP3.indexOf(b.key)) || b.annual - a.annual || b.lineObjs.length - a.lineObjs.length);
}
function byLine(a, b) {
  return RANK[a.status] - RANK[b.status] || TY[a.type].i - TY[b.type].i || (a.city || "").localeCompare(b.city || "", "tr")
    || a.code.localeCompare(b.code, "tr", { numeric: true }) || !!(a.branch || a.extension) - !!(b.branch || b.extension) || a.name.localeCompare(b.name, "tr");
}
const byCode = lines => { const m = new Map(); for (const l of [...lines].sort(byLine)) { const k = l.city ? l.city + l.code : l.type; if (!m.has(k)) m.set(k, l); } return [...m.values()]; };
const unionBounds = ls => ls.length ? [[Math.min(...ls.map(l => l.bounds[0][0])), Math.min(...ls.map(l => l.bounds[0][1]))], [Math.max(...ls.map(l => l.bounds[1][0])), Math.max(...ls.map(l => l.bounds[1][1]))]] : TURKEY;

/* ---------- filters and scope ---------- */
// Nothing picked shows everything. The first type picked shows that type alone, each further pick adds one, and picking
// a type again takes it away. Statuses (İstanbul's lines under construction, planned) are picked the same way.
const picked = new Set(), pickedSt = new Set();
let cityKey = null, query = "", queryLines = null, rideMode = false;
const typeOn = k => !picked.size || picked.has(k);
const statusOn = k => !pickedSt.size || pickedSt.has(k);
const passes = l => typeOn(l.type) && statusOn(l.status);
const filtered = () => picked.size + pickedSt.size > 0;
const inScope = l => !cityKey || l.city === cityKey || CITY[cityKey].servingSet.has(l.id);
const groupState = g => { const ts = TYPES.filter(t => t.g === g); const n = ts.filter(t => picked.has(t.k)).length; return n === ts.length ? "on" : n ? "part" : picked.size ? "off" : "all"; };
function pickGroup(g) {
  const ts = TYPES.filter(t => t.g === g);
  if (groupState(g) === "on") ts.forEach(t => picked.delete(t.k)); else ts.forEach(t => picked.add(t.k));
  applyFilters();
}
function pickType(k) { picked.has(k) ? picked.delete(k) : picked.add(k); applyFilters(); }
function pickStatus(k) { pickedSt.has(k) ? pickedSt.delete(k) : pickedSt.add(k); applyFilters(); }
function resetFilters() { picked.clear(); pickedSt.clear(); applyFilters(); }
function applyFilters() {
  const t = top();
  for (const l of LINES) l.vis = passes(l) || (t && t.k === "line" && t.id === l.id);
  pushData();
  renderLegend(); renderScopes();
  if (!stack.length && tab === "lines") renderRoot();
  if (tab === "insights") renderInsights();
  $("#lg-reset").disabled = !filtered();
  foldCue();
}

/* ---------- map ---------- */
const OFM = "https://tiles.openfreemap.org/styles/";
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const BASES = { light: { url: OFM + "positron" }, dark: { url: OFM + "dark", dark: true }, streets: { url: OFM + "liberty" }, satellite: { dark: true } };
let base = BASES[store.get("base")] ? store.get("base") : "light";
let map, darkStyle, tilt = false, introDone = false, cityIn = 0, endIntro = null, growing = new Set(), hoverLine = null, hoverType = null, ring = [];
let lineFC = { type: "FeatureCollection", features: [] }, staFC = lineFC, meFC = lineFC, cityFC = lineFC, baseFC = lineFC;

async function styleFor(k) {
  if (k !== "satellite") return BASES[k].url;
  darkStyle = darkStyle || await fetch(OFM + "dark").then(r => r.json());
  const s = darkStyle;
  return {
    version: 8, glyphs: s.glyphs, sprite: s.sprite,
    sources: { esri: { type: "raster", tiles: [ESRI], tileSize: 256, maxzoom: 19, attribution: "Uydu görüntüsü © Esri, Maxar, Earthstar Geographics" }, openmaptiles: s.sources.openmaptiles },
    layers: [{ id: "esri", type: "raster", source: "esri", paint: { "raster-saturation": -.2, "raster-brightness-max": .85 } },
      // military areas mapped in OpenStreetMap are covered on the imagery, as official Turkish maps do; the blurred edge hides misalignment
      { id: "mil", type: "fill", source: "openmaptiles", "source-layer": "landuse", filter: ["==", ["get", "class"], "military"], paint: { "fill-color": "#34373b" } },
      { id: "mil-edge", type: "line", source: "openmaptiles", "source-layer": "landuse", filter: ["==", ["get", "class"], "military"], paint: { "line-color": "#34373b", "line-width": 10, "line-blur": 8 } },
      ...s.layers.filter(l => l.type === "symbol" && !/oneway/.test(l.id)).map(l => ({ ...l, paint: { ...l.paint, "text-color": "#fff", "text-halo-color": "rgba(0,0,0,.75)", "text-halo-width": 1.4 } }))],
  };
}
const TH = () => BASES[base].dark
  ? { casing: "#0e1013", fill: "#16191d", ink: "#f4f4f4", halo: "rgba(14,16,19,.9)", text: "#f4f4f4", dim: .4, bldg: "#3b4048", glow: true, rail: "#59606b", gray: "#b3b8c1", hst: "#ff4a57", main: "#c9d3e6", regional: "#8f9bb3" }
  : { casing: "#ffffff", fill: "#ffffff", ink: "#1a1a1a", halo: "rgba(255,255,255,.95)", text: "#1a1a1a", dim: .4, bldg: "#dfddd7", glow: false, rail: "#b9bdc2", gray: "#4c5058", hst: TY.hst.c, main: TY.main.c, regional: TY.regional.c };

// line width by zoom and type; a highlighted line is drawn on top, half as wide again
const ZS = [4.5, 7, 9, 11, 13, 16];
const HLW = 1.5;
const ZW = { hst: [1.8, 2.6, 3.1, 3.8, 4.8, 7], main: [1.25, 1.8, 2.3, 3, 4, 5.5], regional: [.85, 1.25, 1.7, 2.3, 3.1, 4.5],
  suburban: [1, 1.6, 2.4, 3.4, 5, 8.5], metro: [1, 1.6, 2.3, 3.4, 5, 9], tram: [.8, 1.2, 1.7, 2.6, 3.8, 7], cable: [.7, 1, 1.4, 2, 3, 5.5] };
const RK = [4.5, .03, 8, .028, 11, .03, 14, .06]; // ridership mode: width = √(daily passengers) × k(zoom)
function width(mul = 1, add = 0) {
  const e = ["interpolate", ["exponential", 1.3], ["zoom"]];
  ZS.forEach((z, i) => {
    let w = ["match", ["get", "type"], ...TYPES.flatMap(t => [t.k, ZW[t.k][i]]), 2];
    if (rideMode) w = ["case", [">", ["get", "d"], 0], ["min", 24, ["max", 1.2, ["*", ["sqrt", ["get", "d"]], kAt(z)]]], ["max", .9, ["*", w, .6]]];
    e.push(z, ["+", ["*", w, mul], add]);
  });
  return e;
}
function kAt(z) { for (let i = 0; i < RK.length - 2; i += 2) if (z <= RK[i + 2]) { const f = clamp((z - RK[i]) / (RK[i + 2] - RK[i]), 0, 1); return RK[i + 1] + (RK[i + 3] - RK[i + 1]) * f; } return RK[RK.length - 1]; }
const DASH = (() => { const a = 2, b = 1.4, p = a + b, n = 16, out = []; for (let i = 0; i < n; i++) { const u = (p - p * i / n) % p; out.push(u < a ? [a - u, b, u, 0] : [0, p - u, a, u - a]); } return out; })();

function shieldImage(l) {
  const ghost = l.status !== "open", dpr = 2, font = `800 11px "Open Sans", sans-serif`;
  const probe = document.createElement("canvas").getContext("2d"); probe.font = font;
  const w = Math.max(24, Math.ceil(probe.measureText(l.code).width) + 11), h = 17;
  const cv = document.createElement("canvas"); cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  g.beginPath(); g.roundRect(1, 1, w - 2, h - 2, 4);
  g.fillStyle = ghost ? "#fff" : l.color; g.fill();
  g.lineWidth = ghost ? 1.8 : 1.2; g.strokeStyle = ghost ? l.color : "rgba(255,255,255,.9)"; g.stroke();
  g.font = font; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillStyle = ghost ? (l.on === "#fff" ? l.color : "#1a1a1a") : l.on;
  g.fillText(l.code, w / 2, h / 2 + .5);
  return { width: cv.width, height: cv.height, data: g.getImageData(0, 0, cv.width, cv.height).data };
}
function addBuildings() {
  if (!map.getSource("openmaptiles") || base === "satellite" || map.getLayer("x-bldg") || map.getStyle().layers.some(l => l.type === "fill-extrusion")) return;
  map.addLayer({ id: "x-bldg", type: "fill-extrusion", source: "openmaptiles", "source-layer": "building", minzoom: 13,
    paint: { "fill-extrusion-color": TH().bldg, "fill-extrusion-height": ["coalesce", ["get", "render_height"], 10], "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
      "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 14.5, .75] } }, map.getLayer("b-rail") ? "b-rail" : undefined);
}

const URB = ["==", ["get", "u"], 1], OUT = ["==", ["get", "out"], 1];
function installOverlay() {
  const th = TH(), layers = map.getStyle().layers, before = layers.find(l => l.type === "symbol")?.id;
  if (base === "dark") for (const l of layers) if (l.type === "line" && l["source-layer"] === "transportation") map.setPaintProperty(l.id, "line-opacity", .45);
  // place names in Turkish where the tiles have them, else in Latin script (no second line in another alphabet)
  for (const l of layers) if (l.type === "symbol" && l.layout && l.layout["text-field"] && l["source-layer"] !== "transportation_name" && l["source-layer"] !== "housenumber")
    map.setLayoutProperty(l.id, "text-field", ["coalesce", ["get", "name:tr"], ["get", "name:latin"], ["get", "name"]]);
  // the basemaps draw railways of their own; ours replace them
  for (const l of layers) if (l["source-layer"] === "transportation" && /rail|transit/.test(l.id)) map.setLayoutProperty(l.id, "visibility", "none");
  for (const l of LINES) if (l.city && !map.hasImage("sh-" + l.id)) map.addImage("sh-" + l.id, shieldImage(l), { pixelRatio: 2 });
  // the lines arrive when the opening starts, so the map is ready, and the cities up, without waiting for them
  const net = introDone ? lineFC : { type: "FeatureCollection", features: [] };
  for (const [id, data] of [["base", baseFC], ["net", net], ["sta", staFC], ["cities", cityFC], ["me", meFC]]) map.addSource(id, { type: "geojson", data, ...(id === "net" ? { promoteId: "line" } : {}) });
  const round = { "line-join": "round", "line-cap": "round" };
  // the whole railway, faint: lines without passenger service, and those being built
  map.addLayer({ id: "b-rail", type: "line", source: "base", filter: ["==", ["get", "k"], "rail"], layout: round,
    paint: { "line-color": th.rail, "line-width": ["interpolate", ["linear"], ["zoom"], 5, .7, 10, 1.2, 14, 1.7], "line-opacity": 1 } }, before);
  map.addLayer({ id: "b-cons", type: "line", source: "base", filter: ["==", ["get", "k"], "cons"], layout: { "line-join": "round" },
    paint: { "line-color": th.rail, "line-width": ["interpolate", ["linear"], ["zoom"], 5, .8, 10, 1.3, 14, 2], "line-dasharray": [2, 2], "line-opacity": .9 } }, before);
  const notPlanned = ["!=", ["get", "status"], "planned"], isOpen = ["==", ["get", "status"], "open"], ties = ["all", isOpen, ["==", ["get", "gray"], 1]];
  map.addLayer({ id: "x-glow", type: "line", source: "net", filter: notPlanned, layout: { ...round, visibility: th.glow ? "visible" : "none", "line-sort-key": ["get", "sk"] },
    paint: { "line-color": ["get", "color"], "line-width": width(3.4), "line-blur": ["interpolate", ["linear"], ["zoom"], 6, 3, 14, 12], "line-opacity": .3 } }, before);
  map.addLayer({ id: "x-casing", type: "line", source: "net", filter: notPlanned, layout: { ...round, "line-sort-key": ["get", "sk"] }, paint: { "line-color": th.casing, "line-width": width(1, 2.2) } }, before);
  map.addLayer({ id: "x-open", type: "line", source: "net", filter: isOpen, layout: { ...round, "line-sort-key": ["get", "sk"] }, paint: { "line-color": ["get", "color"], "line-width": width() } }, before);
  map.addLayer({ id: "x-tie", type: "line", source: "net", minzoom: 10, filter: ties, paint: { "line-color": th.casing, "line-width": width(.4), "line-dasharray": [1.3, 2.2] } }, before);
  map.addLayer({ id: "x-cons", type: "line", source: "net", filter: ["==", ["get", "status"], "construction"], layout: { "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": width(), "line-dasharray": DASH[0] } }, before);
  map.addLayer({ id: "x-plan", type: "line", source: "net", filter: ["==", ["get", "status"], "planned"], layout: round,
    paint: { "line-color": ["get", "color"], "line-width": width(1.15), "line-dasharray": [0, 2.1] } }, before);
  // the highlight: the hovered line and the line (or station's lines) in view, redrawn on top of the rest, wider and haloed.
  // Its lines carry feature-state "hl", so hovering changes no layer and nothing else on the map moves.
  map.addLayer({ id: "h-glow", type: "line", source: "net", filter: notPlanned, layout: round,
    paint: { "line-color": ["get", "color"], "line-width": width(HLW * 3), "line-blur": ["interpolate", ["linear"], ["zoom"], 6, 3, 14, 9] } }, before);
  map.addLayer({ id: "h-case", type: "line", source: "net", filter: notPlanned, layout: round, paint: { "line-color": th.casing, "line-width": width(HLW, 3.2) } }, before);
  map.addLayer({ id: "h-open", type: "line", source: "net", filter: isOpen, layout: round, paint: { "line-color": ["get", "color"], "line-width": width(HLW) } }, before);
  map.addLayer({ id: "h-tie", type: "line", source: "net", minzoom: 10, filter: ties, paint: { "line-color": th.casing, "line-width": width(HLW * .4), "line-dasharray": [1.3, 2.2] } }, before);
  map.addLayer({ id: "h-cons", type: "line", source: "net", filter: ["==", ["get", "status"], "construction"], layout: { "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": width(HLW), "line-dasharray": DASH[0] } }, before);
  map.addLayer({ id: "h-plan", type: "line", source: "net", filter: ["==", ["get", "status"], "planned"], layout: round,
    paint: { "line-color": ["get", "color"], "line-width": width(HLW * 1.15), "line-dasharray": [0, 2.1] } }, before);
  map.addLayer({ id: "x-hit", type: "line", source: "net", filter: ["==", ["get", "out"], 0], layout: round, paint: { "line-color": "rgba(0,0,0,0)", "line-width": 14 } }, before);
  map.addLayer({ id: "x-shield", type: "symbol", source: "net", minzoom: 11, filter: ["all", URB, ["==", ["get", "out"], 0]],
    layout: { "symbol-placement": "line", "symbol-spacing": 380, "icon-image": ["get", "shield"], "icon-rotation-alignment": "viewport", "icon-padding": 4 } });
  const xfer = ["==", ["get", "xfer"], 1];
  map.addLayer({ id: "x-sta", type: "circle", source: "sta", paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, ["case", xfer, 2.2, 1.4], 9, ["case", xfer, 3, 2], 11, ["case", xfer, 3.8, 2.6], 13, ["case", xfer, 5.6, 4], 16, ["case", xfer, 9, 6.5]],
    "circle-color": th.fill, "circle-stroke-color": ["case", xfer, th.ink, ["get", "color"]],
    "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, .9, 13, 2, 16, 3] } });
  map.addLayer({ id: "x-ring", type: "circle", source: "sta", filter: ["in", ["get", "id"], ["literal", ring]],
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 7, 16, 15], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": th.ink, "circle-stroke-width": 1.8 } });
  const label = (id, minzoom, filter, bold) => map.addLayer({ id, type: "symbol", source: "sta", minzoom, filter,
    layout: { "text-field": ["get", "name"], "text-font": [bold ? "Noto Sans Bold" : "Noto Sans Regular"], "text-size": ["interpolate", ["linear"], ["zoom"], 8, bold ? 11 : 10.5, 16, bold ? 14.5 : 13],
      "text-variable-anchor": ["left", "right", "top", "bottom"], "text-radial-offset": .9, "text-justify": "auto", "text-max-width": 9, "text-padding": 3 },
    paint: { "text-color": th.text, "text-halo-color": th.halo, "text-halo-width": 1.6 } });
  // intercity stations are labelled earlier than urban ones: there are fewer of them, further apart
  label("x-lbl-x", 8.5, ["all", ["==", ["get", "lead"], 1], ["any", ["all", xfer, [">=", ["zoom"], 11]], ["all", ["==", ["get", "end"], 1], ["!", URB]]]], true);
  label("x-lbl", 9.5, ["all", ["==", ["get", "lead"], 1], ["any", ["all", URB, [">=", ["zoom"], 12.8]], ["all", ["!", URB], [">=", ["zoom"], 10.5]]]], false);
  label("x-lbl-sel", 0, NONE, true);
  // cities with urban rail: a labelled marker at country scale, a way into the city
  map.addLayer({ id: "c-dot", type: "circle", source: "cities", maxzoom: 9.2, paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 4.5, ["+", 3.2, ["*", ["get", "w"], 2.6]], 8, ["+", 5, ["*", ["get", "w"], 4]]],
    "circle-color": th.fill, "circle-stroke-color": th.ink, "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4.5, 1.6, 8, 2.4],
    "circle-opacity": ["interpolate", ["linear"], ["zoom"], 8, 1, 9, 0], "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], 8, 1, 9, 0] } });
  map.addLayer({ id: "c-lbl", type: "symbol", source: "cities", maxzoom: 9.2, layout: {
    "text-field": ["format", ["get", "name"], { "font-scale": 1 }, "\n", {}, ["get", "sub"], { "font-scale": .78, "text-font": ["literal", ["Noto Sans Regular"]] }],
    "text-font": ["Noto Sans Bold"], "text-size": ["interpolate", ["linear"], ["zoom"], 4.5, 11.5, 8, 13.5], "text-anchor": "left", "text-offset": [.95, 0], "text-justify": "left",
    "text-allow-overlap": false, "text-padding": 2, "symbol-sort-key": ["get", "rank"] },
    paint: { "text-color": th.text, "text-halo-color": th.halo, "text-halo-width": 1.8, "text-opacity": ["interpolate", ["linear"], ["zoom"], 8, 1, 9, 0] } });
  map.addLayer({ id: "x-me", type: "circle", source: "me", paint: { "circle-radius": 7, "circle-color": "#2f80ed", "circle-stroke-color": "#fff", "circle-stroke-width": 3 } });
  if (tilt) addBuildings();
  hlOn = new Set(); // a new style starts without feature-state
  paintFocus();
}

// What the rest is dimmed against: the open page (a line, the lines at a station), else search matches. Hovering dims nothing.
function focusExpr() {
  const t = top();
  if (t && t.k === "line") return ["==", ["get", "line"], t.id];
  if (t && t.k === "station") return ["in", ["get", "line"], ["literal", CX[t.id].lines.map(l => l.id)]];
  if (queryLines) return ["in", ["get", "line"], ["literal", queryLines]];
  return null;
}
// urban lines appear as you zoom in from the country view; until then their city's marker stands for them
const zoomed = (low, high, z0 = 6.4, z1 = 7.6) => ["interpolate", ["linear"], ["zoom"], z0, ["case", URB, low, high], z1, high];
function paintFocus() {
  if (!map || !map.getLayer("x-open")) return;
  const F = focusExpr(), th = TH(), set = (id, k, v) => map.setPaintProperty(id, k, v);
  const base1 = F ? ["case", F, 1, th.dim] : 1;
  const op = ["case", OUT, .1, ["==", ["get", "closed"], 1], ["*", .7, base1], base1];
  // lines that are growing on a canvas (all of them in the opening, a city's own when it opens) are hidden here meanwhile,
  // with their shields, stations and labels
  const hide = v => growing.size ? ["case", ["in", ["get", "line"], ["literal", [...growing]]], 0, v] : v;
  const on = v => introDone ? zoomed(0, hide(v)) : 0, lineOp = on(op);
  for (const id of ["x-open", "x-cons", "x-plan"]) { set(id, "line-width", width(id === "x-plan" ? 1.15 : 1)); set(id, "line-opacity", lineOp); }
  const noData = rideMode ? ["case", [">", ["get", "d"], 0], 1, .55] : 1;
  set("x-open", "line-opacity", on(["*", op, noData]));
  set("x-tie", "line-width", width(.4)); set("x-tie", "line-opacity", lineOp);
  set("x-casing", "line-width", width(1, 2.2)); set("x-casing", "line-opacity", on(["case", OUT, 0, F ? ["case", F, 1, th.dim * .8] : 1]));
  set("x-glow", "line-width", width(3.4)); set("x-glow", "line-opacity", on(["case", OUT, 0, F ? ["case", F, .3, .06] : .3]));
  const hl = v => zoomed(0, ["case", ["boolean", ["feature-state", "hl"], false], ["case", OUT, 0, ["==", ["get", "closed"], 1], ["*", .7, v], v], 0]);
  set("h-glow", "line-width", width(HLW * 3)); set("h-glow", "line-opacity", hl(BASES[base].dark ? .5 : .35));
  set("h-case", "line-width", width(HLW, 3.2)); set("h-case", "line-opacity", hl(1));
  for (const id of ["h-open", "h-cons"]) { set(id, "line-width", width(HLW)); set(id, "line-opacity", hl(1)); }
  set("h-plan", "line-width", width(HLW * 1.15)); set("h-plan", "line-opacity", hl(1));
  set("h-tie", "line-width", width(HLW * .4)); set("h-tie", "line-opacity", hl(1));
  const shown = introDone ? hide(base1) : 0;
  set("x-shield", "icon-opacity", shown);
  const staOp = ["interpolate", ["linear"], ["zoom"], 6.5, 0, 7, ["case", URB, 0, shown], 10, ["case", URB, 0, shown], 10.6, shown];
  set("x-sta", "circle-opacity", staOp); set("x-sta", "circle-stroke-opacity", staOp);
  for (const id of ["x-lbl", "x-lbl-x"]) set(id, "text-opacity", shown);
  const t = top();
  map.setFilter("x-lbl-sel", t && t.k === "line" ? ["all", ["==", ["get", "line"], t.id], ["any", ["==", ["get", "end"], 1], ["==", ["get", "xfer"], 1], [">=", ["zoom"], BY[t.id].city ? 0 : 8.5]]] : t && t.k === "station" ? ["all", ["==", ["get", "cx"], t.id], ["==", ["get", "lead"], 1]] : NONE);
  for (const id of ["x-lbl", "x-lbl-x"]) map.setLayoutProperty(id, "visibility", t && t.k === "line" ? "none" : "visible");
  map.setFilter("x-ring", ["in", ["get", "id"], ["literal", ring]]);
  paintCities();
  syncHL();
}
// the city markers; in the opening they come up one after another, the largest first, each with a small swell
function paintCities() {
  if (!map || !map.getLayer("c-dot")) return;
  const n = CITIES.length + 3, f = ["min", 1, ["max", 0, ["/", ["-", cityIn * n, ["get", "rank"]], 3]]], dim = ["==", ["get", "dim"], 1];
  const fade = v => ["interpolate", ["linear"], ["zoom"], 8, ["*", f, ["case", dim, v, 1]], 9, 0];
  const swell = ["interpolate", ["linear"], f, 0, .3, .65, 1.12, 1, 1];
  map.setPaintProperty("c-dot", "circle-opacity", fade(.35)); map.setPaintProperty("c-dot", "circle-stroke-opacity", fade(.35));
  map.setPaintProperty("c-dot", "circle-radius", ["interpolate", ["linear"], ["zoom"], 4.5, ["*", swell, ["+", 3.2, ["*", ["get", "w"], 2.6]]], 8, ["*", swell, ["+", 5, ["*", ["get", "w"], 4]]]]);
  map.setPaintProperty("c-lbl", "text-opacity", fade(.4));
}

const SK = { regional: 1, main: 2, hst: 3, suburban: 4, tram: 5, metro: 6, cable: 7 };
function lineFeatures() {
  const out = [];
  for (const l of LINES) {
    if (!l.vis) continue;
    const props = { line: l.id, status: l.status, type: l.type, color: l.type === "hst" || l.type === "main" || l.type === "regional" ? TH()[l.type] : l.gray ? TH().gray : l.color,
      gray: l.gray ? 1 : 0, u: l.city ? 1 : 0, out: inScope(l) ? 0 : 1, d: l.daily, closed: l.closed ? 1 : 0, shield: "sh-" + l.id, sk: rideMode ? -l.daily : SK[l.type] };
    for (const part of l.parts) out.push({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: part.c } });
  }
  return { type: "FeatureCollection", features: out };
}
function stationFeatures() {
  const out = [];
  for (const c of CX) {
    const vis = c.members.filter(s => s.line.vis && inScope(s.line));
    if (!vis.length) continue;
    const xfer = new Set(vis.map(s => s.line.city ? s.line.city + s.line.code : "ic")).size > 1 ? 1 : 0;
    vis.forEach((s, k) => {
      const st = s.line.stations, end = st[0] === s || st[st.length - 1] === s ? 1 : 0;
      out.push({ type: "Feature", properties: { id: s.i, cx: c.id, line: s.line.id, status: s.line.status, type: s.line.type, u: s.line.city ? 1 : 0,
        color: s.line.city ? s.line.color : TH()[s.line.type], name: s.name, xfer, end, lead: k === 0 ? 1 : 0 }, geometry: { type: "Point", coordinates: s.at } });
    });
  }
  return { type: "FeatureCollection", features: out };
}
function cityFeatures() {
  const max = Math.max(...CITIES.map(c => c.lineObjs.length));
  return { type: "FeatureCollection", features: CITIES.map((c, i) => {
    const n = c.lineObjs.filter(l => l.status === "open" && passes(l)).length;
    const soon = !n && (c.lineObjs.some(l => l.status === "construction") ? "inşa halinde" : c.lineObjs.some(l => l.status === "planned") ? "planlanıyor" : "");
    return { type: "Feature", properties: { key: c.key, name: c.name, sub: n ? `${n} hat` : soon, w: Math.sqrt(c.lineObjs.length / max), rank: i, dim: cityKey && cityKey !== c.key ? 1 : n ? 0 : 1 },
      geometry: { type: "Point", coordinates: c.mark } };
  }) };
}
function pushData() {
  stopIntro("data"); // a change to what the map shows ends the opening
  lineFC = lineFeatures(); staFC = stationFeatures(); cityFC = cityFeatures();
  if (!map) return;
  map.getSource("net")?.setData(lineFC);
  map.getSource("sta")?.setData(staFC);
  map.getSource("cities")?.setData(cityFC);
}
/* ---------- the opening, and opening a city ---------- */
// The cities come up first, then the railway grows out of them. The growing lines are drawn on a canvas laid over the map,
// so nothing on the map is rebuilt while they grow; meanwhile the map loads its own lines, hidden, and when the growth is
// done they are switched on underneath and the canvas fades away. Opening a city grows its own lines the same way, out of
// its centre, once the map has arrived. Moving the map, or changing what it shows, ends either at once.
const stopIntro = via => endIntro && endIntro(via);
function intro() {
  map.getSource("net")?.setData(lineFC);
  if (reduced) return finishIntro(null, true);
  const t0 = performance.now(), CITY_MS = 900, GROW_AT = 350, GROW_MS = 2400;
  let g = null, raf = 0;
  // cut short by a change the user made (a filter, a city), the link in the address is no longer opened
  endIntro = via => { cancelAnimationFrame(raf); finishIntro(g, true, via === "data"); };
  map.on("movestart", stopIntro); addEventListener("resize", stopIntro);
  const step = now => {
    const t = now - t0;
    cityIn = Math.min(1, t / CITY_MS); paintCities();
    if (t >= GROW_AT) (g = g || growth(LINES, CITIES.map(c => c.mark), false)).draw(Math.min(1, (t - GROW_AT) / GROW_MS));
    if (t >= GROW_AT + GROW_MS) return finishIntro(g, false);
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}
function finishIntro(g, quick, skipRoute) {
  if (introDone) return;
  map.off("movestart", stopIntro); removeEventListener("resize", stopIntro);
  introDone = true; cityIn = 1; endIntro = null; paintFocus();
  handover(g, quick || !!location.hash.slice(1)); // a link opens a page and moves the map: no slow fade over a moving map
  if (!skipRoute) route();
}
function cityGrow(key) {
  const ls = LINES.filter(l => l.city === key && l.vis);
  if (reduced || !introDone || !map || !ls.length) return;
  let g = null, raf = 0;
  const end = quick => {
    cancelAnimationFrame(raf); map.off("moveend", start); map.off("movestart", stopIntro); removeEventListener("resize", stopIntro);
    endIntro = null; growing = new Set(); paintFocus(); handover(g, quick);
  };
  const start = () => {
    if (map.isMoving()) return; // still flying, or the user is moving the map: wait until it rests
    map.off("moveend", start);
    if (cityKey !== key) return end(true);
    g = growth(ls, [CITY[key].mark], true);
    map.on("movestart", stopIntro); addEventListener("resize", stopIntro);
    const t0 = performance.now(), step = now => { const t = Math.min(1, (now - t0) / 1700); g.draw(t); if (t >= 1) return end(false); raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
  };
  stopIntro();
  endIntro = () => end(true);
  growing = new Set(ls.map(l => l.id)); paintFocus();
  map.on("moveend", start); requestAnimationFrame(start);
}
// the canvas fades once the map has drawn its own lines underneath; at once if the map is moving
function handover(g, quick) {
  if (!g) return;
  const fade = () => { g.cv.style.transitionDuration = quick ? ".2s" : ".6s"; g.cv.style.opacity = "0"; setTimeout(() => g.cv.remove(), quick ? 250 : 700); };
  if (quick) return fade();
  let n = 0;
  const wait = () => { if (map.isSourceLoaded("net") || ++n > 90) { map.once("render", () => requestAnimationFrame(fade)); map.triggerRepaint(); } else requestAnimationFrame(wait); };
  wait();
}
// a line's width on the map at zoom z, as width() gives it to the map
function lineW(l, z) {
  const at = i => rideMode ? (l.daily > 0 ? Math.min(24, Math.max(1.2, Math.sqrt(l.daily) * kAt(ZS[i]))) : Math.max(.9, ZW[l.type][i] * .6)) : ZW[l.type][i];
  if (z <= ZS[0]) return at(0);
  if (z >= ZS[ZS.length - 1]) return at(ZS.length - 1);
  let i = 0;
  while (z > ZS[i + 1]) i++;
  return at(i) + (at(i + 1) - at(i)) * (1.3 ** (z - ZS[i]) - 1) / (1.3 ** (ZS[i + 1] - ZS[i]) - 1);
}
// The growing lines. Each part grows from its end nearer a seed (the cities), or with `split` from its point nearest one
// (a city's centre) outwards both ways, all at one speed, so the network spreads out from the seeds; lines being built
// follow the open ones, planned lines come last. Colours, widths and dashes are the map's own, and a city's marker and
// name stay above the lines, as on the map: the canvas is cleared where they are.
function growth(lines, from, split) {
  const box = map.getContainer(), W = box.clientWidth, H = box.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
  const cv = document.createElement("canvas"); cv.className = "grow"; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  box.insertBefore(cv, box.querySelector(".maplibregl-control-container"));
  const ctx = cv.getContext("2d"), z = map.getZoom(), th = TH(), P = ll => { const p = map.project(ll); return [p.x, p.y]; };
  const seeds = from.map(P), near = p => Math.min(...seeds.map(s => Math.hypot(p[0] - s[0], p[1] - s[1])));
  const parts = [], add = (pts, d, base) => {
    if (pts.length < 2) return;
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    parts.push({ ...base, pts, cum, len: cum[cum.length - 1] || 1, from: d });
  };
  for (const l of lines) {
    const u = l.city ? clamp((z - 6.4) / 1.2, 0, 1) : 1, scope = inScope(l) ? 1 : 0; // urban lines join in past the country view
    const op = l.vis ? u * (scope ? (l.closed ? .7 : 1) : .1) * (rideMode && l.status === "open" && !(l.daily > 0) ? .55 : 1) : 0;
    if (!op) continue;
    const w = lineW(l, z), color = l.type === "hst" || l.type === "main" || l.type === "regional" ? th[l.type] : l.gray ? th.gray : l.color;
    const base = { w, color, op, caseOp: u * scope, status: l.status, sk: SK[l.type] };
    for (const part of l.parts) {
      const pts = [];
      for (const c of part.c) { const p = P(c), q = pts[pts.length - 1]; if (!q || Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]) > 1) pts.push(p); }
      if (pts.length < 2) continue;
      pts[pts.length - 1] = P(part.c[part.c.length - 1]);
      if (split) {
        let k = 0, d = Infinity;
        pts.forEach((p, i) => { const e = near(p); if (e < d) { d = e; k = i; } });
        add(pts.slice(0, k + 1).reverse(), d, base); add(pts.slice(k), d, base);
      } else {
        const a = near(pts[0]), b = near(pts[pts.length - 1]);
        add(b < a ? pts.reverse() : pts, Math.min(a, b), base);
      }
    }
  }
  const R0 = Math.max(1, ...parts.map(p => p.from + p.len));
  for (const p of parts) p.from += R0 * (p.status === "construction" ? .08 : p.status === "planned" ? .16 : 0);
  const reach = Math.max(1, ...parts.map(p => p.from + p.len));
  parts.sort((a, b) => a.sk - b.sk);
  const holes = new Path2D();
  if (z < 9.2) {
    const k = clamp((z - 4.5) / 3.5, 0, 1), size = 11.5 + 2 * k, m = document.createElement("canvas").getContext("2d");
    for (const c of cityFC.features) {
      const [x, y] = P(c.geometry.coordinates), w = c.properties.w, r = 3.2 + 2.6 * w + (1.8 + 1.4 * w) * k + .8 + .4 * k + 1;
      holes.moveTo(x + r, y); holes.arc(x, y, r, 0, 2 * Math.PI);
    }
    for (const f of map.queryRenderedFeatures({ layers: ["c-lbl"] })) {
      const [x, y] = P(f.geometry.coordinates), { name, sub } = f.properties;
      m.font = `700 ${size}px "Noto Sans", "Open Sans", sans-serif`;
      let tw = m.measureText(name).width, hgt = size * 1.2;
      if (sub) { m.font = `400 ${size * .78}px "Noto Sans", "Open Sans", sans-serif`; tw = Math.max(tw, m.measureText(sub).width); hgt += size * .94; }
      holes.rect(x + .95 * size - 3, y - hgt / 2 - 3, tw + 6, hgt + 6);
    }
  }
  const seg = (p, f) => { // the first f of a part, and where it has got to
    const path = new Path2D(), to = p.len * f, { pts, cum } = p;
    path.moveTo(pts[0][0], pts[0][1]);
    let i = 1;
    for (; i < pts.length && cum[i] <= to; i++) path.lineTo(pts[i][0], pts[i][1]);
    let tip = pts[i - 1];
    if (i < pts.length) { const s = (to - cum[i - 1]) / (cum[i] - cum[i - 1] || 1); tip = [tip[0] + (pts[i][0] - tip[0]) * s, tip[1] + (pts[i][1] - tip[1]) * s]; path.lineTo(tip[0], tip[1]); }
    return [path, tip];
  };
  const draw = t => {
    const front = easeOut(t) * reach, live = [];
    for (const p of parts) { const f = clamp((front - p.from) / p.len, 0, 1); if (f > 0) live.push([p, f, ...seg(p, f)]); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.setLineDash([]); ctx.strokeStyle = th.casing;
    for (const [p, , path] of live) if (p.status !== "planned" && p.caseOp) { ctx.globalAlpha = p.caseOp; ctx.lineWidth = p.w + 2.2; ctx.stroke(path); }
    for (const [p, , path] of live) if (p.status === "open") { ctx.globalAlpha = p.op; ctx.strokeStyle = p.color; ctx.lineWidth = p.w; ctx.stroke(path); }
    ctx.lineCap = "butt";
    for (const [p, , path] of live) if (p.status === "construction") { ctx.globalAlpha = p.op; ctx.strokeStyle = p.color; ctx.lineWidth = p.w; ctx.setLineDash([2 * p.w, 1.4 * p.w]); ctx.stroke(path); }
    ctx.lineCap = "round";
    for (const [p, , path] of live) if (p.status === "planned") { const w = p.w * 1.15; ctx.globalAlpha = p.op; ctx.strokeStyle = p.color; ctx.lineWidth = w; ctx.setLineDash([0, 2.1 * w]); ctx.stroke(path); }
    // the growing tips, softly lit, fading as their line completes
    for (const [p, f, , tip] of live) if (f < 1) {
      ctx.fillStyle = p.color;
      ctx.globalAlpha = p.op * .25 * (1 - f); ctx.beginPath(); ctx.arc(tip[0], tip[1], p.w * 2.8, 0, 2 * Math.PI); ctx.fill();
      ctx.globalAlpha = p.op * (1 - f * f); ctx.beginPath(); ctx.arc(tip[0], tip[1], p.w * .9 + .5, 0, 2 * Math.PI); ctx.fill();
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = "destination-out"; ctx.fill(holes); ctx.globalCompositeOperation = "source-over";
  };
  return { cv, draw };
}
let dashStep = -1;
function tick(now) {
  if (!reduced && !document.hidden && map && map.getLayer("x-cons")) {
    const s = Math.floor(now / 100) % DASH.length;
    if (s !== dashStep) { dashStep = s; map.setPaintProperty("x-cons", "line-dasharray", DASH[s]); map.setPaintProperty("h-cons", "line-dasharray", DASH[s]); }
  }
  requestAnimationFrame(tick);
}

// room the map keeps clear for the panel, the city buttons and the legend when it frames something; a folded panel leaves
// only its tab. On phones a sheet pulled up past half counts as half, where opening a city, a line or a station brings it.
function pad(open = panelOpen) {
  if (phone()) return { top: 70, bottom: Math.min(sheetPx, SHEET.half()) + 24, left: 28, right: 28 };
  const p = $("#panel"), lg = $("#legend").getBoundingClientRect(); // the panel's offsets, not its rect: they ignore the slide, so a fit made mid-slide uses where the panel ends up
  return { top: 84, bottom: 50, left: open ? p.offsetLeft + p.offsetWidth + 36 : 64, right: innerWidth - lg.left + 24 };
}
const fly = (bounds, maxZoom = 14.5) => map && map.fitBounds(bounds, { padding: pad(), maxZoom, duration: reduced ? 0 : 1400, essential: true });
const fitVisible = () => {
  if (cityKey) return fly(CITY[cityKey].bounds, 13);
  const v = LINES.filter(l => l.vis && !l.city);
  fly(v.length ? unionBounds(v) : TURKEY, 13);
};
const flyToLine = l => fly(l.bounds, 14.2);
const offset = () => { const p = pad(); return [(p.left - p.right) / 2, (p.top - p.bottom) / 2]; };
const flyToStation = (at, z = 15) => map && map.flyTo({ center: at, zoom: Math.max(map.getZoom(), z), offset: offset(), duration: reduced ? 0 : 1200, essential: true });
// The map stays over Türkiye: before every camera step, dragged or animated, the middle of the free map (beside the panel,
// above the sheet) is held inside TR, so the map stops at its edge. Not maxBounds: that holds the whole screen inside the box,
// the strips under the panel and the legend too, and no box near Türkiye then lets the country view sit beside the panel.
// In 3D the free middle is placed as if the map were flat, which is close enough for an edge.
function keepInTR(next) {
  const [ox, oy] = offset(), r = rad(next.bearing), k = 1 / (512 * 2 ** next.zoom), M = ll => maplibregl.MercatorCoordinate.fromLngLat(ll);
  const m = M(next.center), [a, b] = TR.map(M), dx = (ox * Math.cos(r) - oy * Math.sin(r)) * k, dy = (ox * Math.sin(r) + oy * Math.cos(r)) * k;
  const fx = m.x + dx, fy = m.y + dy, x = clamp(fx, a.x, b.x), y = clamp(fy, b.y, a.y);
  return x === fx && y === fy ? {} : { center: new maplibregl.MercatorCoordinate(x - dx, y - dy).toLngLat() };
}
// how far out the map zooms: a little past the country view beside the open panel (above the sheet on phones) on this screen
const setFloor = () => map.setMinZoom(Math.max(3.5, (map.cameraForBounds(TURKEY, { padding: pad(true) })?.zoom ?? 4) - .25));

/* ---------- hover card ---------- */
const tipEl = $("#tip");
function showTip(html, x, y) {
  tipEl.innerHTML = html; tipEl.classList.add("on");
  const r = tipEl.getBoundingClientRect();
  let left = x + 16, topY = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 16;
  if (topY + r.height > innerHeight - 8) topY = y - r.height - 14;
  tipEl.style.transform = `translate(${Math.round(left)}px,${Math.round(topY)}px)`;
}
const hideTip = () => tipEl.classList.remove("on");
const kmText = l => `${nf(l.km)} km`;
const lineFacts = l => [TY[l.type].label, l.status !== "open" ? ST[l.status].label : "", l.count ? `${l.count} istasyon` : "", kmText(l)].filter(Boolean).join(" · ");
const rideLine = l => l.ride?.daily ? `<span class="tr">${l.ride.dailyKind === "derived" ? "Ortalama günlük" : "Günlük"} <b>${prec(l.ride.dailyKind === "reported" ? l.ride.dailyPrecision : l.ride.precision, nf(l.ride.daily, 0))}</b> yolcu</span>`
  : l.ride?.annual ? `<span class="tr"><b>${prec(l.ride.precision, big(l.ride.annual))}</b> yolcu · ${esc(l.ride.period)}</span>` : "";
const tipLine = l => `<div class="th">${badge(l)}<div><b>${esc(l.name)}</b>${l.alias ? `<span class="ta">${esc(l.alias)}</span>` : ""}</div></div><span class="ts">${esc(lineFacts(l))}${l.city ? ` · ${esc(CITY[l.city].name)}` : ""}</span>${rideLine(l)}`;
const tipStation = c => `<b>${esc(c.name)}</b><div class="tl">${byCode(c.lines).slice(0, 10).map(l => badge(l, "sm")).join("")}</div><span class="ts">${c.codes.size > 1 ? "Aktarma istasyonu · " : ""}${c.lines.length} hat</span>`;
const tipCity = c => `<b>${esc(c.name)}</b><span class="ts">${c.lineObjs.filter(l => l.status === "open").length} hat${c.annual ? ` · yılda ${big(c.annual)} yolcu` : ""}</span><span class="tr">Tıklayın: şehre gidin</span>`;

// the lines drawn in the highlight: hovered, and those of the page in view; only their feature-state changes
let hlOn = new Set();
function syncHL() {
  const want = new Set(), t = top();
  if (hoverLine) want.add(hoverLine);
  if (hoverType) for (const l of LINES) if (l.type === hoverType && l.vis && inScope(l)) want.add(l.id);
  if (t && t.k === "line") want.add(t.id);
  if (t && t.k === "station") for (const l of CX[t.id].lines) want.add(l.id);
  if (!map || !map.getSource("net")) return;
  for (const id of hlOn) if (!want.has(id)) map.setFeatureState({ source: "net", id }, { hl: false });
  for (const id of want) if (!hlOn.has(id)) map.setFeatureState({ source: "net", id }, { hl: true });
  hlOn = want;
}
function setHoverLine(id) {
  if (hoverLine === id) return;
  hoverLine = id; syncHL();
  document.querySelectorAll(".row.hl").forEach(r => r.classList.remove("hl"));
  if (id) document.querySelectorAll(`.row[data-id="${id}"]`).forEach(r => r.classList.add("hl"));
}
function setHoverType(k) { if (hoverType !== k) { hoverType = k; syncHL(); } }
function setRing(ids) { ring = ids; if (map && map.getLayer("x-ring")) map.setFilter("x-ring", ["in", ["get", "id"], ["literal", ring]]); }

function wireMap() {
  const pick = e => {
    const p = e.point, layers = ["x-sta", "x-hit", "c-dot", "c-lbl"].filter(id => map.getLayer(id));
    const fs = map.queryRenderedFeatures([[p.x - 5, p.y - 5], [p.x + 5, p.y + 5]], { layers });
    const z = map.getZoom();
    const city = z < 8.6 && fs.find(f => f.layer.id === "c-dot" || f.layer.id === "c-lbl");
    if (city) return { city: CITY[city.properties.key] };
    const st = fs.find(f => f.layer.id === "x-sta" && (f.properties.u ? z >= 10.6 : z >= 7));
    const hit = fs.filter(f => f.layer.id === "x-hit").map(f => BY[f.properties.line]).filter(l => l && (l.city ? z >= 7 : true));
    // prefer the most specific line under the pointer: urban over intercity, then the busiest
    hit.sort((a, b) => !!b.city - !!a.city || (b.daily - a.daily));
    return { st: st ? CX[st.properties.cx] : null, line: !st && hit.length ? hit[0] : null };
  };
  map.on("mousemove", e => {
    if (!introDone) return;
    const { st, line, city } = pick(e);
    map.getCanvas().style.cursor = st || line || city ? "pointer" : "";
    if (city) { setHoverLine(null); showTip(tipCity(city), e.point.x, e.point.y); }
    else if (st) { setHoverLine(null); showTip(tipStation(st), e.point.x, e.point.y); }
    else if (line) { setHoverLine(line.id); showTip(tipLine(line), e.point.x, e.point.y); }
    else { setHoverLine(null); hideTip(); }
  });
  map.getCanvas().addEventListener("mouseleave", () => { setHoverLine(null); hideTip(); });
  map.on("click", e => {
    const { st, line, city } = pick(e);
    hideTip();
    if (city) setCity(city.key);
    else if (st) openStation(st.id);
    else if (line) select(line.id);
  });
  map.on("movestart", hideTip);
}

/* ---------- panel: navigation ---------- */
const stack = [];
const top = () => stack[stack.length - 1];
let tab = "lines";
function hashFor() {
  const t = top();
  if (t) return "#" + (t.k === "line" ? t.id : "istasyon/" + CX[t.id].slug);
  if (tab === "insights") return "#ozet";
  return cityKey ? "#" + cityKey : "";
}
function showView() {
  const t = top();
  $("#v-list").hidden = tab !== "lines" || !!t || !!cityKey;
  $("#v-city").hidden = tab !== "lines" || !!t || !cityKey;
  $("#v-line").hidden = tab !== "lines" || !t || t.k !== "line";
  $("#v-station").hidden = tab !== "lines" || !t || t.k !== "station";
  $("#v-insights").hidden = tab !== "insights";
  for (const l of LINES) l.vis = passes(l) || (t && t.k === "line" && t.id === l.id);
  pushData();
  if (!t || t.k !== "station") setRing([]);
  paintFocus();
  try { history.replaceState(null, "", hashFor() || location.pathname + location.search); } catch { /* file:// */ }
}
function push(v) {
  if (!(top() && top().k === v.k && top().id === v.id)) stack.push(v);
  if (stack.length > 12) stack.shift();
  tab = "lines"; setTabs();
  showView();
}
function back() {
  const was = stack.pop();
  showView();
  const t = top();
  if (!t) { renderRoot(); enter(cityKey ? $("#v-city") : $("#v-list")); const r = was && document.querySelector(`#pbody .row[data-id="${was.id}"]`); if (r) r.scrollIntoView({ block: "center" }); fitVisible(); }
  else if (t.k === "line") { renderLine(BY[t.id], true); flyToLine(BY[t.id]); }
  else renderStation(CX[t.id], true);
}
// every line and station page carries one button, held at the top while the page scrolls, straight back to the list
function home() {
  stack.length = 0; showView(); renderRoot();
  enter(cityKey ? $("#v-city") : $("#v-list")); $("#pbody").scrollTop = 0; fitVisible();
}
const homeBar = (act = "home", label = cityKey ? `${CITY[cityKey].name} hatları` : "Tüm hatlar") =>
  `<div class="homebar"><button class="home" data-act="${act}">${ICON_BACK}<span>${esc(label)}</span></button></div>`;
const enter = el => { if (reduced) return; el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter"); };
function select(id, opts = {}) {
  const l = BY[id]; if (!l) return;
  // a line outside the city in view takes the map to its own city (or to the country, for an intercity line)
  if (cityKey && !inScope(l)) setCity(l.city || null, { fly: false, keepStack: true });
  push({ k: "line", id });
  renderLine(l, true);
  $("#pbody").scrollTop = 0;
  setSheet("half"); setPanel(true);
  hideTip();
  if (!opts.noFly) requestAnimationFrame(() => flyToLine(l));
}
function openStation(id) {
  const c = CX[id]; if (!c) return;
  push({ k: "station", id });
  renderStation(c, true);
  $("#pbody").scrollTop = 0;
  setSheet("half"); setPanel(true);
  setRing(c.members.map(m => m.i));
  const pts = c.members.map(m => m.at);
  if (pts.length > 1) fly([[Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1]))], [Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1]))]], 16);
  else flyToStation(c.at, 15.5);
}
// the city buttons: focus the map and the panel on one city, or on the whole country
function setCity(key, opts = {}) {
  cityKey = key && CITY[key] ? key : null;
  if (!opts.keepStack) stack.length = 0;
  tab = "lines"; setTabs();
  renderPresets();
  showView();
  renderScopes(); renderLegend();
  if (!opts.keepStack) { renderRoot(); enter(cityKey ? $("#v-city") : $("#v-list")); $("#pbody").scrollTop = 0; }
  if (cityKey) setPanel(true);
  if (opts.fly !== false && map) cityKey ? fly(CITY[cityKey].bounds, 13) : fly(TURKEY, 7);
  if (cityKey && opts.fly !== false && opts.grow !== false) cityGrow(cityKey);
  setSheet(cityKey ? "half" : sheet);
}

/* ---------- city buttons ---------- */
function renderPresets() {
  const el = $("#presets");
  const btn = (k, label) => `<button data-city="${k}" aria-pressed="${(cityKey || "") === k}">${esc(label)}</button>`;
  el.innerHTML = `<div class="pr-row">${btn("", "Türkiye")}${CITIES.map(c => btn(c.key, c.name)).join("")}</div><div class="pr-more" hidden><button class="pr-more-b" aria-expanded="false">Diğer<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2 3.5l3 3 3-3"/></svg></button><div class="pr-menu" role="menu"></div></div>`;
  fitPresets();
}
// on wide screens the cities that do not fit move into a "Diğer" menu; on phones the row scrolls sideways
function fitPresets() {
  const el = $("#presets"), row = $(".pr-row", el), more = $(".pr-more", el), menu = $(".pr-menu", el);
  if (!row) return;
  const all = [...row.querySelectorAll("button")];
  all.forEach(b => { b.hidden = false; });
  more.hidden = true; menu.innerHTML = "";
  if (phone()) { const a = row.querySelector('[aria-pressed="true"]'); if (a) a.scrollIntoView({ inline: "center", block: "nearest" }); return; }
  const avail = el.clientWidth - 8;
  if (row.scrollWidth <= avail) return;
  more.hidden = false;
  const moreW = more.getBoundingClientRect().width + 4;
  const active = cityKey || "";
  let used = 0;
  const keep = new Set();
  for (const b of all) {
    const w = b.getBoundingClientRect().width + 2;
    if (used + w + moreW <= avail || b.dataset.city === "") { keep.add(b); used += w; }
  }
  // the active city stays on the bar even when it would have gone into the menu
  const act = all.find(b => b.dataset.city === active);
  if (act && !keep.has(act)) { const last = [...keep].pop(); keep.delete(last); keep.add(act); }
  const moved = all.filter(b => !keep.has(b));
  moved.forEach(b => { b.hidden = true; });
  menu.innerHTML = moved.map(b => `<button role="menuitem" data-city="${b.dataset.city}">${b.textContent}</button>`).join("");
  $(".pr-more-b", el).classList.toggle("on", moved.some(b => b.dataset.city === active));
}
$("#presets").addEventListener("click", e => {
  const m = e.target.closest(".pr-more-b");
  if (m) { const open = m.getAttribute("aria-expanded") !== "true"; m.setAttribute("aria-expanded", open); $("#presets").classList.toggle("menu", open); return; }
  const b = e.target.closest("[data-city]"); if (!b) return;
  $("#presets").classList.remove("menu");
  setCity(b.dataset.city || null);
});
document.addEventListener("click", e => { if (!e.target.closest("#presets")) { $("#presets").classList.remove("menu"); const m = $(".pr-more-b"); if (m) m.setAttribute("aria-expanded", "false"); } });

/* ---------- panel: tally, scope, list ---------- */
const tween = (el, to) => {
  const from = +el.dataset.v || 0; el.dataset.v = to;
  if (reduced || from === to) { el.textContent = to.toLocaleString("tr-TR"); return; }
  const t0 = performance.now(), d = 600;
  const step = () => { const q = Math.min(1, (performance.now() - t0) / d); el.textContent = Math.round(from + (to - from) * easeOut(q)).toLocaleString("tr-TR"); if (q < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
};
// route length on the ground: services that share a track count it once (cells of about 200 m)
function trackKm(ls) {
  const cells = new Set();
  for (const l of ls) for (const p of l.parts) {
    const c = p.c;
    for (let i = 1; i < c.length; i++) {
      const n = Math.max(1, Math.ceil((p.cum[i] - p.cum[i - 1]) / 200));
      for (let k = 0; k < n; k++) { const f = k / n; cells.add(Math.round((c[i - 1][0] + (c[i][0] - c[i - 1][0]) * f) * 450) + ":" + Math.round((c[i - 1][1] + (c[i][1] - c[i - 1][1]) * f) * 550)); }
    }
  }
  return cells.size * .2;
}
const stationCount = ls => { const set = new Set(ls); return CX.filter(c => c.members.some(s => !s.existing && set.has(s.line))).length; };
const openLines = ls => ls.filter(l => l.status === "open");
function scopeHTML(lines) {
  return GROUPS.map(g => {
    const st = groupState(g.k), ts = TYPES.filter(t => t.g === g.k);
    const ls = openLines(lines.filter(l => l.g === g.k));
    const types = ts.map(t => { const n = ls.filter(l => l.type === t.k).length; return `<button class="ty${typeOn(t.k) ? "" : " off"}${picked.has(t.k) ? " sel" : ""}${n ? "" : " none"}" data-t="${t.k}" aria-pressed="${picked.has(t.k)}" style="--c:${t.c}"><i></i><span>${t.label}</span><em class="num">${n}</em></button>`; }).join("");
    return `<div class="sg ${st}"><button class="sg-h" data-g="${g.k}" aria-pressed="${st === "on"}"><span class="ck" aria-hidden="true"></span><span class="sg-t"><b>${g.label}</b><small>${ls.filter(l => typeOn(l.type)).length} hat</small></span></button><div class="sg-ty">${types}</div></div>`;
  }).join("") + (filtered() ? `<button class="sc-reset" data-reset="1">Filtreyi sıfırla</button>` : "");
}
function renderScopes() {
  for (const el of document.querySelectorAll(".scope")) el.innerHTML = scopeHTML(el.dataset.city ? cityLines(CITY[el.dataset.city]) : LINES);
}
document.addEventListener("click", e => {
  const s = e.target.closest(".scope [data-g], .scope [data-t], .scope [data-reset]"); if (!s) return;
  if (s.dataset.reset) resetFilters(); else if (s.dataset.g) pickGroup(s.dataset.g); else pickType(s.dataset.t);
});
function renderTally() {
  const v = openLines(LINES.filter(passes));
  tween($("#t-n"), v.length);
  $("#t-of").textContent = `hat · ≈ ${nf(Math.round(trackKm(v) / 10) * 10, 0)} km güzergâh · ${nf(stationCount(v), 0)} istasyon`;
  $("#t-bar").innerHTML = TYPES.map(t => { const ls = v.filter(l => l.type === t.k); return ls.length ? `<i style="--c:${t.c};flex-grow:${trackKm(ls)}" title="${t.label}: ${ls.length} hat"></i>` : ""; }).join("");
}
function rowMeta(l) {
  if (l.status === "construction") return l.progress != null ? `<span class="mini num" style="--p:${l.progress}%">%${nf(l.progress)}<s></s></span>` : `<span class="pill" style="--c:${ST.construction.c}"><i></i>İnşa</span>`;
  if (l.status === "planned") return `<span class="pill" style="--c:${ST.planned.c}"><i></i>Plan</span>`;
  if (l.closed) return `<span class="pill" style="--c:var(--accent)"><i></i>Kapalı</span>`;
  if (l.ride?.daily) return `<span class="rv num" title="${l.ride.dailyKind === "derived" ? "Ortalama günlük yolcu" : "Günlük yolcu"}">${shortN(l.ride.daily)}<small>/gün</small></span>`;
  return l.opened ? `<span class="pill num" style="--c:var(--open)"><i></i>${l.opened}</span>` : "";
}
const rowSub = l => [l.alias, l.city && !cityKey ? CITY[l.city].name : "", l.count ? `${l.count} istasyon` : "", kmText(l)].filter(Boolean).join(" · ");
const row = l => `<li><button class="row" data-id="${l.id}">${badge(l, "lg")}<span><span class="rn">${esc(l.name)}</span><span class="ra">${esc(rowSub(l))}</span></span><span class="rc">${rowMeta(l)}</span></button></li>`;
const stationRow = (c, sub) => `<li><button class="row st" data-cx="${c.id}"><span class="sti"><i></i></span><span><span class="rn">${esc(c.name)}</span><span class="ra">${sub ? esc(sub) + " · " : ""}${c.codes.size > 1 ? "Aktarma · " : ""}${c.lines.length} hat</span></span><span class="rc"><span class="bds">${byCode(c.lines).slice(0, 6).map(l => badge(l, "sm")).join("")}</span></span></button></li>`;
const cityLines = c => [...c.lineObjs, ...c.serving.map(id => BY[id]).filter(Boolean)];
function cityRow(c) {
  const own = openLines(c.lineObjs.filter(passes)), all = openLines(c.lineObjs);
  const sub = (all.length ? [`${own.length} hat`, `${nf(own.reduce((a, l) => a + l.km, 0), 0)} km`, c.annual ? `yılda ${big(c.annual)} yolcu` : ""] : [projectText(c)]).filter(Boolean).join(" · ");
  return `<li><button class="row city${own.length ? "" : " dim"}" data-city="${c.key}"><span class="ctile"><b class="num">${all.length}</b><small>hat</small></span><span><span class="rn">${esc(c.name)}</span><span class="ra">${esc(sub)}</span></span><span class="rc"><span class="bds">${byCode(own).slice(0, 5).map(l => badge(l, "sm")).join("")}${own.length > 5 ? `<span class="more">+${byCode(own).length - 5}</span>` : ""}</span></span></button></li>`;
}
// a city's lines being built or planned, as words: "2 hat inşa halinde · 1 hat planlanıyor"
const projectText = c => [["construction", "inşa halinde"], ["planned", "planlanıyor"]].map(([k, w]) => { const n = c.lineObjs.filter(l => l.status === k).length; return n ? `${n} hat ${w}` : ""; }).filter(Boolean).join(" · ");
const grpHead = (label, n, sw = "") => `<div class="grp-head">${sw}<span class="h">${label}</span><span class="n num">${n}</span></div>`;
function renderRoot() { if (cityKey) renderCity(CITY[cityKey]); else renderList(); }
function renderList() {
  renderTally(); renderScopes();
  const q = norm(query);
  const lines = LINES.filter(l => passes(l) && (!q || l.q.includes(q)));
  queryLines = q ? lines.map(l => l.id) : null;
  let html = "";
  const inter = lines.filter(l => !l.city);
  for (const t of TYPES.filter(t => t.g === "inter")) {
    const g = openLines(inter.filter(l => l.type === t.k)).sort((a, b) => b.daily - a.daily || b.km - a.km);
    if (g.length) html += `<div class="grp">${grpHead(t.label, g.length, swatch(t.k, 22))}<ul class="plist">${g.map(row).join("")}</ul></div>`;
  }
  const soon = inter.filter(l => l.status !== "open").sort(byLine);
  if (soon.length) html += `<div class="grp">${grpHead("Yapımda ve planlanan şehirlerarası hatlar", soon.length)}<ul class="plist">${soon.map(row).join("")}</ul></div>`;
  if (q) {
    const urban = lines.filter(l => l.city).sort(byLine);
    if (urban.length) html += `<div class="grp">${grpHead("Şehir içi hatlar", urban.length)}<ul class="plist">${urban.map(row).join("")}</ul></div>`;
    const cs = CITIES.filter(c => c.q.includes(q));
    if (cs.length) html += `<div class="grp">${grpHead("Şehirler", cs.length)}<ul class="plist">${cs.map(cityRow).join("")}</ul></div>`;
    const st = CX.filter(c => c.q.includes(q) && c.members.some(m => passes(m.line))).sort((a, b) => (b.q.startsWith(q) - a.q.startsWith(q)) || b.lines.length - a.lines.length).slice(0, 12);
    if (st.length) html += `<div class="grp">${grpHead("İstasyonlar", st.length)}<ul class="plist">${st.map(c => stationRow(c)).join("")}</ul></div>`;
  } else if (TYPES.some(t => t.g === "urban" && typeOn(t.k))) {
    html += `<div class="grp">${grpHead("Şehir içi raylı sistemler", CITIES.length + " şehir")}<ul class="plist">${CITIES.map(cityRow).join("")}</ul></div>`;
  }
  if (!html) html = q ? `<p class="empty">“${esc(query)}” ile eşleşen hat, şehir ya da istasyon yok. <button data-clear="1">Aramayı temizle</button></p>`
    : `<p class="empty">Seçili türde hat yok. <button data-clear="1">Tümünü göster</button></p>`;
  $("#list").innerHTML = html;
  paintFocus();
}
document.addEventListener("click", e => {
  const b = e.target.closest("#pbody .row, #pbody [data-clear]"); if (!b) return;
  if (b.dataset.clear) return clearAll();
  if (b.dataset.city) return setCity(b.dataset.city);
  if (b.dataset.cx) return openStation(+b.dataset.cx);
  if (b.dataset.id) return select(b.dataset.id);
});
// rows sliding under a resting pointer while the list scrolls are not hovers
let scrolledAt = 0;
$("#pbody").addEventListener("scroll", () => { scrolledAt = performance.now(); setHoverLine(null); }, { passive: true });
$("#pbody").addEventListener("mouseover", e => { const b = e.target.closest(".row[data-id], .bars [data-id]"); if (b && performance.now() - scrolledAt > 250) setHoverLine(b.dataset.id); });
$("#pbody").addEventListener("mouseout", e => { const b = e.target.closest(".row[data-id], .bars [data-id]"); if (b) setHoverLine(null); });
$("#q").addEventListener("input", e => { query = e.target.value.trim(); renderList(); });
$("#q").addEventListener("keydown", e => {
  if (e.key === "Enter") { const first = $("#list .row"); if (first) first.click(); }
  if (e.key === "Escape") { e.target.value = ""; query = ""; renderList(); e.target.blur(); }
});
$("#q").addEventListener("focus", () => setSheet("full"));
function clearAll() { query = ""; $("#q").value = ""; resetFilters(); }

/* ---------- ridership block ---------- */
const srcLink = (s, label) => s?.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(label || s.title || s.publisher || "Kaynak")} ↗</a>` : "";
function periodText(r) {
  if (r.partial) return `${esc(r.period.replace(/^(\d{4})-(\d\d)-(\d\d)\/(\d{4})-(\d\d)-(\d\d)$/, (m, y1, m1, d1, y2, m2, d2) => `${+d1}.${m1}.${y1}–${+d2}.${m2}.${y2}`))} (kısmi yıl)`;
  if (r.season) return "2025–26 kış sezonu";
  return esc(String(r.year));
}
function rideHTML(r, compact) {
  if (!r) return "";
  const parts = [];
  if (r.annual) parts.push(`<div class="rb"><b class="num">${prec(r.precision, big(r.annual))}</b><span>${r.season ? "sezonluk yolcu" : r.partial ? "yolcu" : "yıllık yolcu"} · ${periodText(r)}</span></div>`);
  if (r.daily) {
    const derived = r.dailyKind === "derived";
    parts.push(`<div class="rb"><b class="num">${prec(derived ? r.precision : r.dailyPrecision || r.precision, nf(r.daily, 0))}</b><span>${derived ? "ortalama günlük" : "günlük ortalama"}${!derived && r.dailyYear ? ` · ${r.dailyYear}` : ""}</span></div>`);
  }
  const s = r.src, ds = r.dailySrc;
  const how = r.dailyKind === "derived" && r.annual ? `Günlük değer yıllık toplamın ${r.partial ? "kapsadığı gün" : "gün"} sayısına bölünmesiyle bulunur.` : "";
  const meta = [s ? `Kaynak: ${srcLink(s)}${s.publisher && s.title ? ` · ${esc(s.publisher)}` : ""}` : "", ds && ds.url !== s?.url ? `Günlük değer: ${srcLink(ds)}` : "",
    [s?.unit && `Birim: ${esc(s.unit)}`, s?.derived && esc(s.derived), how].filter(Boolean).join(". ")].filter(Boolean);
  return `<div class="ride${compact ? " compact" : ""}"><div class="rbs">${parts.join("")}</div>${meta.map(m => `<p class="rsrc">${m}</p>`).join("")}</div>`;
}
function groupFigHTML(g) {
  if (!g) return "";
  return `<div class="gfig"><span class="gl">Grup verisi</span><p><b class="num">${prec(g.precision, big(g.annual))}</b> yolcu · ${esc(String(g.year))} · ${esc(g.label)}</p><p class="rsrc">Kaynak: ${srcLink(g.src)}</p></div>`;
}

/* ---------- panel: a line ---------- */
function routeSVG(l) {
  const pts = l.parts.flatMap(p => p.c);
  if (pts.length < 2) return "";
  const k = Math.cos(rad(pts.reduce((a, c) => a + c[1], 0) / pts.length));
  const xs = pts.map(c => c[0] * k), ys = pts.map(c => -c[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const W = 400, H = 150, P = 24, s = Math.min((W - 2 * P) / ((x1 - x0) || 1e-6), (H - 2 * P) / ((y1 - y0) || 1e-6));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  const X = c => ((c[0] * k - x0) * s + ox).toFixed(1), Y = c => ((-c[1] - y0) * s + oy).toFixed(1);
  const kind = { construction: "cons", planned: "plan" }[l.status] || "";
  const paths = l.parts.map(p => `<path class="${kind}" d="M${p.c.map(c => X(c) + " " + Y(c)).join("L")}"/>`).join("");
  const sts = l.stations.length > 40 ? l.stations.filter((s, i) => i === 0 || i === l.stations.length - 1 || s.cx.codes.size > 1) : l.stations;
  const dots = sts.map((st, i) => { const x = st.cx.codes.size > 1; return `<circle class="${x ? "x" : ""}" style="--i:${i}" cx="${X(st.at)}" cy="${Y(st.at)}" r="${x ? 4.6 : 3.6}"/>`; }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${paths}${dots}</svg>`;
}
function statHTML(v, label) {
  const m = String(v).match(/^(.*?)\s*\((.+)\)$/);
  return `<div class="stat"><b class="num">${esc(m ? m[1] : v)}</b><span>${esc(label)}${m ? ` · ${esc(m[2])}` : ""}</span></div>`;
}
/* journey times (l.dur): only as published, with date and source; per-stop minutes only from an operator's GTFS timetable.
   Average speed is the one derived value: published km ÷ published time. */
const hm = m => { m = Math.round(m); const h = Math.floor(m / 60), r = m % 60; return h ? `${h} sa${r ? ` ${r} dk` : ""}` : `${r} dk`; };
const durText = (d, m = d.dirs[0].min) => `${d.bound === "under" ? "< " : d.approx ? "≈ " : ""}${hm(m)}`;
const dmy = d => /^\d{4}-\d\d-\d\d$/.test(d || "") ? d.split("-").reverse().join(".") : d || "";
const srcMeta = s => `${srcLink(s)}${esc([s.publisher, dmy(s.date)].filter(Boolean).map(x => " · " + x).join(""))}`;
let tOrigin = null; // the stop the minutes are counted from, on the line it belongs to
const timedDirs = l => (l.dur?.dirs || []).filter(d => d.stops);
const originOf = l => tOrigin && tOrigin.id === l.id ? tOrigin.name : timedDirs(l)[0]?.stops[0][0];
// minutes from a stop to each stop after it, in the first timetable direction that runs onward from it
function timesFrom(l, o) {
  const out = new Map();
  for (const d of timedDirs(l)) {
    const i = d.stops.findIndex(s => s[0] === o); if (i < 0) continue;
    for (let j = i; j < d.stops.length; j++) if (!out.has(d.stops[j][0])) out.set(d.stops[j][0], d.stops[j][1] - d.stops[i][1]);
  }
  return out;
}
// the timetable direction as a strip: stops spaced by minutes, the run from the chosen stop drawn in the line's colour
function tstripHTML(l, c) {
  const o = originOf(l);
  const pick = timedDirs(l).map(d => ({ d, i: d.stops.findIndex(s => s[0] === o) })).filter(x => x.i >= 0).sort((a, b) => (b.d.stops.length - b.i) - (a.d.stops.length - a.i))[0];
  if (!pick) return "";
  const st = pick.d.stops, i = pick.i, T = st[st.length - 1][1], t0 = st[i][1], x = t => (100 * t / T).toFixed(2) + "%";
  const ticks = []; for (let m = 10; (T - t0 - m) / T > .12; m += 10) ticks.push(`<span style="left:${x(t0 + m)}">${m}</span>`);
  const dots = st.map((s, j) => `<button class="ts-d${j < i ? " pre" : j === i ? " on" : ""}" style="left:${x(s[1])}" data-tm="${esc(s[0])}" title="${esc(s[0])}${j > i ? ` · ${hm(s[1] - t0)}` : ""}" aria-label="${esc(s[0])}"></button>`).join("");
  return `<div class="tstrip" style="--c:${c}">
    <p class="ts-h"><b>${esc(st[i][0])}</b> → <b>${esc(st[st.length - 1][0])}</b><span class="num">${hm(T - t0)}</span></p>
    <div class="ts-bar"><i class="ts-run" style="left:${x(t0)}"></i>${dots}</div>
    <div class="ts-ax num"><span style="left:${x(t0)}">0</span>${ticks.join("")}<span class="end">dk</span></div>
    <p class="ts-tip">Duraklar tarifedeki dakikalarına göre dizilir. Bir durağa ya da aşağıdaki listede bir süreye dokunun: süreler o duraktan sayılır.</p></div>`;
}
function durHTML(l) {
  const d = l.dur; if (!d) return "";
  const c = l.city ? l.color : TH()[l.type], d0 = d.dirs[0];
  const lab = x => `${esc(x.label || "")}${x.dep ? ` · ${esc(x.dep)}–${esc(x.arr)}` : ""}`;
  const blocks = [`<div class="rb"><b class="num">${durText(d)}</b><span>${lab(d0)} · tek yön${d.stopsIncluded ? ", duruşlar dahil" : ""}</span></div>`,
    ...d.dirs.slice(1).map(x => `<div class="rb"><b class="num">${durText(d, x.min)}</b><span>${lab(x)}</span></div>`),
    d.avg ? `<div class="rb"><b class="num">${d.avgApprox ? "≈ " : ""}${d.avg}<small>km/sa</small></b><span>ortalama hız${d.stopsIncluded ? ", duruşlar dahil" : ""} · ${nf(d.km, 0)} km</span></div>` : "",
    d.vmax ? `<div class="rb"><b class="num">${d.vmax.kmh}<small>km/sa</small></b><span>${esc(d.vmax.kind)}${d.vmax.scope ? ` · ${esc(d.vmax.scope)}` : ""}</span></div>` : ""];
  const meta = [d.train && esc(d.train), d.note && esc(d.note), d.basis && esc(d.basis),
    `Kaynak: ${srcMeta(d.src)}`, d.vmax && d.vmax.src.url !== d.src.url ? `${esc(d.vmax.kind[0].toLocaleUpperCase("tr") + d.vmax.kind.slice(1))}: ${srcMeta(d.vmax.src)}` : "",
    d.avg ? "Ortalama hız, yayımlanmış uzunluğun yayımlanmış süreye bölünmesiyle bulunur." : ""].filter(Boolean);
  return `<div class="sec rsec"><h3>Yolculuk süresi${d.gtfs ? " <span>işletmecinin tarifesi</span>" : ""}</h3><div class="ride dur"><div class="rbs">${blocks.join("")}</div>${meta.map(m => `<p class="rsrc">${m}</p>`).join("")}</div>${timedDirs(l).length ? tstripHTML(l, c) : ""}</div>`;
}
// the stations as a strip map; a long intercity route shows its ends and junctions until opened in full
function stripHTML(l, full) {
  const kind = { construction: "cons", planned: "plan" }[l.status] || "";
  const sts = l.stations, long = !full && sts.length > 26;
  const keep = s => !long || s === sts[0] || s === sts[sts.length - 1] || byCode(s.cx.lines.filter(o => o !== l && o.status === "open")).length >= (l.city ? 1 : 2);
  const o = timedDirs(l).length ? originOf(l) : null, mins = o ? timesFrom(l, o) : null;
  const tm = s => !mins ? "" : s.name === o ? `<span class="tm on">buradan</span>` : mins.has(s.name) ? `<button class="tm num" data-tm="${esc(s.name)}" title="${esc(s.name)} çıkışlı süreleri göster">${hm(mins.get(s.name))}</button>` : `<button class="tm" data-tm="${esc(s.name)}" title="${esc(s.name)} çıkışlı süreleri göster">–</button>`;
  let html = "", skipped = 0;
  for (const s of sts) {
    if (!keep(s)) { skipped++; continue; }
    if (skipped) { html += `<li class="gap"><span class="dot"></span><button class="sn more" data-act="all">${skipped} istasyon daha</button><span></span></li>`; skipped = 0; }
    const others = byCode(s.cx.lines.filter(o => o !== l && (o.city ? o.city + o.code : o.type) !== (l.city ? l.city + l.code : "-")));
    html += `<li class="${others.length ? "x" : ""}${s.existing ? " old" : ""}" data-s="${s.i}"><span class="dot"></span><button class="sn" data-s="${s.i}">${esc(s.name)}${s.existing ? "<em>mevcut</em>" : ""}</button><span class="bds">${others.slice(0, 5).map(o => badge(o, "sm", "button")).join("")}${others.length > 5 ? `<span class="more">+${others.length - 5}</span>` : ""}</span>${tm(s)}</li>`;
  }
  return `<ul class="strip ${kind}${mins ? " timed" : ""}" style="--c:${l.city ? l.color : TH()[l.type]}">${html}</ul>${long ? `<button class="showall" data-act="all">Tüm istasyonları göster (${sts.length})</button>` : ""}`;
}
function renderLine(l, fresh, full = false) {
  const el = $("#v-line"), s = ST[l.status], parent = (l.extension || l.branch) && LINES.find(o => o.city === l.city && o.code === l.code && !o.extension && !o.branch);
  const who = l.status === "open" ? l.operator : l.authority;
  const sub = l.extension ? `${l.code} hattının uzatması` : l.branch ? `${l.code} hattının kolu` : l.alias || "";
  const city = l.city && CITY[l.city];
  const state = [`<span class="pill" style="--c:${s.c}"><i></i>${s.label}</span>`,
    l.opened ? `<span>Açılış <b class="num">${l.opened}</b></span>` : "",
    city ? `<button class="lnk" data-city="${city.key}">${esc(city.name)}</button>` : `<span>${TY[l.type].label}</span>`,
    l.status !== "open" && l.target && !/^(Yok|Belirsiz)$/.test(l.target) ? `<span>Resmi hedef <b>${esc(l.target)}</b></span>` : "",
    l.statusNote ? `<span class="warn">${esc(l.statusNote)}</span>` : ""].filter(Boolean).join("");
  const stats = [l.count ? statHTML(l.count, l.stopsKind === "route" ? "İstasyon (güzergâhta)" : "İstasyon") : "", statHTML(`${nf(l.km)} km`, "Uzunluk"),
    l.time ? statHTML(l.time.replace("~ ", "~"), "Tek yön yolculuk") : "", l.freq ? statHTML(l.freq, "Sefer") : "", l.fleet ? statHTML(l.fleet, "Araç sayısı") : ""].join("");
  // asOf dates the latest report: it heads the note, or sits with the progress figure when there is no note
  const note = l.status !== "open" && l.update, asOf = l.asOf ? ` · ${esc(l.asOf)}` : "";
  const prog = (l.status === "construction" && l.progress != null ? `
    <div class="prog"><div class="pv"><b class="num">%${nf(l.progress)}</b><span>fiziki ilerleme${note ? "" : asOf}</span></div><div class="bar"><i style="background:${l.city ? l.color : TH()[l.type]}"></i></div>
      ${l.target ? `<div class="dates"><div><b>${esc(l.target)}</b><span>Resmi açılış hedefi</span></div></div>` : ""}</div>` : "")
    + (note ? `<div class="note"><b>Son durum${asOf ? `<span>${asOf}</span>` : ""}</b><p>${esc(l.update)}</p></div>` : "");
  const ride = l.status !== "open" ? "" : `<div class="sec rsec"><h3>Yolcu sayısı</h3>${l.ride ? rideHTML(l.ride) : `<div class="nodata"><b>Veri yok</b><span>Bu ${l.city ? "hat" : "sefer"} için yayımlanmış ayrı bir yolcu sayısı bulunamadı.</span></div>`}${groupFigHTML(l.rideGroup)}</div>`;
  const osm = (l.osm || []).map(id => `<a href="https://www.openstreetmap.org/relation/${id}" target="_blank" rel="noopener">${id}</a>`).join(", ");
  const facts = [["Proje", l.project && esc(l.project)], [l.status === "open" ? "İşletmeci" : "Sorumlu kurum", who && esc(who)], ["Tasarım hızı", l.speed && esc(l.speed)], ["Hat kesimi", l.pso && `${esc(l.pso)}<small>2026 kamu hizmeti yükümlülüğü kapsamındaki hat kesimi (Cumhurbaşkanı Kararı 11800)</small>`],
    ["Yüklenici", l.contractor && esc(l.contractor)], ["Araç modeli", l.model && esc(l.model)],
    ["Ana hat", parent && `<button class="lnk" data-line="${parent.id}">${esc(parent.code + " " + parent.name)}</button>`], ["OSM", osm]]
    .filter(f => f[1]).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  const notes = [l.note, l.approx ? l.approxNote || "Bu güzergâhın bir bölümü OpenStreetMap'te yenileme nedeniyle parçalı; çizim o kesimde yaklaşıktır." : ""].filter(Boolean);
  const day = d => /^\d{4}-\d\d-\d\d$/.test(d || "") ? d.split("-").reverse().join(".") : d || "";
  const sources = l.sources?.length ? `<div class="sec"><h3>Kaynaklar</h3><ul class="srcs">${l.sources.map(s => `<li>${srcLink(s)}<span>${esc([s.publisher, day(s.date)].filter(Boolean).join(" · "))}</span></li>`).join("")}</ul></div>` : "";
  const sections = l.sections ? `<div class="sec"><h3>Kesimler</h3><ul class="parts">${l.sections.map(p => `<li><b>${esc(p.name)}</b><span>${esc([p.note, p.stations && `${p.stations} istasyon`, p.km && `${nf(p.km)} km`, p.time, p.fleet].filter(Boolean).join(" · "))}</span></li>`).join("")}</ul></div>` : "";
  const related = LINES.filter(o => l.city && o.city === l.city && o.code === l.code && o !== l && o !== parent);
  const siblings = l.project ? LINES.filter(o => o.project === l.project && o !== l && !related.includes(o)) : [];
  const stNote = l.stopsKind === "yht" ? "başlıca YHT durakları" : l.stopsKind === "route" ? "güzergâhtaki istasyonlar; trenler hepsinde durmaz" : `${l.count} istasyon${l.stations.length > l.count ? ` · ${l.stations.length - l.count} mevcut istasyona bağlanır` : ""}`;
  el.innerHTML = `
    ${homeBar()}
    <figure class="route" style="--c:${l.city ? l.color : TH()[l.type]};margin-top:0">${routeSVG(l)}</figure>
    <p class="eyebrow">${badge(l)}<span>${TY[l.type].label}</span>${who ? `<span>·</span><span>${esc(who.replace(/ Daire Başkanlığı$/, "").replace(/ \(.*\)$/, ""))}</span>` : ""}</p>
    <h2>${esc(l.name)}</h2>
    ${sub ? `<p class="det-sub">${esc(sub)}</p>` : ""}
    <div class="state">${state}</div>
    ${ride}
    ${l.status === "open" ? durHTML(l) : ""}
    <div class="stats">${stats}</div>
    ${prog}
    ${notes.map(n => `<div class="note"><b>Not</b><p>${esc(n)}</p></div>`).join("")}
    <div class="sec"><h3>Hat bilgisi</h3><dl class="dl">${facts}</dl></div>
    ${sections}
    ${l.stations.length ? `<div class="sec"><h3>İstasyonlar <span>${stNote}</span></h3>${stripHTML(l, full)}</div>` : ""}
    ${l.history ? `<div class="sec"><h3>Tarihçe</h3><ul class="hist">${l.history.map(h => `<li><time>${esc(h.date)}</time><span>${esc(h.text)}</span></li>`).join("")}</ul></div>` : ""}
    ${related.length ? `<div class="sec"><h3>Aynı hattın diğer kesimleri</h3><ul class="plist">${related.sort(byLine).map(row).join("")}</ul></div>` : ""}
    ${siblings.length ? `<div class="sec"><h3>Projenin diğer kesimleri</h3><ul class="plist">${siblings.sort(byLine).map(row).join("")}</ul></div>` : ""}
    ${sources}`;
  if (fresh) enter(el);
  const fig = el.querySelector(".route");
  if (fig && !reduced && fresh) { fig.querySelectorAll("path").forEach(p => p.style.setProperty("--len", Math.ceil(p.getTotalLength()))); fig.classList.add("draw"); }
  requestAnimationFrame(() => { const bar = el.querySelector(".prog .bar i"); if (bar) bar.style.width = clamp(l.progress, 0, 100) + "%"; });
}

/* ---------- panel: a city ---------- */
function renderCity(c) {
  const el = $("#v-city");
  const own = c.lineObjs.filter(passes), serving = c.serving.map(id => BY[id]).filter(l => l && passes(l));
  const open = openLines(own);
  const withRide = open.filter(l => l.ride?.annual && !l.ride.partial && !l.ride.season);
  const km = open.reduce((a, l) => a + l.km, 0);
  const groups = TYPES.filter(t => t.g === "urban").map(t => [t, own.filter(l => l.type === t.k).sort(byLine)]).filter(([, g]) => g.length);
  const maxR = Math.max(1, ...withRide.map(l => l.ride.annual));
  const bars = withRide.sort((a, b) => b.ride.annual - a.ride.annual).map(l => `<li><button data-id="${l.id}">${badge(l)}<span class="k">${esc(l.name)}</span><span class="track"><i style="width:${100 * l.ride.annual / maxR}%;background:${l.color}"></i></span><span class="s">${esc(String(l.ride.year))}${l.ride.dailyKind === "derived" ? ` · ortalama ${nf(l.ride.daily, 0)}/gün` : ""}</span><span class="v num">${prec(l.ride.precision, shortN(l.ride.annual))}</span></button></li>`).join("");
  const built = c.lineObjs.some(l => l.status === "open"); // a city with only projects has no network figures to show
  const sysNote = c.ride ? `<div class="sec rsec"><h3>Yolcu sayısı <span>${esc(c.ride.label)}</span></h3>${rideHTML(c.ride)}</div>` : "";
  el.innerHTML = `
    ${homeBar("country", "Türkiye geneli")}
    <p class="eyebrow"><span>Şehir</span><span>·</span><span>${[`${c.lineObjs.filter(l => l.status === "open").length} hat işletmede`, projectText(c)].filter(Boolean).join(" · ")}</span></p>
    <h2>${esc(c.name)}</h2>
    <p class="det-sub">${esc(listTr(TYPES.filter(t => t.g === "urban" && c.lineObjs.some(l => l.status === "open" && l.type === t.k)).map((t, i) => i ? t.label.toLocaleLowerCase("tr") : t.label)))}</p>
    ${built ? `<div class="stats big">${statHTML(open.length, "hat işletmede")}${statHTML(`${nf(km, 0)} km`, "şehir içi hat")}${statHTML(nf(stationCount(open), 0), "istasyon")}${c.annual ? statHTML(big(c.annual), c.ride ? `yıllık yolcu · ${c.ride.short || "işletmeci toplamı"} · ${c.ride.year}` : "yıllık yolcu · hat toplamı") : ""}</div>
    <div class="scope" data-city="${c.key}" role="group" aria-label="Şehirlerarası ve şehir içi hatlar"></div>` : ""}
    ${groups.map(([t, g]) => `<div class="grp">${grpHead(t.label, g.length, swatch(t.k, 22))}<ul class="plist">${g.map(row).join("")}</ul></div>`).join("")}
    ${serving.length ? `<div class="grp">${grpHead("Şehirlerarası trenler", serving.length)}<ul class="plist">${serving.sort((a, b) => RANK[a.status] - RANK[b.status] || TY[a.type].i - TY[b.type].i || b.daily - a.daily).map(row).join("")}</ul></div>` : ""}
    ${!groups.length && !serving.length ? `<p class="empty">Seçili türlerde bu şehirde hat yok. <button data-clear="1">Tümünü göster</button></p>` : ""}
    ${bars ? `<div class="sec"><h3>Hatlara göre yolcu <span>yıllık</span></h3><ul class="bars">${bars}</ul></div>` : ""}
    ${sysNote}`;
  renderScopes();
}

const listTr = a => a.length > 1 ? a.slice(0, -1).join(", ") + " ve " + a[a.length - 1] : a.join("");

/* ---------- panel: a station ---------- */
function renderStation(c, fresh) {
  const el = $("#v-station"), [lon, lat] = c.at;
  const open = c.lines.filter(l => l.status === "open").length;
  const near = CX.filter(o => o !== c).map(o => ({ o, d: dist(c.at, o.at) })).filter(x => x.d < 600).sort((a, b) => a.d - b.d).slice(0, 6);
  el.innerHTML = `
    ${homeBar()}
    <p class="eyebrow"><span>İstasyon</span>${c.codes.size > 1 ? "<span>·</span><span>Aktarma</span>" : ""}</p>
    <h2>${esc(c.name)}</h2>
    <p class="det-sub">${c.lines.length} hat${open && open < c.lines.length ? `, ${open} tanesi işletmede` : ""}</p>
    <div class="sec"><h3>Bu istasyondan geçen hatlar</h3><ul class="plist">${c.lines.map(row).join("")}</ul></div>
    ${near.length ? `<div class="sec"><h3>Yürüme mesafesinde <span>kuş uçuşu</span></h3><ul class="plist">${near.map(({ o, d }) => stationRow(o, `${Math.round(d / 10) * 10} m`)).join("")}</ul></div>` : ""}
    <div class="links"><a href="https://www.google.com/maps/search/?api=1&query=${lat},${lon}" target="_blank" rel="noopener">Google Haritalar ↗</a><a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}" target="_blank" rel="noopener">OpenStreetMap ↗</a></div>`;
  if (fresh) enter(el);
}
for (const id of ["#v-line", "#v-station", "#v-city"]) {
  $(id).addEventListener("click", e => {
    const b = e.target.closest("[data-act], [data-line], .sn"); if (!b || b.closest(".row")) return;
    if (b.dataset.act === "home") return home();
    if (b.dataset.act === "country") return setCity(null);
    if (b.dataset.act === "all") { const t = top(); if (t && t.k === "line") { const y = $("#pbody").scrollTop; renderLine(BY[t.id], false, true); $("#pbody").scrollTop = y; } return; }
    if (b.dataset.line) return select(b.dataset.line);
    const s = STA[+b.dataset.s]; if (!s) return;
    setRing([s.i]); flyToStation(s.at, s.line.city ? 15 : 12);
    if (phone()) setSheet("peek");
  });
  $(id).addEventListener("mouseover", e => { const li = e.target.closest(".strip li[data-s]"); if (li) setRing([+li.dataset.s]); });
}
document.addEventListener("click", e => { const b = e.target.closest(".state [data-city]"); if (b) setCity(b.dataset.city); });
// a stop on the time strip, or a time in the station list: count the minutes from that stop
$("#v-line").addEventListener("click", e => {
  const b = e.target.closest("[data-tm]"), t = top(); if (!b || !t || t.k !== "line") return;
  tOrigin = { id: t.id, name: b.dataset.tm };
  const y = $("#pbody").scrollTop; renderLine(BY[t.id], false, !$("#v-line .showall")); $("#pbody").scrollTop = y;
});

/* ---------- panel: summary ---------- */
function renderInsights() {
  const v = openLines(LINES.filter(passes));
  const tiles = GROUPS.map(g => { const ls = v.filter(l => l.g === g.k); return `<div class="tile"><b class="num">${nf(Math.round(trackKm(ls) / 10) * 10, 0)}<small>km</small></b><span>${g.label}<br>${ls.length} hat · ${nf(stationCount(ls), 0)} istasyon</span></div>`; }).join("")
    + `<div class="tile"><b class="num">${CITIES.filter(c => c.lineObjs.some(l => l.status === "open" && passes(l))).length}</b><span>Şehir içi raylı<br>sistemi olan şehir</span></div>`;
  const ranked = v.filter(l => l.ride?.annual && !l.ride.partial && !l.ride.season).sort((a, b) => b.ride.annual - a.ride.annual).slice(0, 20);
  const maxR = ranked[0]?.ride.annual || 1;
  const bars = ranked.map(l => `<li><button data-id="${l.id}">${badge(l)}<span class="k">${esc(l.name)}${l.city ? ` <em>${esc(CITY[l.city].name)}</em>` : ""}</span><span class="track"><i style="width:${100 * l.ride.annual / maxR}%;background:${l.city ? l.color : TH()[l.type]}"></i></span><span class="s">${esc(String(l.ride.year))} · ${l.ride.dailyKind === "derived" ? "ortalama " : ""}${nf(l.ride.daily, 0)}/gün</span><span class="v num">${prec(l.ride.precision, shortN(l.ride.annual))}</span></button></li>`).join("");
  const cmax = Math.max(1, ...CITIES.map(c => c.annual));
  const cities = CITIES.map(c => { const ls = openLines(c.lineObjs.filter(passes)); return `<li><button data-city="${c.key}"><span class="k">${esc(c.name)}</span><span class="track">${c.annual ? `<i style="width:${100 * c.annual / cmax}%;background:var(--ink-2)"></i>` : ""}</span><span class="s">${ls.length} hat · ${nf(ls.reduce((a, l) => a + l.km, 0), 0)} km${c.ride?.year ? ` · ${c.ride.year}` : ""}</span><span class="v num">${c.annual ? shortN(c.annual) : "—"}</span></button></li>`; }).join("");
  const types = TYPES.map(t => { const ls = v.filter(l => l.type === t.k), km = trackKm(ls); return { t, ls, km }; });
  const kmax = Math.max(1, ...types.map(x => x.km));
  const typeBars = types.map(({ t, ls, km }) => `<li><button data-type="${t.k}"><span class="k">${t.label}</span><span class="track"><i style="width:${100 * km / kmax}%;background:${t.c}"></i></span><span class="s">${ls.length} hat</span><span class="v num">${nf(Math.round(km), 0)} km</span></button></li>`).join("");
  const nat = GROUPFIG.map(g => `<li><b class="num">${big(g.annual)}</b><span>${esc(g.label)} · ${g.year} · ${srcLink(g.src, "kaynak")}</span></li>`).join("");
  // published intercity journey times, shortest first; YHT and ana hat each on their own scale (90 minutes against 32 hours)
  const timed = v.filter(l => !l.city && l.dur?.dirs[0].min);
  const times = [["hst", "Yüksek hızlı tren"], ["main", "Ana hat"]].map(([k, label]) => [label, timed.filter(l => l.type === k).sort((a, b) => a.dur.dirs[0].min - b.dur.dirs[0].min)]).filter(([, ls]) => ls.length)
    .map(([label, ls]) => { const mx = Math.max(...ls.map(l => l.dur.dirs[0].min)); return `<p class="tb-h">${label}</p><ul class="bars times">${ls.map(l => { const d = l.dur;
      return `<li><button data-id="${l.id}">${badge(l)}<span class="k">${esc(l.dur.dirs.length > 1 ? d.dirs[0].label : l.name)}${l.alias ? ` <em>${esc(l.alias)}</em>` : ""}</span><span class="track"><i style="width:${100 * d.dirs[0].min / mx}%;background:${TH()[l.type]}"></i></span><span class="s">${[d.avg && `ortalama ${d.avgApprox ? "≈ " : ""}${d.avg} km/sa`, d.stopsIncluded && "duruşlar dahil", d.src.date?.slice(0, 4)].filter(Boolean).join(" · ")}</span><span class="v num">${durText(d)}</span></button></li>`; }).join("")}</ul>`; }).join("");
  $("#v-insights").innerHTML = `
    <div class="tiles">${tiles}</div>
    <div class="sec"><h3>En çok yolcu taşıyan hatlar <span>yıllık</span></h3><ul class="bars">${bars}</ul>
      <p class="muted">Yalnızca hat bazında yayımlanmış rakamlar. Yıllar (2024 ya da 2025) ve sayım birimleri (yolcu, biniş, kart basma) kaynağa göre değişir; her hattın sayfasında kaynağı yazılıdır.</p></div>
    ${times ? `<div class="sec"><h3>Şehirlerarası yolculuk süreleri <span>tek yön</span></h3>${times}
      <p class="muted">Bakanlığın ve TCDD'nin yayımladığı süreler; sefere göre değişebilir. Her grup kendi ölçeğindedir. Ortalama hız, yayımlanmış uzunluğun süreye bölünmesidir. Kaynak ve tarih hattın sayfasındadır.</p></div>` : ""}
    <div class="sec"><h3>Şehirlere göre <span>şehir içi raylı sistem, yıllık yolcu</span></h3><ul class="bars plain">${cities}</ul>
      <p class="muted">İşletmecinin yayımladığı ağ toplamı; yoksa hat rakamlarının toplamı. TCDD banliyö hatları (Marmaray, Başkentray, İZBAN) şehir toplamına dahil değildir, kendi sayfalarında yer alır.</p></div>
    <div class="sec"><h3>Türlere göre <span>güzergâh uzunluğu</span></h3><ul class="bars plain">${typeBars}</ul>
      <p class="muted">Aynı rayı kullanan seferler bir kez sayılır.</p></div>
    ${nat ? `<div class="sec"><h3>TCDD yolcu toplamları</h3><ul class="natl">${nat}</ul></div>` : ""}`;
}
$("#v-insights").addEventListener("click", e => {
  const b = e.target.closest("[data-id], [data-city], [data-type], a"); if (!b || b.tagName === "A") return;
  if (b.dataset.id) return select(b.dataset.id);
  if (b.dataset.city) return setCity(b.dataset.city);
  picked.clear(); picked.add(b.dataset.type); pickedSt.clear(); stack.length = 0; cityKey = null; renderPresets(); setTab("lines"); applyFilters(); fitVisible();
});

/* ---------- tabs ---------- */
function setTabs() { $("#tab-lines").setAttribute("aria-selected", tab === "lines"); $("#tab-insights").setAttribute("aria-selected", tab === "insights"); }
function setTab(t) {
  tab = t; setTabs(); showView();
  if (t === "insights") { renderInsights(); enter($("#v-insights")); }
  else { const v = top(); if (!v) { renderRoot(); enter(cityKey ? $("#v-city") : $("#v-list")); } else if (v.k === "line") renderLine(BY[v.id], true); else renderStation(CX[v.id], true); }
  $("#pbody").scrollTop = 0;
}
$("#tab-lines").addEventListener("click", () => { if (tab === "lines" && stack.length) home(); else setTab("lines"); });
$("#tab-insights").addEventListener("click", () => { setTab("insights"); setSheet("full"); });

/* ---------- legend ---------- */
function renderLegend() {
  const v = LINES.filter(l => l.status === "open" && (!cityKey || inScope(l)));
  const dot = (stroke, sw, r) => `<svg width="30" height="14" viewBox="0 0 30 14" aria-hidden="true"><circle cx="15" cy="7" r="${r}" fill="#fff" stroke="${stroke}" stroke-width="${sw}"/></svg>`;
  const groups = GROUPS.map(g => {
    const st = groupState(g.k);
    const keys = TYPES.filter(t => t.g === g.k).map(t => { const n = v.filter(l => l.type === t.k).length; return `<li><button data-t="${t.k}" class="${typeOn(t.k) ? "" : "off"}${picked.has(t.k) ? " sel" : ""}" aria-pressed="${picked.has(t.k)}">${swatch(t.k)}<span>${t.label}</span><span class="n num">${n}</span></button></li>`; }).join("");
    return `<div class="kg ${st}"><button class="kg-h" data-g="${g.k}" aria-pressed="${st === "on"}"><span class="ck" aria-hidden="true"></span><b>${g.label}</b></button><ul class="keys">${keys}</ul></div>`;
  }).join("");
  const statusKeys = STATUS.filter(s => LINES.some(l => l.status === s.k)).map(s => `<li><button data-st="${s.k}" class="${statusOn(s.k) ? "" : "off"}${pickedSt.has(s.k) ? " sel" : ""}" aria-pressed="${pickedSt.has(s.k)}">${statusSwatch(s)}<span>${s.label}</span><span class="n num">${LINES.filter(l => l.status === s.k && (!cityKey || inScope(l))).length}</span></button></li>`).join("");
  $("#keys").innerHTML = groups + `<ul class="keys extra">${statusKeys}<li><span class="k"><svg class="sw" width="30" height="8" viewBox="0 0 30 8"><path d="M3 4h24" stroke="${TH().rail}" stroke-width="1.6"/></svg><span>Yolcu treni olmayan hat</span></span></li>`
    + `<li><span class="k"><svg class="sw" width="30" height="8" viewBox="0 0 30 8"><path d="M3 4h24" stroke="${TH().rail}" stroke-width="1.6" stroke-dasharray="3 3"/></svg><span>Yapım ya da yenileme</span></span></li>`
    + `<li><span class="k">${dot("#1a1a1a", 2.4, 4.6)}<span>Raylı sistemi olan şehir</span></span></li></ul>`;
}
$("#keys").addEventListener("click", e => {
  const b = e.target.closest("[data-g], [data-t], [data-st]"); if (!b) return;
  if (b.dataset.g) pickGroup(b.dataset.g);
  else if (b.dataset.t) pickType(b.dataset.t);
  else pickStatus(b.dataset.st);
});
$("#keys").addEventListener("mouseover", e => { const b = e.target.closest("[data-t]"); setHoverType(b && typeOn(b.dataset.t) ? b.dataset.t : null); });
$("#keys").addEventListener("mouseleave", () => setHoverType(null));
$("#lg-reset").addEventListener("click", resetFilters);
function setBaseButtons() { for (const b of document.querySelectorAll("#basemaps button")) b.setAttribute("aria-pressed", b.dataset.base === base); }
$("#basemaps").addEventListener("click", async e => {
  const b = e.target.closest("[data-base]"); if (!b || b.dataset.base === base) return;
  stopIntro();
  base = b.dataset.base; store.set("base", base); setBaseButtons();
  lineFC = lineFeatures(); staFC = stationFeatures();
  try { map.setStyle(await styleFor(base), { diff: false }); } catch (err) { console.error(err); toast("Altlık harita yüklenemedi"); }
  renderLegend();
});
// ridership mode: line width follows average daily passengers (area-true: width grows with the square root)
function renderRideScale() {
  const el = $("#ride-scale");
  el.hidden = !rideMode;
  if (!rideMode || !map) return;
  const k = kAt(map.getZoom());
  el.innerHTML = [10000, 100000, 500000].map(n => `<span><i style="height:${clamp(Math.sqrt(n) * k, 1.2, 24).toFixed(1)}px"></i>${shortN(n)}</span>`).join("") + `<small>günlük yolcu · ince çizgi: veri yok</small>`;
}
$("#ride-mode").addEventListener("change", e => {
  rideMode = e.target.checked;
  pushData(); paintFocus(); renderRideScale();
  if (rideMode) toast("Çizgi kalınlığı artık günlük yolcu sayısını gösteriyor");
});

/* ---------- controls ---------- */
$("#zin").addEventListener("click", () => map.zoomIn({ duration: reduced ? 0 : 380 }));
$("#zout").addEventListener("click", () => map.zoomOut({ duration: reduced ? 0 : 380 }));
$("#zfit").addEventListener("click", () => { map.easeTo({ pitch: tilt ? 58 : 0, bearing: tilt ? -18 : 0, duration: 0 }); const t = top(); if (t && t.k === "line") flyToLine(BY[t.id]); else fitVisible(); });
$("#tilt").addEventListener("click", () => {
  tilt = !tilt; $("#tilt").setAttribute("aria-pressed", tilt);
  if (tilt) addBuildings();
  const t = top(), cam = t && t.k === "line" ? map.cameraForBounds(BY[t.id].bounds, { padding: pad(), maxZoom: 14.2 }) || {} : {};
  map.easeTo({ ...cam, pitch: tilt ? 58 : 0, bearing: tilt ? -18 : 0, zoom: cam.zoom ?? map.getZoom(), duration: reduced ? 0 : 1200 });
  if (!tilt && map.getLayer("x-bldg")) map.once("moveend", () => { if (!tilt && map.getLayer("x-bldg")) map.removeLayer("x-bldg"); });
});
$("#layers").addEventListener("click", () => { const open = !$("#legend").classList.contains("open"); $("#legend").classList.toggle("open", open); $("#layers").setAttribute("aria-expanded", open); });
$("#lg-close").addEventListener("click", () => { $("#legend").classList.remove("open"); $("#layers").setAttribute("aria-expanded", false); });
// the arrow at the foot of the legend folds the filters away for this visit (every visit starts open); while folded, a cue says how many filters are on
function foldCue() { const n = picked.size + pickedSt.size; $("#lg-cue").textContent = n ? `${n} süzgeç açık` : ""; }
function setFold(f) {
  $("#legend").classList.toggle("folded", f);
  $("#lg-tog").setAttribute("aria-expanded", !f); $("#lg-tog").setAttribute("aria-label", f ? "Süzgeçleri göster" : "Süzgeçleri gizle");
}
$("#lg-tog").addEventListener("click", () => setFold(!$("#legend").classList.contains("folded")));
$("#locate").addEventListener("click", () => {
  if (!navigator.geolocation) return toast("Tarayıcınız konum paylaşmayı desteklemiyor");
  toast("Konumunuz alınıyor…");
  navigator.geolocation.getCurrentPosition(pos => {
    const me = [pos.coords.longitude, pos.coords.latitude];
    meFC = { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: me } }] };
    map.getSource("me")?.setData(meFC);
    let best = null, bd = Infinity;
    for (const c of CX) if (c.lines.some(l => l.status === "open")) { const d = dist(me, c.at); if (d < bd) { bd = d; best = c; } }
    // outside Türkiye the map could only stop at the edge of TR, so it stays where it is
    const inTR = me[0] > TR[0][0] && me[0] < TR[1][0] && me[1] > TR[0][1] && me[1] < TR[1][1];
    if (!best || bd > 150000) { if (inTR) map.flyTo({ center: me, zoom: 9, duration: reduced ? 0 : 1200 }); return toast("Yakınınızda yolcu taşıyan bir hat yok"); }
    fly([[Math.min(me[0], best.at[0]), Math.min(me[1], best.at[1])], [Math.max(me[0], best.at[0]), Math.max(me[1], best.at[1])]], 16);
    setRing(best.members.map(m => m.i));
    toast(`En yakın istasyon <b>${esc(best.name)}</b> · ${bd < 1000 ? Math.round(bd / 10) * 10 + " m" : nf(bd / 1000) + " km"}`, ["Aç", () => openStation(best.id)]);
  }, () => toast("Konumunuz alınamadı"), { enableHighAccuracy: true, timeout: 10000 });
});
let toastTimer = 0;
function toast(html, action) {
  const el = $("#toast");
  el.innerHTML = html + (action ? ` <button>${action[0]}</button>` : "");
  if (action) el.querySelector("button").onclick = () => { el.classList.remove("on"); action[1](); };
  el.classList.add("on"); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("on"), action ? 6000 : 2600);
}

/* ---------- desktop and tablet: the panel folds away to the left ---------- */
// the tab stays at the screen edge to bring it back, and so does opening a city, a line or a station from the map, search,
// a city button or a link. The city buttons give the room back at once and take it once the panel has gone (transitionend).
let panelOpen = true;
function setPanel(open, still) {
  if (open === panelOpen && !still) return;
  const app = $("#app"), b = $("#ptab"), label = open ? "Paneli gizle" : "Paneli göster", jump = still || reduced;
  panelOpen = open; store.set("panel", open ? "open" : "closed");
  if (jump) app.classList.add("still"); // the remembered state is applied on load without the slide
  app.classList.toggle("folded", !open);
  if (jump) { void app.offsetWidth; app.classList.remove("still"); }
  b.setAttribute("aria-expanded", open); b.setAttribute("aria-label", label); b.title = label;
  fitPresets();
}
$("#ptab").addEventListener("click", () => setPanel(!panelOpen));
$("#presets").addEventListener("transitionend", e => { if (e.propertyName === "left") fitPresets(); });
setPanel(store.get("panel") !== "closed", true);

/* ---------- phones: the panel is a bottom sheet ---------- */
const SHEET = { peek: () => 170, half: () => Math.round(innerHeight * .5), full: () => Math.round(innerHeight - 64) };
let sheet = "peek", sheetPx = 170;
function setSheet(name) {
  if (!phone()) return;
  sheet = name; sheetPx = SHEET[name]();
  $("#app").style.setProperty("--sheet", sheetPx + "px");
}
(() => {
  let y0 = 0, h0 = 0, moved = false, t0 = 0, active = false;
  const start = e => {
    if (!phone() || (e.target.closest("button, input") && !e.target.closest("#grab"))) return;
    active = true; moved = false; y0 = e.clientY; t0 = performance.now(); h0 = $("#panel").getBoundingClientRect().height;
    $("#panel").classList.add("drag");
  };
  const move = e => { if (!active) return; const dy = e.clientY - y0; if (Math.abs(dy) > 4) moved = true; $("#app").style.setProperty("--sheet", clamp(h0 - dy, 120, innerHeight - 40) + "px"); };
  const end = e => {
    if (!active) return; active = false; $("#panel").classList.remove("drag");
    const h = $("#panel").getBoundingClientRect().height, v = (e.clientY - y0) / (performance.now() - t0);
    if (!moved) return setSheet(sheet === "peek" ? "half" : "peek");
    const names = ["peek", "half", "full"];
    let best = names.reduce((a, n) => Math.abs(SHEET[n]() - h) < Math.abs(SHEET[a]() - h) ? n : a, "peek");
    if (Math.abs(v) > .5) best = names[clamp(names.indexOf(sheet) + (v < 0 ? 1 : -1), 0, 2)];
    setSheet(best);
  };
  for (const el of [$("#grab"), $("#phead")]) el.addEventListener("pointerdown", start);
  addEventListener("pointermove", move); addEventListener("pointerup", end); addEventListener("pointercancel", end);
})();

addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); setPanel(true); stack.length = 0; if (cityKey) setCity(null, { fly: false }); else showView(); setTab("lines"); $("#q").focus(); }
  if (e.key === "Escape" && !typing) { if (stack.length) back(); else if (cityKey) setCity(null); }
});

/* ---------- boot ---------- */
const json = u => fetch(u).then(r => { if (!r.ok) throw new Error(u); return r.json(); });
const fontsReady = Promise.race([document.fonts ? document.fonts.load(`800 11px "Open Sans"`) : null, new Promise(r => setTimeout(r, 1500))]);
function route() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (BY[h]) { if (BY[h].city) setCity(BY[h].city, { fly: false }); select(h); }
  else if (CITY[h]) setCity(h, { grow: false }); // the opening has just grown its lines
  else if (h.startsWith("istasyon/") && CX_BY_SLUG[h.slice(9)]) openStation(CX_BY_SLUG[h.slice(9)].id);
  else if (h === "ozet") { setPanel(true); setTab("insights"); }
}
const firstStyle = styleFor(base); // the basemap's style downloads alongside the data
Promise.all([json("data/lines.json"), json("data/network.geojson"), fontsReady]).then(async ([data, net]) => {
  prep(data, net);
  for (const l of LINES) l.vis = passes(l);
  $("#q").placeholder = `${LINES.filter(l => l.status === "open").length} hat, ${CITIES.length} şehir ya da ${nf(CX.length, 0)} istasyon ara`;
  renderPresets(); renderLegend(); renderRoot(); setBaseButtons();
  pushData();
  const h = decodeURIComponent(location.hash.slice(1));
  const startBounds = CITY[h] ? CITY[h].bounds : BY[h] ? BY[h].bounds : TURKEY;
  $("#map").classList.toggle("dark", !!BASES[base].dark);
  map = new maplibregl.Map({
    container: "map", style: await firstStyle, bounds: startBounds, fitBoundsOptions: { padding: pad() },
    attributionControl: false, maxPitch: 70, dragRotate: true, pitchWithRotate: true, minZoom: 3.5, transformCameraUpdate: keepInTR,
  });
  setFloor(); map.on("resize", setFloor);
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Hatlar ve istasyonlar © <a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\">OpenStreetMap katkıcıları</a> (ODbL)" }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 90 }), "bottom-right");
  map.on("style.load", installOverlay);
  map.on("styleimagemissing", e => { if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) }); });
  map.on("zoomend", renderRideScale);
  // The basemap is shown once it is fully drawn ("load": its tiles are in and on screen), never half-loaded; the cities
  // and the lines then come in on top. Not "idle": the moving dashes of the lines being built keep the map from ever
  // resting. A basemap that never finishes loading is shown after a while all the same.
  let shown = false;
  const show = () => {
    if (shown) return;
    if (!map.getLayer("c-dot")) return map.once("style.load", show);
    shown = true;
    $("#map").classList.add("ready");
    requestAnimationFrame(tick); wireMap(); // a link in the address is opened when the opening ends
    setTimeout(intro, reduced ? 0 : 450);
    // the rest of the railway arrives after the network, so the opening is not held up by it
    json("data/base.geojson").then(b => { baseFC = b; map.getSource("base")?.setData(b); }).catch(() => {});
  };
  map.once("load", show); setTimeout(show, 8000);
  addEventListener("resize", () => { if (phone()) setSheet(sheet); fitPresets(); });
  addEventListener("hashchange", () => { if (hashFor() !== location.hash) route(); });
}).catch(err => {
  console.error(err);
  $("#list").innerHTML = `<p class="empty">Hat verisi yüklenemedi. Sayfayı yenileyip tekrar deneyin.</p>`;
});
})();
