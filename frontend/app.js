/* ============================================================
 * HydroMap — frontend completo
 *   - mappa Leaflet con basemap switcher
 *   - zone (Acea Ato 2) con coropletico per parametro
 *   - news geolocalizzate con cluster + filtri categoria
 *   - nasoni Roma (OSM Overpass)
 *   - acquedotti storici (polylines)
 *   - sidebar a tab: Zona / Dashboard / News / Confronto / Chat AI / Info
 *   - search bar globale con autocomplete
 *   - Chart.js per dashboard
 * ============================================================ */

// ---------- API base URL (per deploy split frontend/backend) ----------
// Configurabile via <meta name="api-base" content="https://..."> in index.html
// oppure window.API_BASE prima del caricamento dello script.
// Lasciato vuoto = same-origin (sviluppo locale o monolito).
const API_BASE = (
  window.API_BASE
  || document.querySelector('meta[name="api-base"]')?.content
  || ""
).replace(/\/$/, "");
const API = (p) => API_BASE + p;

// ---------- mappa + basemaps ----------
const BASEMAPS = {
  osm:      { url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
              attr: '&copy; OpenStreetMap', maxZoom: 19 },
  positron: { url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
              attr: '&copy; OSM &copy; CARTO', maxZoom: 19 },
  dark:     { url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              attr: '&copy; OSM &copy; CARTO', maxZoom: 19 },
  sat:      { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
              attr: 'Tiles &copy; Esri', maxZoom: 19 },
  topo:     { url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
              attr: '&copy; OpenTopoMap', maxZoom: 17 },
};

const map = L.map("map", { preferCanvas: true }).setView([41.85, 12.66], 9);
let baseLayer = null;
function setBasemap(key) {
  if (baseLayer) map.removeLayer(baseLayer);
  const b = BASEMAPS[key] || BASEMAPS.osm;
  baseLayer = L.tileLayer(b.url, { maxZoom: b.maxZoom, attribution: b.attr });
  baseLayer.addTo(map);
}
setBasemap("osm");
document.getElementById("basemap-select").addEventListener("change", e => setBasemap(e.target.value));

// ---------- state ----------
const state = {
  geoData: null,
  geoLayer: null,
  selectedLayer: null,
  newsItems: [],
  newsCategories: {},
  newsCluster: null,
  activeCategory: "tutte",
  nasoniLayer: null,
  aqueductsLayer: null,
  bracciantoLayer: null,
  parameter: "",      // parametro coropletico attivo
  paramData: null,
  compareList: [],    // names
};

const SELECTED_STYLE = { weight: 2.5, color: "#0c4a6e", fillOpacity: 0.7 };
const SEVERITY_RANK = { alert: 3, warning: 2, info: 1 };
const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// ---------- NAMING HELPERS ----------
// Il PDF Acea usa nomi come "5 ACQUA MARCIA" o "3 PESCHIERA-CAPORE"
// dove la prima cifra è il numero di zona e il resto è l'acquedotto fornitore.
// Questi nomi (specie "Acqua Marcia") confondono gli utenti che pensano a
// "acqua marcia" = guasta. Li separiamo esplicitamente.
const AQUEDUCT_INFO = {
  "ACQUA MARCIA": "Storico acquedotto romano del 144 a.C. — il nome 'Marcia' deriva dal pretore Quinto Marcio Re, non dalla qualità dell'acqua. Oggi capta sorgenti dell'alto Aniene.",
  "PESCHIERA-CAPORE": "Principale acquedotto di Roma: sorgenti di Peschiera (Rieti) e Capore. Fornisce ~70% dell'acqua della Capitale.",
  "PESCHIERA CAPORE": "Principale acquedotto di Roma: sorgenti di Peschiera (Rieti) e Capore. Fornisce ~70% dell'acqua della Capitale.",
  "APPIO-ALESSANDRINO": "Acquedotto della zona sud-est di Roma, integra l'apporto principale.",
  "APPIO ALESSANDRINO": "Acquedotto della zona sud-est di Roma, integra l'apporto principale.",
  "DOGANELLA": "Sorgenti dei Castelli Romani (Frascati/Doganella).",
};
function prettyZoneInfo(zonaRaw) {
  const raw = String(zonaRaw || "").trim();
  if (!raw) return { number: "", aqueduct: "", label: "", hint: "" };
  // Match "5 ACQUA MARCIA" o "3 PESCHIERA-CAPORE" o solo "1" o solo nome.
  const m = raw.match(/^\s*(\d+)\s*[-·.\s]?\s*(.*)$/);
  let num = "", aq = raw;
  if (m && m[1]) { num = m[1]; aq = (m[2] || "").trim(); }
  const aqUp = aq.toUpperCase();
  const hint = AQUEDUCT_INFO[aqUp] || "";
  const aqPretty = aq ? aq.toLowerCase().replace(/(^|\s|-)\p{L}/gu, c => c.toUpperCase()) : "";
  const label = num
    ? (aqPretty ? `Zona ${num} · ${aqPretty}` : `Zona ${num}`)
    : aqPretty;
  return { number: num, aqueduct: aqPretty, label, hint };
}
function tooltipHtml(comune, zonaRaw) {
  const pz = prettyZoneInfo(zonaRaw);
  const com = escapeHtml(comune || "—").replace(/\bE\b/g, "e").toLowerCase()
    .replace(/(^|\s)\p{L}/gu, c => c.toUpperCase());
  const supply = pz.aqueduct
    ? `<div class="tt-supply">💧 Fornitore: acquedotto <b>${escapeHtml(pz.aqueduct)}</b></div>`
    : "";
  const zone = pz.number ? `<div class="tt-zone">Zona ${escapeHtml(pz.number)}</div>` : "";
  return `<div class="map-tt">
    <div class="tt-comune">${escapeHtml(com)}</div>
    ${zone}${supply}
    <div class="tt-hint">Clicca per i dettagli</div>
  </div>`;
}

