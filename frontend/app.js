/* ============================================================
 * AcquaMap — frontend v2.0 (mobile-first)
 *   Funzioni dati preservate dalla v1; shell completamente nuovo:
 *   bottom sheet drag, bottom nav, FAB, modal sheets, dark mode.
 * ============================================================ */

// ---------- API base ----------
// In Capacitor (Android/iOS) il WebView serve l'app da https://localhost o capacitor://...
// e quindi `localhost` NON significa "dev locale": dobbiamo usare l'API remota (meta tag).
const _cap = window.Capacitor;
const IS_NATIVE = !!(_cap && (
  (typeof _cap.isNativePlatform === "function" && _cap.isNativePlatform()) ||
  (typeof _cap.getPlatform === "function" && _cap.getPlatform() !== "web") ||
  _cap.platform && _cap.platform !== "web"
));
const _isCapacitorScheme = /^capacitor:/i.test(location.protocol);
const _isLocalHost = !IS_NATIVE && !_isCapacitorScheme && (
  /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname) ||
  location.protocol === "file:"
);
const _metaApiBase = _isLocalHost ? "" : (document.querySelector('meta[name="api-base"]')?.content || "");
const API_BASE = (window.API_BASE || _metaApiBase || "").replace(/\/$/, "");
const API = (p) => API_BASE + p;
window.__ACQUAMAP_DEBUG__ = { IS_NATIVE, API_BASE, host: location.hostname, proto: location.protocol };

// ---------- BASEMAPS ----------
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

const map = L.map("map", { preferCanvas: true, zoomControl: false }).setView([41.85, 12.66], 9);
let baseLayer = null;
function setBasemap(key) {
  if (baseLayer) map.removeLayer(baseLayer);
  const b = BASEMAPS[key] || BASEMAPS.osm;
  baseLayer = L.tileLayer(b.url, { maxZoom: b.maxZoom, attribution: b.attr });
  baseLayer.addTo(map);
}
setBasemap("osm");

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
  parameter: "",
  paramData: null,
  compareList: [],
  meLayer: null,
};

const SELECTED_STYLE = { weight: 2.5, color: "#0c4a6e", fillOpacity: 0.7 };
const SEVERITY_RANK = { alert: 3, warning: 2, info: 1 };
const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

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
function tooltipHtml(p) {
  const icon = p.icon || "🏘️";
  const title = p.display_name || p.comune || "—";
  const area = p.area || "";
  const zone = p.zone_num ? `Zona ${escapeHtml(p.zone_num)}` : "";
  const aq = p.aqueduct
    ? `<div class="tt-supply">💧 Acquedotto <b>${escapeHtml(p.aqueduct)}</b></div>` : "";
  const badges = (p.badges || []).slice(0, 2).map(b =>
    `<span class="tt-badge">${escapeHtml(b)}</span>`).join("");
  const statusBadge = p.status === "ATTENZIONE"
    ? `<span class="tt-status warn">⚠ Attenzione</span>`
    : p.status === "OK" ? `<span class="tt-status ok">✓ Conforme</span>` : "";
  const fr = p.freshness || {};
  const frBadge = fr.label && fr.label !== "n/d"
    ? `<span class="tt-fresh fresh-${fr.level}">${escapeHtml(fr.label)}</span>` : "";
  const provBadge = p.provider_label
    ? `<span class="tt-prov" title="${escapeHtml(p.provider_ato || "")}">${escapeHtml(p.provider_label)}</span>` : "";
  return `<div class="map-tt">
    <div class="tt-comune">${icon} ${escapeHtml(title)}</div>
    ${area ? `<div class="tt-zone">${escapeHtml(area)}${zone ? ` · ${zone}` : ""}</div>` : (zone ? `<div class="tt-zone">${zone}</div>` : "")}
    ${aq}
    <div class="tt-badges">${badges}${statusBadge}${frBadge}${provBadge}</div>
    <div class="tt-hint">Tocca per i dettagli</div>
  </div>`;
}

// ---------- TOAST ----------
let _toastTm = null;
function showToast(msg, ms = 2400) {
  const t = $("toast"); if (!t) return;
  t.textContent = msg;
  t.classList.remove("hidden");
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(_toastTm);
  _toastTm = setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.classList.add("hidden"), 250);
  }, ms);
}

// ---------- BOTTOM SHEET ----------
function setSheetState(stateName) {
  const sh = $("sheet");
  if (!sh) return;
  sh.dataset.state = stateName;
  document.body.classList.remove("sheet-peek", "sheet-half", "sheet-full");
  document.body.classList.add("sheet-" + stateName);
}

function setupSheetDrag() {
  const sh = $("sheet"), handle = $("sheet-handle");
  if (!sh || !handle) return;
  let startY = 0, startTr = 0, dragging = false, vh = window.innerHeight, moved = 0;

  const stateY = () => {
    const s = sh.dataset.state;
    if (s === "peek") return vh - 112;
    if (s === "half") return vh * 0.5;
    return Math.max(0, 56 + 8); // full
  };
  const snap = (y) => {
    const peekY = vh - 112, halfY = vh * 0.5, fullY = 64;
    const d = [
      ["peek", Math.abs(y - peekY)],
      ["half", Math.abs(y - halfY)],
      ["full", Math.abs(y - fullY)],
    ].sort((a, b) => a[1] - b[1]);
    return d[0][0];
  };

  const onDown = (e) => {
    dragging = true; moved = 0;
    vh = window.innerHeight;
    startY = (e.touches ? e.touches[0].clientY : e.clientY);
    startTr = stateY();
    sh.classList.add("dragging");
    try { handle.setPointerCapture?.(e.pointerId); } catch {}
  };
  const onMove = (e) => {
    if (!dragging) return;
    const y = (e.touches ? e.touches[0].clientY : e.clientY);
    const dy = y - startY;
    moved = Math.abs(dy);
    const nextTr = Math.max(64, Math.min(vh - 60, startTr + dy));
    sh.style.transform = `translateY(${nextTr}px)`;
    e.preventDefault?.();
  };
  const onUp = (e) => {
    if (!dragging) return;
    dragging = false;
    sh.classList.remove("dragging");
    sh.style.transform = "";
    if (moved < 8) {
      // tap: cicla peek <-> half
      const cur = sh.dataset.state;
      setSheetState(cur === "peek" ? "half" : (cur === "half" ? "peek" : "half"));
      return;
    }
    const y = (e.changedTouches ? e.changedTouches[0].clientY : e.clientY);
    setSheetState(snap(y));
  };

  handle.addEventListener("pointerdown", onDown);
  window.addEventListener("pointermove", onMove, { passive: false });
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointercancel", onUp);

  $("sheet-close")?.addEventListener("click", () => setSheetState("peek"));
}

// ---------- BOTTOM NAV ----------
function setupBottomNav() {
  document.querySelectorAll(".bn-item").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".bn-item").forEach(x => x.classList.remove("active"));
      btn.classList.add("active");
      switchTo(tab);
      if ($("sheet").dataset.state === "peek") setSheetState("half");
      try { navigator.vibrate?.(8); } catch {}
    });
  });
}

function switchTo(tabId) {
  document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
  $(`tab-${tabId}`)?.classList.add("active");
  document.querySelectorAll(".bn-item").forEach(x => x.classList.toggle("active", x.dataset.tab === tabId));

  // titolo del bottom-sheet
  const titles = {
    zone: "Dettagli zona",
    dashboard: "Panoramica",
    news: "News real-time",
    compare: "Confronta zone",
    chat: "Assistente AI",
    meteo: "Meteo & Siccità",
    info: "L'acqua del Lazio",
  };
  const t = $("sheet-title"); if (t) t.textContent = titles[tabId] || "AcquaMap";

  // lazy-load
  if (tabId === "dashboard" && !state.dashboardLoaded) loadDashboard();
  if (tabId === "meteo" && !state.meteoLoaded) loadMeteo();
  if (tabId === "info" && !state.infoLoaded) loadInfo();
}

// ---------- MODAL SHEETS ----------
function openModalSheet(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("hidden");
  requestAnimationFrame(() => el.classList.add("open"));
}
function closeModalSheet(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("open");
  el.classList.add("hidden");
}
function setupModalSheet(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.querySelectorAll("[data-close]").forEach(x =>
    x.addEventListener("click", () => closeModalSheet(id)));
}

// ---------- MENU SHEET ----------
function setupMenuSheet() {
  setupModalSheet("menu-sheet");
  $("menu-btn")?.addEventListener("click", () => openModalSheet("menu-sheet"));
  document.querySelectorAll("#menu-sheet .ms-item[data-tab]").forEach(b => {
    b.addEventListener("click", () => {
      switchTo(b.dataset.tab);
      closeModalSheet("menu-sheet");
      setSheetState("half");
    });
  });
  document.querySelectorAll("#menu-sheet .ms-item[data-action='reload']").forEach(b => {
    b.addEventListener("click", () => location.reload());
  });
}