// ---------- TABS ----------
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    $(`tab-${t.dataset.tab}`).classList.add("active");
    // lazy-load tab contents
    if (t.dataset.tab === "dashboard" && !state.dashboardLoaded) loadDashboard();
    if (t.dataset.tab === "meteo" && !state.meteoLoaded) loadMeteo();
    if (t.dataset.tab === "info" && !state.infoLoaded) loadInfo();
    // su mobile, assicura che il drawer sia aperto quando l'utente cambia tab
    document.body.classList.add("sidebar-open");
  });
});

// ---------- MOBILE DRAWER ----------
function setupMobileChrome() {
  const burger = $("burger");
  const overlay = $("sidebar-overlay");
  const closeBtn = $("sidebar-close");
  const open  = () => document.body.classList.add("sidebar-open");
  const close = () => document.body.classList.remove("sidebar-open");
  burger?.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open");
  });
  overlay?.addEventListener("click", close);
  closeBtn?.addEventListener("click", close);
  // chiudi il drawer con Esc
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
  // Sezione layer collassabile su mobile
  const layerBtn = $("layer-toggle-btn");
  layerBtn?.addEventListener("click", () => {
    document.body.classList.toggle("layers-open");
  });
}
setupMobileChrome();

// ---------- ZONE GEOJSON ----------
function statusStyle(feature) {
  const p = feature.properties || {};
  return {
    color: p.stroke || "#0369a1",
    weight: 0.8,
    fillColor: p.fill || "#94a3b8",
    fillOpacity: 0.45,
  };
}

// ramp colors for chloropleth
const RAMP = ["#e0f2fe","#bae6fd","#7dd3fc","#38bdf8","#0ea5e9","#0284c7","#0369a1","#1e40af","#312e81"];
function rampColor(v, min, max) {
  if (v == null || min == null || max == null || max === min) return "#cbd5e1";
  const t = Math.max(0, Math.min(1, (v - min) / (max - min)));
  const idx = Math.min(RAMP.length - 1, Math.floor(t * RAMP.length));
  return RAMP[idx];
}

function parameterStyle(feature) {
  const name = (feature.properties || {}).name;
  const pd = state.paramData;
  if (!pd) return statusStyle(feature);
  const item = pd.byName[name];
  if (!item) return { color: "#94a3b8", weight: 0.6, fillColor: "#e2e8f0", fillOpacity: 0.35 };
  const exceed = item.limite != null && item.valore > item.limite;
  return {
    color: exceed ? "#7c1d1d" : "#0c4a6e",
    weight: exceed ? 1.4 : 0.8,
    fillColor: rampColor(item.valore, pd.min, pd.max),
    fillOpacity: 0.7,
  };
}

function currentStyle(feature) {
  return state.parameter ? parameterStyle(feature) : statusStyle(feature);
}

function onEach(feature, layer) {
  const p = feature.properties || {};
  layer.bindTooltip(tooltipHtml(p.comune, p.zona_label || p.zona), {
    sticky: true, direction: "top", offset: [0, -6], className: "map-tooltip",
  });
  layer.on({
    mouseover: (e) => { if (e.target !== state.selectedLayer) e.target.setStyle({ weight: 1.8, fillOpacity: 0.7 }); },
    mouseout:  (e) => { if (e.target !== state.selectedLayer) state.geoLayer.resetStyle(e.target); },
    click: () => selectZone(p.name, layer),
  });
}

async function loadGeoJSON() {
  const r = await fetch(API("/api/geojson"));
  state.geoData = await r.json();
  state.geoLayer = L.geoJSON(state.geoData, { style: currentStyle, onEachFeature: onEach }).addTo(map);
  map.fitBounds(state.geoLayer.getBounds(), { padding: [10, 10] });
  let ok = 0, warn = 0, unk = 0;
  for (const f of state.geoData.features) {
    const s = (f.properties || {}).status;
    if (s === "OK") ok++; else if (s === "ATTENZIONE") warn++; else unk++;
  }
  $("stats").innerHTML = `<span>📍 ${state.geoData.features.length} zone</span>
    <span style="color:#16a34a">✓ ${ok} conformi</span>
    <span style="color:#dc2626">⚠ ${warn} attenzione</span>
    <span style="color:#64748b">? ${unk} N/D</span>`;
}

function refreshZoneStyle() {
  if (state.geoLayer) state.geoLayer.setStyle(currentStyle);
  if (state.selectedLayer) state.selectedLayer.setStyle(SELECTED_STYLE);
}

// ---------- ZONE DETAIL ----------
async function selectZone(name, layer) {
  switchTo("zone");
  document.body.classList.add("sidebar-open"); // mobile: apri il drawer
  if (state.selectedLayer) state.geoLayer.resetStyle(state.selectedLayer);
  state.selectedLayer = layer;
  layer.setStyle(SELECTED_STYLE);
  map.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: 13 });
  $("zone-panel").innerHTML = `<p class="loading">Caricamento dati zona…</p>`;
  try {
    const r = await fetch(API(`/api/zone/${encodeURIComponent(name)}`));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    renderZone(await r.json(), name);
  } catch (e) {
    $("zone-panel").innerHTML = `<p class="error">Errore: ${escapeHtml(e.message)}</p>`;
  }
}

function switchTo(tabId) {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
  document.querySelector(`.tab[data-tab="${tabId}"]`)?.classList.add("active");
  $(`tab-${tabId}`)?.classList.add("active");
}

function renderZone(d, name) {
  const s = d.summary || {};
  const badgeClass = s.status === "OK" ? "ok" : s.status === "ATTENZIONE" ? "warn" : "unk";
  const exceedSet = new Set((s.exceedances || []).map(x => x.parametro));
  const paramsRows = (d.parameters || []).map(p => {
    const cls = exceedSet.has(p.parametro) ? "exceed" : "";
    return `<tr class="${cls}">
      <td>${escapeHtml(p.parametro)}</td>
      <td>${escapeHtml(p.unita)}</td>
      <td class="num">${escapeHtml(p.limite || "—")}</td>
      <td class="num">${escapeHtml(p.valore || "—")}</td>
    </tr>`;
  }).join("");
  const sections = Object.entries(d.sections || {}).map(([k, v]) =>
    `<div class="section-block"><h4>${escapeHtml(k)}</h4><p>${escapeHtml(v)}</p></div>`
  ).join("");
  const pz = prettyZoneInfo(d.zona);
  const comunePretty = String(d.comune || "—").toLowerCase()
    .replace(/(^|\s)\p{L}/gu, c => c.toUpperCase());
  const supplierBlock = pz.aqueduct ? `
    <div class="supplier-card">
      <div class="supplier-head">
        <span class="supplier-ico">💧</span>
        <div>
          <div class="supplier-label">Acqua fornita dall'acquedotto</div>
          <div class="supplier-name">${escapeHtml(pz.aqueduct)}</div>
        </div>
      </div>
      ${pz.hint ? `<div class="supplier-hint"><b>ℹ️ Cosa significa?</b> ${escapeHtml(pz.hint)}</div>` : ""}
    </div>` : "";
  $("zone-panel").innerHTML = `
    <div class="zone-title-row">
      <div>
        <div class="zone-title">${escapeHtml(comunePretty)}</div>
        <div class="zone-sub">${pz.number ? `Zona ${escapeHtml(pz.number)}` : escapeHtml(d.zona || "")} · aggiornato a ${escapeHtml(d.periodo || "n/d")}</div>
      </div>
      <span class="badge ${badgeClass}">${escapeHtml(s.status || "N/D")}</span>
    </div>
    ${supplierBlock}
    <div class="zone-stats">
      <div class="zs-item"><strong>${(d.parameters || []).length}</strong><span>Parametri</span></div>
      <div class="zs-item ${(s.exceedances || []).length ? "bad" : "good"}"><strong>${(s.exceedances || []).length}</strong><span>Anomalie</span></div>
    </div>
    <div class="zone-actions">
      <button class="btn" id="zone-add-compare" data-name="${escapeHtml(name)}">+ Confronta</button>
      <a class="btn ghost" href="${API(escapeHtml(d.pdf_url || ''))}" target="_blank" rel="noopener">📄 PDF originale</a>
    </div>
    <table class="params">
      <thead><tr><th>Parametro</th><th>Unità</th><th>Limite</th><th>Valore</th></tr></thead>
      <tbody>${paramsRows}</tbody>
    </table>
    ${sections}
  `;
  $("zone-add-compare").addEventListener("click", () => addCompare(name));
}

// ---------- NEWS ----------
function makeNewsIcon(item) {
  const color = item.color || "#475569";
  const icon = item.icon || "💧";
  const sev = item.severity || "info";
  const ring = sev === "alert" ? "ring-alert" : sev === "warning" ? "ring-warn" : "ring-info";
  const future = item.is_future ? " is-future" : "";
  const approx = item.geo_quality && item.geo_quality !== "exact" ? " is-approx" : "";
  return L.divIcon({
    className: "news-pin",
    html: `<div class="pin ${ring}${future}${approx}" style="--c:${color}"><span>${icon}</span></div>`,
    iconSize: [36, 36], iconAnchor: [18, 32], popupAnchor: [0, -28],
  });
}
function newsPopupHtml(it) {
  const date = it.date ? `<span class="pill">📅 ${escapeHtml(it.date)}</span>` : "";
  const cat = `<span class="pill cat" style="background:${it.color}22;color:${it.color}">${escapeHtml(it.icon || "")} ${escapeHtml(it.category || "altro")}</span>`;
  const sev = it.severity ? `<span class="pill sev-${escapeHtml(it.severity)}">${escapeHtml(it.severity)}</span>` : "";
  const loc = it.location ? `<span class="pill">📍 ${escapeHtml(it.location)}</span>` : "";
  const future = it.is_future ? `<span class="pill pill-future">🔮 in programma</span>` : "";
  const approx = it.geo_quality === "fallback"
      ? `<span class="pill pill-approx" title="posizione approssimativa">~ pos. stimata</span>`
      : (it.geo_quality === "approx" ? `<span class="pill pill-approx">~ approx</span>` : "");
  const link = it.url
    ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener" class="news-link">Leggi su ${escapeHtml(it.source || "fonte")} →</a>`
    : `<span class="hint">Fonte non disponibile</span>`;
  return `<div class="news-popup"><div class="title">${escapeHtml(it.title || "—")}</div>
    <div class="pills">${date}${loc}${cat}${sev}${future}${approx}</div>
    <div class="summary">${escapeHtml(it.summary || "")}</div>${link}</div>`;
}