// ---------- SEARCH SHEET ----------
function setupSearchSheet() {
  setupModalSheet("search-sheet");
  $("search-btn")?.addEventListener("click", () => {
    openModalSheet("search-sheet");
    setTimeout(() => $("search-input")?.focus(), 220);
  });
  const inp = $("search-input"), clr = $("search-clear");
  inp?.addEventListener("input", () => {
    if (inp.value) clr.classList.remove("hidden"); else clr.classList.add("hidden");
  });
  clr?.addEventListener("click", () => {
    inp.value = ""; clr.classList.add("hidden");
    inp.dispatchEvent(new Event("input"));
    $("search-results").innerHTML = "";
    inp.focus();
  });
  document.querySelectorAll("#search-sheet .chip[data-search]").forEach(c => {
    c.addEventListener("click", () => {
      inp.value = c.dataset.search;
      clr.classList.remove("hidden");
      inp.dispatchEvent(new Event("input"));
    });
  });
}

// ---------- LAYERS SHEET ----------
function setupLayersSheet() {
  setupModalSheet("layers-sheet");
  $("fab-layers")?.addEventListener("click", () => openModalSheet("layers-sheet"));
}

// ---------- BASEMAP SHEET ----------
function setupBasemapSheet() {
  setupModalSheet("basemap-sheet");
  $("fab-basemap")?.addEventListener("click", () => openModalSheet("basemap-sheet"));
  document.querySelectorAll("#basemap-sheet .bm-card[data-bm]").forEach(c => {
    c.addEventListener("click", () => {
      document.querySelectorAll("#basemap-sheet .bm-card").forEach(x => x.classList.remove("active"));
      c.classList.add("active");
      setBasemap(c.dataset.bm);
      setTimeout(() => closeModalSheet("basemap-sheet"), 180);
    });
  });
}

// ---------- LOCATE FAB ----------
async function _ensureNativeGeoPermission() {
  const Geo = window.Capacitor?.Plugins?.Geolocation;
  if (!Geo) return true; // niente plugin -> non blocchiamo
  try {
    let perm = await Geo.checkPermissions();
    const granted = (p) => p && (p.location === "granted" || p.coarseLocation === "granted");
    if (granted(perm)) return true;
    perm = await Geo.requestPermissions({ permissions: ["location", "coarseLocation"] });
    return granted(perm);
  } catch (e) {
    console.warn("[geo] permission check failed:", e);
    return false;
  }
}
async function _getPositionAny() {
  const Geo = window.Capacitor?.Plugins?.Geolocation;
  if (Geo) {
    const pos = await Geo.getCurrentPosition({ enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    return { lat: pos.coords.latitude, lng: pos.coords.longitude };
  }
  return await new Promise((res, rej) => {
    if (!navigator.geolocation) return rej(new Error("Geolocalizzazione non disponibile"));
    navigator.geolocation.getCurrentPosition(
      p => res({ lat: p.coords.latitude, lng: p.coords.longitude }),
      err => rej(err),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  });
}
function setupLocate() {
  $("fab-locate")?.addEventListener("click", async () => {
    const btn = $("fab-locate"); btn.classList.add("locating");
    try {
      const ok = await _ensureNativeGeoPermission();
      if (!ok) { showToast("Permesso posizione negato. Abilita la posizione nelle Impostazioni."); return; }
      const { lat, lng } = await _getPositionAny();
      map.setView([lat, lng], 14, { animate: true });
      if (state.meLayer) map.removeLayer(state.meLayer);
      state.meLayer = L.circleMarker([lat, lng], {
        radius: 8, color: "#0ea5e9", weight: 3,
        fillColor: "#0ea5e9", fillOpacity: 0.4,
      }).addTo(map);
      showToast("Sei qui");
    } catch (e) {
      console.warn("[geo] error:", e);
      const msg = (e && e.message) ? e.message : "Posizione non disponibile";
      showToast(/denied|negato|permission/i.test(msg) ? "Permesso posizione negato" : "Posizione non disponibile");
    } finally {
      btn.classList.remove("locating");
    }
  });
}

// ---------- ESC global ----------
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  ["menu-sheet", "search-sheet", "layers-sheet", "basemap-sheet"].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.classList.contains("hidden")) closeModalSheet(id);
  });
});

// ---------- ZONE GEOJSON ----------
function statusStyle(feature) {
  const p = feature.properties || {};
  return {
    color: p.stroke || "#0369a1", weight: 0.8,
    fillColor: p.fill || "#94a3b8", fillOpacity: 0.45,
  };
}
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
  layer.bindTooltip(tooltipHtml(p), {
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
  const total = state.geoData.features.length;
  $("stats").innerHTML = `<span>📍 ${total}</span>
    <span style="color:#16a34a">✓ ${ok}</span>
    <span style="color:#dc2626">⚠ ${warn}</span>
    <span style="color:#64748b">? ${unk}</span>`;
  const zc = $("ms-zone-count"); if (zc) zc.textContent = `${total} zone`;
}

function refreshZoneStyle() {
  if (state.geoLayer) state.geoLayer.setStyle(currentStyle);
  if (state.selectedLayer) state.selectedLayer.setStyle(SELECTED_STYLE);
}

// ---------- ZONE DETAIL ----------
async function selectZone(name, layer) {
  switchTo("zone");
  setSheetState("half");
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
  const enr = d.enrichment || {};
  const title = enr.display_name || d.comune || "—";
  const area = enr.area || "";
  const icon = enr.icon || "🏘️";
  const comuneOfficial = enr.comune_label || d.comune || "";
  const zoneNum = enr.zone_num || "";
  const aqueduct = enr.aqueduct || "";
  const aqueductHint = enr.aqueduct_hint || "";
  const badges = (enr.badges || []).map(b => `<span class="zbadge">${escapeHtml(b)}</span>`).join("");
  const supplierBlock = aqueduct ? `
    <div class="supplier-card">
      <div class="supplier-head">
        <span class="supplier-ico">💧</span>
        <div>
          <div class="supplier-label">Acqua fornita dall'acquedotto</div>
          <div class="supplier-name">${escapeHtml(aqueduct)}</div>
        </div>
      </div>
      ${aqueductHint ? `<div class="supplier-hint"><b>ℹ️ Cosa significa?</b> ${escapeHtml(aqueductHint)}</div>` : ""}
    </div>` : "";
  const fr = d.freshness || {};
  const frBadge = fr.label && fr.label !== "n/d"
    ? `<span class="fresh-badge fresh-${fr.level}" title="Analisi di ${escapeHtml(fr.periodo || "")} \u2014 ${fr.months_old} mesi fa">${escapeHtml(fr.label)}</span>`
    : "";
  const pm = d.provider_meta || {};
  const provBadge = pm.label
    ? `<span class="prov-badge" title="${escapeHtml(pm.ato || "")}">🏛 ${escapeHtml(pm.label.split(" — ")[0])}</span>`
    : "";
  $("zone-panel").innerHTML = `
    <div class="zone-title-row">
      <div>
        <div class="zone-title">${icon} ${escapeHtml(title)}</div>
        <div class="zone-sub">
          ${area ? `<b>${escapeHtml(area)}</b> · ` : ""}
          ${comuneOfficial ? `${escapeHtml(comuneOfficial)} · ` : ""}
          ${zoneNum ? `Zona ${escapeHtml(zoneNum)} · ` : ""}
          ${escapeHtml(d.periodo || "n/d")} ${frBadge} ${provBadge}
        </div>
        ${badges ? `<div class="zone-badges">${badges}</div>` : ""}
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
      <a class="btn ghost" href="${API(escapeHtml(d.pdf_url || ''))}" target="_blank" rel="noopener">📄 PDF</a>
      <button class="btn ghost" id="zone-share" data-name="${escapeHtml(name)}">📤 Condividi</button>
    </div>
    <table class="params">
      <thead><tr><th>Parametro</th><th>U.M.</th><th>Limite</th><th>Valore</th></tr></thead>
      <tbody>${paramsRows}</tbody>
    </table>
    ${sections}
  `;
  $("zone-add-compare").addEventListener("click", () => addCompare(name));
  $("zone-share")?.addEventListener("click", () => shareZone(d, name));
}

async function shareZone(d, name) {
  const s = d.summary || {};
  const enr = d.enrichment || {};
  const title = `AcquaMap — ${enr.display_name || d.comune || name}`;
  const status = s.status === "OK" ? "✓ Conforme" : s.status === "ATTENZIONE" ? "⚠ Attenzione" : "Stato n/d";
  const text = `${title}\n${status} · ${(s.exceedances || []).length} anomalie · ${(d.parameters || []).length} parametri analizzati`;
  const url = location.href.split("#")[0] + "#zona=" + encodeURIComponent(name);
  const payload = { title, text, url };
  try {
    const Share = window.Capacitor?.Plugins?.Share;
    if (Share && typeof Share.share === "function") {
      await Share.share({ title, text, url, dialogTitle: "Condividi zona" });
      return;
    }
  } catch (e) { /* fallback below */ }
  try {
    if (navigator.share) { await navigator.share(payload); return; }
  } catch (e) { /* user cancelled or unsupported */ }
  try {
    await navigator.clipboard.writeText(`${text}\n${url}`);
    showToast("Link copiato negli appunti");
  } catch {
    showToast("Condivisione non disponibile");
  }
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
      setSheetState("half");
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
    const fut = it.is_future ? `<span class="sev sev-future">🔮</span>` : "";
    const romaTag = it.is_rome ? `<span class="sev sev-roma" title="Roma o Città Metropolitana">🏛️</span>` : "";
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
    const gen = data.generated_at ? new Date(data.generated_at * 1000) : null;
    const next = data.next_refresh_at ? new Date(data.next_refresh_at * 1000) : null;
    const ttlH = data.ttl_seconds ? Math.round(data.ttl_seconds / 3600) : null;
    const refreshing = data.refreshing ? ' · <em>aggiornamento in corso…</em>' : "";
    $("news-meta").innerHTML = `
      <span>${state.newsItems.length} notizie</span>
      ${gen ? `<span title="Ultimo aggiornamento">aggiornato ${gen.toLocaleString("it-IT")}</span>` : ""}
      ${next && ttlH ? `<span title="Prossimo refresh">prossimo ~${next.toLocaleTimeString("it-IT", {hour:"2-digit", minute:"2-digit"})}</span>` : ""}
      ${refreshing}`;
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
        <div class="summary">${escapeHtml(n.name || "Nasone")}<br/>
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

// ---------- FONTI UFFICIALI ----------
async function loadOfficialSources() {
  const el = $("official-sources"); if (!el) return;
  try {
    const r = await fetch(API("/api/sources"));
    const d = await r.json();
    el.innerHTML = (d.items || []).map(s => {
      const ato = s.ato ? `<span class="src-pill src-ato">${escapeHtml(s.ato)}</span>` : "";
      const tracked = s.provider ? (s.scraped
        ? `<span class="src-pill src-scraped">● Dati in AcquaMap</span>`
        : `<span class="src-pill src-link">● Solo link</span>`) : "";
      return `
      <a class="source-card" href="${s.url}" target="_blank" rel="noopener">
        <div class="source-card-head">
          <span class="source-card-title">${escapeHtml(s.title)}</span>
          <span class="source-card-open">Apri ↗</span>
        </div>
        <div class="source-card-meta">${escapeHtml(s.agency)} · ${escapeHtml(s.type)}</div>
        ${(ato || tracked) ? `<div class="source-card-pills">${ato}${tracked}</div>` : ""}
        <div class="source-card-desc">${escapeHtml(s.description)}</div>
        ${s.hint ? `<div class="source-card-hint">💡 ${escapeHtml(s.hint)}</div>` : ""}
      </a>`;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div class="hint">Impossibile caricare le fonti (${escapeHtml(e.message || e)}).</div>`;
  }
}

// ---------- PARAMETER ----------
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
  const legend = $("param-legend");
  const step = (d.max - d.min) / RAMP.length;
  legend.innerHTML = `<div class="legend-title">${escapeHtml(name)} <small>(${d.items[0]?.unita || ""})</small></div>
    <div class="legend-bar">${RAMP.map((c, i) => {
      const v = d.min + step * i;
      return `<span style="background:${c}" title="${v.toFixed(3)}"></span>`;
    }).join("")}</div>
    <div class="legend-range"><span>${d.min.toFixed(2)}</span><span>med ${d.median.toFixed(2)}</span><span>${d.max.toFixed(2)}</span></div>
    <div class="legend-hint">${d.count} zone · bordo rosso = supero limite</div>`;
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
    if (q.length < 2) { box.innerHTML = ""; return; }
    tmo = setTimeout(async () => {
      if (searchAbort) searchAbort.abort();
      searchAbort = new AbortController();
      try {
        const r = await fetch(API(`/api/search?q=${encodeURIComponent(q)}&limit=12`), { signal: searchAbort.signal });
        const d = await r.json();
        if (!d.items.length) { box.innerHTML = `<div class="sr-empty">Nessun risultato</div>`; return; }
        box.innerHTML = d.items.map(it => {
          const titleLine = it.display_name
            ? `${it.icon || "🏘️"} ${escapeHtml(it.display_name)}`
            : `${escapeHtml(it.comune || "")} · ${escapeHtml(it.zona || "")}`;
          const subLine = it.area
            ? `${escapeHtml(it.area)}${it.aqueduct ? ` · 💧 ${escapeHtml(it.aqueduct)}` : ""}`
            : (it.zona ? escapeHtml(it.zona) : "");
          return `
          <div class="sr-item" data-name="${escapeHtml(it.name)}">
            <div class="sr-title">${titleLine}</div>
            ${subLine ? `<div class="sr-sub">${subLine}</div>` : ""}
            <div class="sr-meta">
              <span class="badge ${it.status === 'OK' ? 'ok' : it.status === 'ATTENZIONE' ? 'warn' : 'unk'}">${escapeHtml(it.status || "?")}</span>
              ${it.exceedances ? `<span>· ${it.exceedances} anomalie</span>` : ""}
            </div>
          </div>`;
        }).join("");
        box.querySelectorAll(".sr-item").forEach(el => {
          el.addEventListener("click", () => {
            onPick(el.dataset.name);
            input.value = "";
            box.innerHTML = "";
          });
        });
      } catch (e) {
        if (e.name !== "AbortError") box.innerHTML = `<div class="sr-empty">Errore: ${escapeHtml(e.message)}</div>`;
      }
    }, 180);
  });
}
function pickZoneFromSearch(name) {
  closeModalSheet("search-sheet");
  pickZoneByName(name);
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
bindSearch("search-input", "search-results", pickZoneFromSearch);

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
  const exP = d.top_exceedances_by_parameter || [];
  new Chart($("chart-exc-param"), {
    type: "bar",
    data: {
      labels: exP.map(([p]) => p),
      datasets: [{ label: "zone con supero", data: exP.map(([, c]) => c), backgroundColor: "#dc2626" }],
    },
    options: { indexAxis: "y", scales: { x: { beginAtZero: true } }, plugins: { legend: { display: false } } },
  });
  const exC = d.top_exceedances_by_comune || [];
  new Chart($("chart-exc-comune"), {
    type: "bar",
    data: {
      labels: exC.map(([c]) => c),
      datasets: [{ label: "anomalie", data: exC.map(([, n]) => n), backgroundColor: "#ea580c" }],
    },
    options: { indexAxis: "y", scales: { x: { beginAtZero: true } }, plugins: { legend: { display: false } } },
  });
  const rows = (d.parameter_stats || []).slice(0, 20).map(p => `
    <tr><td>${escapeHtml(p.parametro)}</td>
        <td class="num">${p.count}</td>
        <td class="num">${(+p.min).toFixed(3)}</td>
        <td class="num">${(+p.median).toFixed(3)}</td>
        <td class="num">${(+p.mean).toFixed(3)}</td>
        <td class="num">${(+p.max).toFixed(3)}</td></tr>`).join("");
  $("dashboard-table-wrap").innerHTML = `
    <div class="scroll-x"><table class="params"><thead><tr><th>Parametro</th><th>n</th><th>min</th><th>med</th><th>mean</th><th>max</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}

// ---------- COMPARE ----------
bindSearch("compare-input", "compare-suggest", (name) => addCompare(name));

async function addCompare(name) {
  if (state.compareList.includes(name)) return;
  if (state.compareList.length >= 4) { showToast("Massimo 4 zone"); return; }
  state.compareList.push(name);
  switchTo("compare");
  setSheetState("half");
  await renderCompare();
}
function removeCompare(name) {
  state.compareList = state.compareList.filter(n => n !== name);
  renderCompare();
}

async function renderCompare() {
  $("compare-chips").innerHTML = state.compareList.map(n => {
    const f = (state.geoData?.features || []).find(ff => (ff.properties || {}).name === n);
    const p = f ? f.properties : {};
    const lbl = p.display_name ? `${p.icon || "🏘️"} ${p.display_name}` : n;
    return `<span class="chip active" style="--c:#0369a1">${escapeHtml(lbl)} <button data-rm="${escapeHtml(n)}">×</button></span>`;
  }).join("");
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
    `<th>${z.icon || "🏘️"} ${escapeHtml(z.display_name || z.comune || "")}<br/><small>${escapeHtml(z.area || z.zona || "")}</small></th>`).join("")}</tr>`;
  const statusRow = `<tr><td><b>Stato</b></td>${d.zones.map(z =>
    `<td><span class="badge ${z.status === 'OK' ? 'ok' : z.status === 'ATTENZIONE' ? 'warn' : 'unk'}">${escapeHtml(z.status || "?")}</span></td>`).join("")}</tr>`;
  const rows = d.parameters.map(p => {
    return `<tr><td>${escapeHtml(p)}</td>${d.zones.map(z => {
      const item = z.parameters[p];
      if (!item) return `<td class="num">—</td>`;
      const exceed = z.exceedances.some(e => e.parametro === p);
      return `<td class="num ${exceed ? 'exc' : ''}">${escapeHtml(item.valore || "—")}<br/><small>${escapeHtml(item.limite || "—")}</small></td>`;
    }).join("")}</tr>`;
  }).join("");
  $("compare-table-wrap").innerHTML = `<table class="params compare-table"><thead>${head}</thead><tbody>${statusRow}${rows}</tbody></table>`;
}

// ---------- CHAT ----------
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

// ---------- INFO ----------
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
  const dash = await (await fetch(API("/api/dashboard"))).json();
  $("info-numbers").innerHTML = `
    <div class="kpi"><strong>${dash.total_zones}</strong><span>zone</span></div>
    <div class="kpi"><strong>${dash.total_parameters_distinct}</strong><span>parametri</span></div>
    <div class="kpi"><strong>${(dash.top_exceedances_by_parameter || []).reduce((s, [, c]) => s + c, 0)}</strong><span>superi</span></div>
  `;
  loadOfficialSources();
}

// (Aggiornamento news disabilitato lato utente: refresh automatico ogni 15 min,
// stesso contenuto condiviso per tutti, gestito server-side per evitare costi.)

// ---------- METEO ----------
const WCODE = {
  0: ["☀️","sereno"], 1: ["🌤️","poco nuv."], 2: ["⛅","variabile"], 3: ["☁️","coperto"],
  45: ["🌫️","nebbia"], 48: ["🌫️","nebbia gelo"],
  51: ["🌦️","pioviggine"], 53: ["🌦️","pioviggine"], 55: ["🌦️","pioviggine"],
  61: ["🌧️","pioggia"], 63: ["🌧️","pioggia"], 65: ["🌧️","pioggia forte"],
  71: ["🌨️","neve"], 73: ["🌨️","neve"], 75: ["❄️","neve forte"],
  80: ["🌦️","rovesci"], 81: ["🌧️","rovesci"], 82: ["⛈️","rovesci forti"],
  95: ["⛈️","temporale"], 96: ["⛈️","temp."], 99: ["⛈️","temp."],
};

async function loadMeteo() {
  state.meteoLoaded = true;
  $("meteo-status").innerText = "Caricamento dati Open-Meteo…";
  try {
    const m = await fetch(API("/api/meteo")).then(r => r.json());
    if (m.error) throw new Error(m.error);
    renderMeteo(m);
    $("meteo-status").innerText = `${m.source} · agg. ${new Date(m.updated).toLocaleString("it-IT")}`;
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
  banner.innerHTML = `<strong>${(d.label || "n/d").toUpperCase()}</strong> ·
    indice 90gg vs media = ${d.ratio_90d_vs_normal ?? "n/d"} ·
    ${m.rain_mm.last_90d} mm vs ${m.rain_mm.expected_90d_from_365d_mean} attesi`;
  banner.classList.remove("hidden");

  $("meteo-kpis").innerHTML = `
    <div class="kpi"><strong>${m.rain_mm.last_7d}</strong><span>mm 7gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_30d}</strong><span>mm 30gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_90d}</strong><span>mm 90gg</span></div>
    <div class="kpi"><strong>${m.rain_mm.last_365d}</strong><span>mm 365gg</span></div>
    <div class="kpi"><strong>${m.temp_c.mean_last_30d ?? "—"}°</strong><span>T media 30gg</span></div>
  `;

  const ctxH = $("chart-rain-history").getContext("2d");
  if (state.chartHist) state.chartHist.destroy();
  state.chartHist = new Chart(ctxH, {
    type: "bar",
    data: {
      labels: m.history_90d.map(x => x.date.slice(5)),
      datasets: [{ label: "Pioggia (mm)", data: m.history_90d.map(x => x.rain), backgroundColor: "#0284c7" }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
        y: { beginAtZero: true, title: { display: true, text: "mm/giorno" } },
      },
    },
  });

  const ctxF = $("chart-rain-forecast").getContext("2d");
  if (state.chartFcst) state.chartFcst.destroy();
  state.chartFcst = new Chart(ctxF, {
    data: {
      labels: m.forecast_7d.map(x => new Date(x.date).toLocaleDateString("it-IT", { weekday: "short", day: "numeric" })),
      datasets: [
        { type: "bar",  label: "Pioggia mm", data: m.forecast_7d.map(x => x.rain), backgroundColor: "#0284c7", yAxisID: "y" },
        { type: "line", label: "Tmax °C",    data: m.forecast_7d.map(x => x.tmax), borderColor: "#dc2626", backgroundColor: "transparent", yAxisID: "y1", tension: 0.3 },
        { type: "line", label: "Tmin °C",    data: m.forecast_7d.map(x => x.tmin), borderColor: "#1d4ed8", backgroundColor: "transparent", yAxisID: "y1", tension: 0.3 },
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
      <div class="fc-date">${new Date(d.date).toLocaleDateString("it-IT", { weekday: "short", day: "numeric" })}</div>
      <div class="fc-icon">${emoji}</div>
      <div class="fc-temp">${Math.round(d.tmin)}° / <strong>${Math.round(d.tmax)}°</strong></div>
      <div class="fc-rain">💧 ${d.rain}mm</div>
      <div class="fc-txt">${txt}</div>
    </div>`;
  }).join("");
}