function refreshNewsMarkers() {
  if (state.newsCluster) {
    state.newsCluster.clearLayers();
  } else {
    state.newsCluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      iconCreateFunction: (cluster) => {
        let worst = 0;
        cluster.getAllChildMarkers().forEach(m => {
          const r = SEVERITY_RANK[m.options._sev] || 0;
          if (r > worst) worst = r;
        });
        const cls = worst >= 3 ? "alert" : worst === 2 ? "warn" : "info";
        return L.divIcon({
          html: `<div class="news-cluster ${cls}"><span>${cluster.getChildCount()}</span></div>`,
          className: "", iconSize: [40, 40],
        });
      },
    });
    if ($("toggle-news").checked) state.newsCluster.addTo(map);
  }
  state.newsItems.forEach(it => {
    if (!(typeof it.lat === "number" && typeof it.lng === "number")) return;
    if (state.activeCategory !== "tutte" && it.category !== state.activeCategory) return;
    const marker = L.marker([it.lat, it.lng], { icon: makeNewsIcon(it), _sev: it.severity || "info" });
    marker.bindPopup(newsPopupHtml(it), { maxWidth: 340 });
    marker.on("click", () => {
      switchTo("news");
      document.querySelectorAll(".news-card").forEach(c => c.classList.remove("active"));
      const card = $(`news-${it._idx}`);
      if (card) { card.classList.add("active"); card.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
    });
    it._marker = marker;
    state.newsCluster.addLayer(marker);
  });
}

function renderNewsSidebar() {
  const counts = { tutte: state.newsItems.length };
  state.newsItems.forEach(it => { counts[it.category] = (counts[it.category] || 0) + 1; });
  const romaCount = state.newsItems.filter(it => it.is_rome).length;
  const cats = ["tutte", "roma", ...Object.keys(state.newsCategories)];
  $("news-filters").innerHTML = cats.map(c => {
    let meta, n;
    if (c === "tutte")      { meta = { icon: "🌐", color: "#0369a1" }; n = counts.tutte; }
    else if (c === "roma")  { meta = { icon: "🏛️", color: "#b91c1c" }; n = romaCount; }
    else                    { meta = state.newsCategories[c]; n = counts[c] || 0; }
    return `<button class="chip ${c === state.activeCategory ? "active" : ""}" data-cat="${escapeHtml(c)}" style="--c:${meta.color}"><span>${meta.icon}</span> ${escapeHtml(c)} <em>${n}</em></button>`;
  }).join("");
  $("news-filters").querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeCategory = btn.dataset.cat;
      renderNewsSidebar();
      refreshNewsMarkers();
    });
  });
  const filtered = state.newsItems.filter(it => {
    if (state.activeCategory === "tutte") return true;
    if (state.activeCategory === "roma")  return it.is_rome;
    return it.category === state.activeCategory;
  });
  if (filtered.length === 0) {
    $("news-list").innerHTML = `<p class="hint">Nessuna notizia in questa categoria.</p>`;
    return;
  }
  $("news-list").innerHTML = filtered.map(it => {
    const sev = it.severity || "info";
    const link = it.url ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener">Leggi →</a>` : `<span class="hint">no link</span>`;
    const loc = it.location ? `📍 ${escapeHtml(it.location)} · ` : "";
    const fut = it.is_future ? `<span class="sev sev-future">🔮 futuro</span>` : "";
    const romaTag = it.is_rome ? `<span class="sev sev-roma" title="Roma o Città Metropolitana">🏛️ Roma</span>` : "";
    const apx = (it.geo_quality && it.geo_quality !== "exact")
      ? `<span class="sev sev-approx" title="posizione approssimativa">~</span>` : "";
    return `<div class="news-card ${it.is_future ? "future" : ""} ${it.is_rome ? "is-rome" : ""}" id="news-${it._idx}" data-idx="${it._idx}" style="--c:${it.color}">
      <div class="news-card-head">
        <span class="cat-dot" style="background:${it.color}">${it.icon || "💧"}</span>
        <div class="title">${escapeHtml(it.title || "—")}</div>
        ${romaTag}${fut}${apx}<span class="sev sev-${escapeHtml(sev)}">${escapeHtml(sev)}</span>
      </div>
      <div class="meta">${loc}${escapeHtml(it.source || "")} · ${escapeHtml(it.date || "")}</div>
      <div class="summary">${escapeHtml(it.summary || "")}</div>
      <div class="card-foot">${link}</div></div>`;
  }).join("");
  $("news-list").querySelectorAll(".news-card").forEach(card => {
    card.addEventListener("click", (ev) => {
      if (ev.target.tagName === "A") return;
      const it = state.newsItems[parseInt(card.dataset.idx, 10)];
      if (it && it._marker && $("toggle-news").checked) {
        map.setView([it.lat, it.lng], 11, { animate: true });
        it._marker.openPopup();
      }
    });
  });
}

async function loadNews(fresh = false) {
  $("news-list").innerHTML = `<p class="loading">Caricamento news multi-tematica…</p>`;
  $("news-meta").textContent = "";
  try {
    const r = await fetch(API(`/api/news${fresh ? "?fresh=1" : ""}`));
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    state.newsCategories = data.categories || {};
    state.newsItems = (data.items || []).map((it, idx) => ({ ...it, _idx: idx }));
    $("news-meta").innerHTML = `<span>${state.newsItems.length} notizie</span>
      <span>${data.cached ? "cache" : "live"}</span><span>${escapeHtml(data.model || "")}</span>
      <span>${data.generated_at ? new Date(data.generated_at * 1000).toLocaleTimeString("it-IT") : ""}</span>`;
    renderNewsSidebar();
    refreshNewsMarkers();
  } catch (e) {
    $("news-list").innerHTML = `<p class="error">Errore news: ${escapeHtml(e.message)}</p>`;
  }
}