// ---------- BOOT ----------
(async () => {
  // shell mobile
  setSheetState("peek");
  setupSheetDrag();
  setupBottomNav();
  setupMenuSheet();
  setupSearchSheet();
  setupLayersSheet();
  setupBasemapSheet();
  setupLocate();
  setupDesktopTabs();
  setupNativeIntegrations();

  // dati
  try { await loadGeoJSON(); } catch (e) { console.error(e); showToast("Errore caricamento zone"); }
  try { await loadParameterList(); } catch (e) { console.error(e); }
  loadNews().catch(e => console.error(e));
  setInterval(() => loadNews(false), 15 * 60 * 1000);
})();

// ---------- DESKTOP TABS (≥1024px) ----------
function setupDesktopTabs() {
  document.querySelectorAll(".dt-tab[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".dt-tab").forEach(x => x.classList.remove("active"));
      btn.classList.add("active");
      switchTo(tab);
    });
  });
}

// Mantieni i .dt-tab in sync quando si cambia tab da altri punti (bottom-nav, menu, ecc.)
const _origSwitchTo = switchTo;
switchTo = function(tabId) {
  _origSwitchTo(tabId);
  document.querySelectorAll(".dt-tab").forEach(x => x.classList.toggle("active", x.dataset.tab === tabId));
};