// ---------- NASONI ----------
const NASONE_ICON = L.divIcon({
  className: "nasone-pin",
  html: `<div class="nasone">💧</div>`,
  iconSize: [22, 22], iconAnchor: [11, 11],
});
async function loadNasoni() {
  if (state.nasoniLayer) return state.nasoniLayer;
  $("toggle-nasoni").disabled = true;
  try {
    const r = await fetch(API("/api/nasoni"));
    const d = await r.json();
    const cluster = L.markerClusterGroup({
      maxClusterRadius: 50,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="nasone-cluster"><span>${c.getChildCount()}</span></div>`,
        className: "", iconSize: [36, 36],
      }),
    });
    (d.items || []).forEach(n => {
      const m = L.marker([n.lat, n.lng], { icon: NASONE_ICON });
      m.bindPopup(`<div class="news-popup">
        <div class="title">💧 Fontanella pubblica</div>
        <div class="summary">${escapeHtml(n.name || "Nasone / drinking water")}<br/>
        Operatore: ${escapeHtml(n.operator || "—")}<br/>
        ID OSM: <a href="https://www.openstreetmap.org/node/${n.id}" target="_blank">${n.id}</a></div>
      </div>`);
      cluster.addLayer(m);
    });
    state.nasoniLayer = cluster;
    state.nasoniCount = d.count;
    return cluster;
  } finally {
    $("toggle-nasoni").disabled = false;
  }
}

// ---------- ACQUEDOTTI ----------
async function loadAqueducts() {
  if (state.aqueductsLayer) return state.aqueductsLayer;
  const r = await fetch(API("/api/aqueducts"));
  const d = await r.json();
  const grp = L.layerGroup();
  (d.features || []).forEach(f => {
    const props = f.properties || {};
    const coords = f.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
    const line = L.polyline(coords, {
      color: props.color || "#0369a1",
      weight: props.still_active ? 4 : 3,
      opacity: 0.85,
      dashArray: props.still_active ? null : "8,6",
    });
    line.bindPopup(`<div class="news-popup">
      <div class="title">${escapeHtml(props.name)}</div>
      <div class="pills"><span class="pill">📅 ${escapeHtml(props.year)}</span>
        <span class="pill">${escapeHtml(props.length_km + " km")}</span>
        <span class="pill ${props.still_active ? "sev-info" : "sev-warning"}">${props.still_active ? "in uso" : "antico"}</span></div>
      <div class="summary"><b>Costruito da:</b> ${escapeHtml(props.builder)}<br/>
        <b>Alimenta:</b> ${escapeHtml(props.feeds)}</div></div>`);
    grp.addLayer(line);
  });
  state.aqueductsLayer = grp;
  return grp;
}

// ---------- LAYER TOGGLES ----------
$("toggle-zones").addEventListener("change", e => {
  if (!state.geoLayer) return;
  if (e.target.checked) state.geoLayer.addTo(map); else map.removeLayer(state.geoLayer);
});
$("toggle-news").addEventListener("change", e => {
  if (!state.newsCluster) return;
  if (e.target.checked) state.newsCluster.addTo(map); else map.removeLayer(state.newsCluster);
});
$("toggle-nasoni").addEventListener("change", async e => {
  const grp = await loadNasoni();
  if (e.target.checked) grp.addTo(map); else map.removeLayer(grp);
});
$("toggle-aqueducts").addEventListener("change", async e => {
  const grp = await loadAqueducts();
  if (e.target.checked) grp.addTo(map); else map.removeLayer(grp);
});

// ---------- PARAMETER COROPLETICO ----------
async function loadParameterList() {
  const r = await fetch(API("/api/parameters"));
  const d = await r.json();
  const sel = $("param-select");
  (d.items || []).forEach(p => {
    const o = document.createElement("option");
    o.value = p; o.textContent = p;
    sel.appendChild(o);
  });
}

async function setParameter(name) {
  state.parameter = name;
  if (!name) {
    state.paramData = null;
    $("param-legend").classList.add("hidden");
    refreshZoneStyle();
    return;
  }
  const r = await fetch(API(`/api/parameter/${encodeURIComponent(name)}`));
  const d = await r.json();
  if (!d.count) {
    state.paramData = null;
    $("param-legend").classList.add("hidden");
    refreshZoneStyle();
    return;
  }
  const byName = {};
  d.items.forEach(it => { byName[it.name] = it; });
  state.paramData = { ...d, byName };
  // legend
  const legend = $("param-legend");
  const step = (d.max - d.min) / RAMP.length;
  legend.innerHTML = `<div class="legend-title">${escapeHtml(name)} <small>(${d.items[0]?.unita || ""})</small></div>
    <div class="legend-bar">${RAMP.map((c, i) => {
      const v = d.min + step * i;
      return `<span style="background:${c}" title="${v.toFixed(3)}"></span>`;
    }).join("")}</div>
    <div class="legend-range"><span>${d.min.toFixed(2)}</span><span>median ${d.median.toFixed(2)}</span><span>${d.max.toFixed(2)}</span></div>
    <div class="legend-hint">${d.count} zone · max evidenziato bordo rosso = supero limite</div>`;
  legend.classList.remove("hidden");
  refreshZoneStyle();
}
$("param-select").addEventListener("change", e => setParameter(e.target.value));

// ---------- SEARCH ----------
let searchAbort = null;
function bindSearch(inputId, resultsId, onPick) {
  const input = $(inputId);
  const box = $(resultsId);
  let tmo = null;
  input.addEventListener("input", () => {
    clearTimeout(tmo);
    const q = input.value.trim();
    if (q.length < 2) { box.innerHTML = ""; box.classList.remove("visible"); return; }
    tmo = setTimeout(async () => {
      if (searchAbort) searchAbort.abort();
      searchAbort = new AbortController();
      try {
        const r = await fetch(API(`/api/search?q=${encodeURIComponent(q)}&limit=12`), { signal: searchAbort.signal });
        const d = await r.json();
        if (!d.items.length) { box.innerHTML = `<div class="sr-empty">Nessun risultato</div>`; box.classList.add("visible"); return; }
        box.innerHTML = d.items.map(it => `
          <div class="sr-item" data-name="${escapeHtml(it.name)}">
            <div class="sr-title">${escapeHtml(it.comune || "")} · ${escapeHtml(it.zona || "")}</div>
            <div class="sr-meta">
              <span class="badge ${it.status === 'OK' ? 'ok' : it.status === 'ATTENZIONE' ? 'warn' : 'unk'}">${escapeHtml(it.status || "?")}</span>
              ${it.exceedances ? `<span>· ${it.exceedances} anomalie</span>` : ""}
            </div>
          </div>`).join("");
        box.classList.add("visible");
        box.querySelectorAll(".sr-item").forEach(el => {
          el.addEventListener("click", () => {
            onPick(el.dataset.name);
            input.value = "";
            box.classList.remove("visible");
          });
        });
      } catch (e) {
        if (e.name !== "AbortError") box.innerHTML = `<div class="sr-empty">Errore: ${escapeHtml(e.message)}</div>`;
      }
    }, 180);
  });
  input.addEventListener("blur", () => setTimeout(() => box.classList.remove("visible"), 200));
  input.addEventListener("focus", () => { if (box.innerHTML) box.classList.add("visible"); });
}
function pickZoneByName(name) {
  const layer = findLayerByName(name);
  if (layer) selectZone(name, layer);
}
function findLayerByName(name) {
  if (!state.geoLayer) return null;
  let found = null;
  state.geoLayer.eachLayer(l => {
    if ((l.feature.properties || {}).name === name) found = l;
  });
  return found;
}
bindSearch("search-input", "search-results", pickZoneByName);

// ---------- DASHBOARD ----------
async function loadDashboard() {
  const r = await fetch(API("/api/dashboard"));
  const d = await r.json();
  state.dashboardLoaded = true;
  const sb = d.status_breakdown || {};
  $("dashboard-summary").innerHTML = `
    <div class="kpi"><strong>${d.total_zones}</strong><span>zone</span></div>
    <div class="kpi ok"><strong>${sb.OK || 0}</strong><span>conformi</span></div>
    <div class="kpi warn"><strong>${sb.ATTENZIONE || 0}</strong><span>attenzione</span></div>
    <div class="kpi unk"><strong>${sb.UNKNOWN || 0}</strong><span>N/D</span></div>
    <div class="kpi"><strong>${d.total_parameters_distinct}</strong><span>parametri</span></div>
  `;
  // Chart: status pie
  new Chart($("chart-status"), {
    type: "doughnut",
    data: {
      labels: ["Conformi", "Attenzione", "N/D"],
      datasets: [{
        data: [sb.OK || 0, sb.ATTENZIONE || 0, sb.UNKNOWN || 0],
        backgroundColor: ["#16a34a", "#dc2626", "#94a3b8"],
        borderWidth: 0,
      }],
    },
    options: { plugins: { legend: { position: "bottom", labels: { font: { size: 11 } } } } },
  });
  // Chart: exceedances by parameter
  const exP = d.top_exceedances_by_parameter || [];
  new Chart($("chart-exc-param"), {
    type: "bar",
    data: {
      labels: exP.map(([p]) => p),
      datasets: [{ label: "zone con supero", data: exP.map(([, c]) => c), backgroundColor: "#dc2626" }],
    },
    options: { indexAxis: "y", scales: { x: { beginAtZero: true } }, plugins: { legend: { display: false } } },
  });
  // Chart: exceedances by comune
  const exC = d.top_exceedances_by_comune || [];
  new Chart($("chart-exc-comune"), {
    type: "bar",
    data: {
      labels: exC.map(([c]) => c),
      datasets: [{ label: "anomalie", data: exC.map(([, n]) => n), backgroundColor: "#ea580c" }],
    },
    options: { indexAxis: "y", scales: { x: { beginAtZero: true } }, plugins: { legend: { display: false } } },
  });
  // Parameter stats table
  const rows = (d.parameter_stats || []).slice(0, 20).map(p => `
    <tr><td>${escapeHtml(p.parametro)}</td>
        <td class="num">${p.count}</td>
        <td class="num">${(+p.min).toFixed(3)}</td>
        <td class="num">${(+p.median).toFixed(3)}</td>
        <td class="num">${(+p.mean).toFixed(3)}</td>
        <td class="num">${(+p.max).toFixed(3)}</td></tr>`).join("");
  $("dashboard-table-wrap").innerHTML = `
    <table class="params"><thead><tr><th>Parametro</th><th>n</th><th>min</th><th>median</th><th>mean</th><th>max</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
}

// ---------- COMPARE ----------
bindSearch("compare-input", "compare-suggest", (name) => addCompare(name));

async function addCompare(name) {
  if (state.compareList.includes(name)) return;
  if (state.compareList.length >= 4) {
    alert("Massimo 4 zone nel confronto");
    return;
  }
  state.compareList.push(name);
  switchTo("compare");
  await renderCompare();
}
function removeCompare(name) {
  state.compareList = state.compareList.filter(n => n !== name);
  renderCompare();
}

async function renderCompare() {
  $("compare-chips").innerHTML = state.compareList.map(n =>
    `<span class="chip active" style="--c:#0369a1">${escapeHtml(n)} <button data-rm="${escapeHtml(n)}">×</button></span>`).join("");
  $("compare-chips").querySelectorAll("button[data-rm]").forEach(b => {
    b.addEventListener("click", () => removeCompare(b.dataset.rm));
  });
  if (state.compareList.length === 0) {
    $("compare-table-wrap").innerHTML = "";
    return;
  }
  const r = await fetch(API(`/api/compare?names=${state.compareList.map(encodeURIComponent).join(",")}`));
  const d = await r.json();
  const head = `<tr><th>Parametro</th>${d.zones.map(z =>
    `<th>${escapeHtml(z.comune || "")}<br/><small>${escapeHtml(z.zona || "")}</small></th>`).join("")}</tr>`;
  const statusRow = `<tr><td><b>Stato</b></td>${d.zones.map(z =>
    `<td><span class="badge ${z.status === 'OK' ? 'ok' : z.status === 'ATTENZIONE' ? 'warn' : 'unk'}">${escapeHtml(z.status || "?")}</span></td>`).join("")}</tr>`;
  const rows = d.parameters.map(p => {
    return `<tr><td>${escapeHtml(p)}</td>${d.zones.map(z => {
      const item = z.parameters[p];
      if (!item) return `<td class="num">—</td>`;
      const exceed = z.exceedances.some(e => e.parametro === p);
      return `<td class="num ${exceed ? 'exc' : ''}">${escapeHtml(item.valore || "—")}<br/><small>lim ${escapeHtml(item.limite || "—")}</small></td>`;
    }).join("")}</tr>`;
  }).join("");
  $("compare-table-wrap").innerHTML = `<table class="params compare-table"><thead>${head}</thead><tbody>${statusRow}${rows}</tbody></table>`;
}

// ---------- AI CHAT ----------
function chatAppend(role, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.innerHTML = `<div class="bubble">${role === "user" ? "" : "🤖 "}${escapeHtml(text)}</div>`;
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return div;
}

async function askAI(question) {
  chatAppend("user", question);
  const thinking = chatAppend("assistant", "Sto pensando…");
  try {
    const r = await fetch(API("/api/ask"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const d = await r.json();
    thinking.querySelector(".bubble").innerHTML = d.answer
      ? `🤖 ${escapeHtml(d.answer).replace(/\n/g, "<br/>")}`
      : `<span class="error">Errore: ${escapeHtml(d.error || "?")}</span>`;
  } catch (e) {
    thinking.querySelector(".bubble").innerHTML = `<span class="error">Errore: ${escapeHtml(e.message)}</span>`;
  }
}
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("chat-input").value.trim();
  if (!v) return;
  $("chat-input").value = "";
  askAI(v);
});
document.querySelectorAll(".chat-suggestions .chip").forEach(b => {
  b.addEventListener("click", () => askAI(b.dataset.q));
});

// ---------- INFO TAB ----------
async function loadInfo() {
  state.infoLoaded = true;
  const r = await fetch(API("/api/aqueducts"));
  const d = await r.json();
  $("aq-list").innerHTML = (d.features || []).map(f => {
    const p = f.properties;
    return `<li>
      <span class="dot" style="background:${p.color}"></span>
      <strong>${escapeHtml(p.name)}</strong> · ${escapeHtml(p.year)} ·
      ${p.length_km} km · ${p.still_active ? "<em>in uso</em>" : "antico"}<br/>
      <small>${escapeHtml(p.feeds)}</small>
    </li>`;
  }).join("");
  // numeri chiave
  const dash = await (await fetch(API("/api/dashboard"))).json();
  $("info-numbers").innerHTML = `
    <div class="kpi"><strong>${dash.total_zones}</strong><span>zone monitorate</span></div>
    <div class="kpi"><strong>${dash.total_parameters_distinct}</strong><span>parametri distinti</span></div>
    <div class="kpi"><strong>${(dash.top_exceedances_by_parameter || []).reduce((s, [, c]) => s + c, 0)}</strong><span>superi totali</span></div>
  `;
}

// ---------- REFRESH NEWS BTN ----------
$("refresh-news").addEventListener("click", () => loadNews(true));

// ---------- METEO & BRACCIANO (DATI REALI ESTERNI) ----------
const WCODE = {
  0: ["☀️","sereno"], 1: ["🌤️","poco nuv."], 2: ["⛅","variabile"], 3: ["☁️","coperto"],
  45: ["🌫️","nebbia"], 48: ["🌫️","nebbia gelo"],
  51: ["🌦️","pioviggine"], 53: ["🌦️","pioviggine"], 55: ["🌦️","pioviggine"],
  61: ["🌧️","pioggia debole"], 63: ["🌧️","pioggia"], 65: ["🌧️","pioggia forte"],
  71: ["🌨️","neve"], 73: ["🌨️","neve"], 75: ["❄️","neve forte"],
  80: ["🌦️","rovesci"], 81: ["🌧️","rovesci"], 82: ["⛈️","rovesci forti"],
  95: ["⛈️","temporale"], 96: ["⛈️","temp. grandine"], 99: ["⛈️","temp. grandine"],
};

async function loadMeteo() {
  state.meteoLoaded = true;
  $("meteo-status").innerText = "Caricamento dati Open-Meteo…";
  try {
    const [m, b] = await Promise.all([
      fetch(API("/api/meteo")).then(r => r.json()),
      fetch(API("/api/bracciano")).then(r => r.json()),
    ]);
    if (m.error) throw new Error(m.error);
    renderMeteo(m);
    renderBracciano(b);
    $("meteo-status").innerText = `Fonte: ${m.source} · ultimo aggiornamento ${new Date(m.updated).toLocaleString("it-IT")}`;
  } catch (e) {
    $("meteo-status").innerHTML = `<span class="error">Errore: ${escapeHtml(e.message)}</span>`;
  }
}

function renderMeteo(m) {
  const d = m.drought || {};
  const banner = $("drought-banner");
  banner.style.background = (d.color || "#94a3b8") + "22";
  banner.style.borderLeft = `4px solid ${d.color || "#94a3b8"}`;
  banner.style.color = d.color || "#94a3b8";
  banner.innerHTML = `
    <strong>${(d.label || "n/d").toUpperCase()}</strong> ·
    indice 90gg vs media = ${d.ratio_90d_vs_normal ?? "n/d"} ·
    ${m.rain_mm.last_90d} mm caduti vs ${m.rain_mm.expected_90d_from_365d_mean} mm attesi
  `;
  banner.classList.remove("hidden");

  $("meteo-kpis").innerHTML = `
    <div class="kpi"><strong>${m.rain_mm.last_7d}</strong><span>mm pioggia 7gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_30d}</strong><span>mm pioggia 30gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_90d}</strong><span>mm pioggia 90gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_365d}</strong><span>mm pioggia 365gg</span></div>
    <div class="kpi"><strong>${m.temp_c.mean_last_30d ?? "—"}°C</strong><span>temp media 30gg</span></div>
  `;

  // Chart pioggia 90gg
  const ctxH = $("chart-rain-history").getContext("2d");
  if (state.chartHist) state.chartHist.destroy();
  state.chartHist = new Chart(ctxH, {
    type: "bar",
    data: {
      labels: m.history_90d.map(x => x.date.slice(5)),
      datasets: [{
        label: "Pioggia (mm)",
        data: m.history_90d.map(x => x.rain),
        backgroundColor: "#0284c7",
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { beginAtZero: true, title: { display: true, text: "mm/giorno" } },
      },
    },
  });

  // Chart forecast 7gg combinato
  const ctxF = $("chart-rain-forecast").getContext("2d");
  if (state.chartFcst) state.chartFcst.destroy();
  state.chartFcst = new Chart(ctxF, {
    data: {
      labels: m.forecast_7d.map(x => new Date(x.date).toLocaleDateString("it-IT", { weekday: "short", day: "numeric" })),
      datasets: [
        { type: "bar",  label: "Pioggia mm",    data: m.forecast_7d.map(x => x.rain), backgroundColor: "#0284c7", yAxisID: "y" },
        { type: "line", label: "Tmax °C", data: m.forecast_7d.map(x => x.tmax), borderColor: "#dc2626", backgroundColor: "transparent", yAxisID: "y1", tension: 0.3 },
        { type: "line", label: "Tmin °C", data: m.forecast_7d.map(x => x.tmin), borderColor: "#1d4ed8", backgroundColor: "transparent", yAxisID: "y1", tension: 0.3 },
      ],
    },
    options: {
      scales: {
        y:  { position: "left",  beginAtZero: true, title: { display: true, text: "mm" } },
        y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "°C" } },
      },
    },
  });

  $("forecast-list").innerHTML = m.forecast_7d.map(d => {
    const [emoji, txt] = WCODE[d.weather_code] || ["•", "—"];
    return `<div class="fc-day">
      <div class="fc-date">${new Date(d.date).toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" })}</div>
      <div class="fc-icon">${emoji}</div>
      <div class="fc-temp">${Math.round(d.tmin)}° / <strong>${Math.round(d.tmax)}°</strong></div>
      <div class="fc-rain">💧 ${d.rain} mm</div>
      <div class="fc-txt">${txt}</div>
    </div>`;
  }).join("");
}

function renderBracciano(b) {
  $("bracciano-card").innerHTML = `
    <div class="b-grid">
      <div class="kpi"><strong>${b.surface_km2}</strong><span>km² superficie</span></div>
      <div class="kpi"><strong>${b.depth_max_m}</strong><span>m profondità max</span></div>
      <div class="kpi"><strong>${b.depth_mean_m}</strong><span>m profondità media</span></div>
      <div class="kpi"><strong>${b.volume_km3}</strong><span>km³ volume</span></div>
      <div class="kpi"><strong>${b.elevation_m}</strong><span>m s.l.m.</span></div>
      <div class="kpi" style="background:${(b.drought_color||'#94a3b8')}22;color:${b.drought_color||'#0f172a'}">
        <strong>${b.drought_label||"n/d"}</strong><span>stato area</span>
      </div>
    </div>
    <p><strong>Tipo:</strong> ${escapeHtml(b.type)}</p>
    <p><strong>Comuni rivieraschi:</strong> ${(b.shore_comuni||[]).join(", ")}</p>
    <p><strong>Emissario:</strong> ${escapeHtml(b.main_outflow)}</p>
    <p><strong>Uso idrico:</strong> ${escapeHtml(b.use)}</p>
    <p class="hint">${escapeHtml(b.notes)}</p>
    <p class="hint">Fonti: ${escapeHtml(b.source)} · <a href="${b.wikipedia}" target="_blank">Wikipedia</a></p>
  `;

  // marker mappa
  if (!state.bracciantoLayer) {
    const icon = L.divIcon({
      className: "bracciano-pin",
      html: `<div class="b-marker" style="background:${b.drought_color||'#0284c7'}">🏞️</div>`,
      iconSize: [40, 40], iconAnchor: [20, 20], popupAnchor: [0, -16],
    });
    state.bracciantoLayer = L.marker([b.lat, b.lon], { icon }).bindPopup(`
      <div class="news-popup">
        <div class="title">${escapeHtml(b.name)}</div>
        <div class="summary">
          ${b.surface_km2} km² · ${b.depth_max_m} m max · ${b.volume_km3} km³<br/>
          <em>${escapeHtml(b.use)}</em>
        </div>
        <a class="news-link" href="${b.wikipedia}" target="_blank">Wikipedia ↗</a>
      </div>
    `);
  }
}

$("toggle-bracciano").addEventListener("change", async e => {
  if (!state.bracciantoLayer) {
    const b = await fetch(API("/api/bracciano")).then(r => r.json());
    renderBracciano(b);
  }
  if (e.target.checked) {
    state.bracciantoLayer.addTo(map);
    map.flyTo([42.117, 12.233], 11, { duration: 1.2 });
  } else if (map.hasLayer(state.bracciantoLayer)) {
    map.removeLayer(state.bracciantoLayer);
  }
});

// ---------- BOOT ----------
(async () => {
  await loadGeoJSON();
  await loadParameterList();
  loadNews().catch(e => console.error(e));
  setInterval(() => loadNews(true), 15 * 60 * 1000);
})();