// ---------- NATIVE INTEGRATIONS (Capacitor) ----------
function setupNativeIntegrations() {
  if (!IS_NATIVE) return;
  try {
    // Status bar: stile coerente con la app-bar (chiara o scura).
    const SB = window.Capacitor?.Plugins?.StatusBar;
    if (SB) {
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      SB.setStyle?.({ style: dark ? "DARK" : "LIGHT" }).catch(() => {});
      SB.setBackgroundColor?.({ color: dark ? "#020617" : "#0c4a6e" }).catch(() => {});
      SB.setOverlaysWebView?.({ overlay: false }).catch(() => {});
    }
  } catch (e) { console.warn(e); }

  try {
    // Quando l'app torna in foreground: ricarica news + geojson silenziosamente.
    const App = window.Capacitor?.Plugins?.App;
    if (App && typeof App.addListener === "function") {
      App.addListener("resume", () => {
        loadNews(false).catch(() => {});
        // Aggiorna freschezza zone (silenzioso)
        fetch(API("/api/geojson")).then(r => r.ok ? r.json() : null).then(d => {
          if (!d || !state.geoLayer) return;
          state.geoData = d;
          state.geoLayer.clearLayers();
          state.geoLayer.addData(d);
          state.geoLayer.setStyle(currentStyle);
        }).catch(() => {});
      });
      // Tasto BACK Android: chiudi modali/sheet invece di uscire.
      App.addListener("backButton", ({ canGoBack }) => {
        const open = ["menu-sheet", "search-sheet", "layers-sheet", "basemap-sheet"]
          .find(id => { const el = document.getElementById(id); return el && !el.classList.contains("hidden"); });
        if (open) { closeModalSheet(open); return; }
        const sh = $("sheet");
        if (sh && sh.dataset.state === "full") { setSheetState("half"); return; }
        if (sh && sh.dataset.state === "half") { setSheetState("peek"); return; }
        if (canGoBack) history.back(); else App.exitApp?.();
      });
    }
  } catch (e) { console.warn(e); }

  // Haptic leggero al cambio tab (mobile only).
  document.addEventListener("click", (e) => {
    if (e.target.closest?.(".bn-item, .ms-item[data-tab], .dt-tab")) {
      try { window.Capacitor?.Plugins?.Haptics?.impact?.({ style: "LIGHT" }); } catch {}
    }
  });
}
