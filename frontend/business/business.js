/* ============================================================
 * AcquaMap Business — helper condivisi tra le pagine business
 *   (apply / profile / dashboard / admin)
 *   Stesso schema di rilevamento API base di app.js.
 * ============================================================ */

// ---------- API base (mirror di frontend/app.js) ----------
const _cap = window.Capacitor;
const IS_NATIVE = !!(_cap && (
  (typeof _cap.isNativePlatform === "function" && _cap.isNativePlatform()) ||
  (typeof _cap.getPlatform === "function" && _cap.getPlatform() !== "web")
));
const _isLocalHost = !IS_NATIVE && (
  /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname) ||
  location.protocol === "file:"
);
const _metaApiBase = _isLocalHost ? "" : (document.querySelector('meta[name="api-base"]')?.content || "");
const API_BASE = (window.API_BASE || _metaApiBase || "").replace(/\/$/, "");
const API = (p) => API_BASE + p;

// ---------- Supabase Auth (client browser, publishable key) ----------
// Inizializzato solo se la pagina carica supabase-js + supabase-config.js.
let _sb = null;
function sbClient() {
  if (_sb) return _sb;
  const cfg = window.SUPABASE_CONFIG;
  if (cfg && window.supabase && typeof window.supabase.createClient === "function") {
    _sb = window.supabase.createClient(cfg.url, cfg.publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true },
    });
  }
  return _sb;
}
async function getAccessToken() {
  const c = sbClient();
  if (!c) return "";
  try {
    const { data } = await c.auth.getSession();
    return data?.session?.access_token || "";
  } catch (_) { return ""; }
}
async function getUser() {
  const c = sbClient();
  if (!c) return null;
  const { data } = await c.auth.getSession();
  return data?.session?.user || null;
}
async function signIn(email, password) {
  const c = sbClient();
  if (!c) throw new Error("Supabase non inizializzato.");
  const { data, error } = await c.auth.signInWithPassword({ email, password });
  if (error) throw new Error(error.message);
  return data;
}
async function signUp(email, password) {
  const c = sbClient();
  if (!c) throw new Error("Supabase non inizializzato.");
  const { data, error } = await c.auth.signUp({ email, password });
  if (error) throw new Error(error.message);
  return data;
}
async function signOut() {
  const c = sbClient();
  if (c) await c.auth.signOut();
}

// ---------- utils ----------
const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function qs(name) {
  return new URLSearchParams(location.search).get(name) || "";
}

// Slug dal path /acquamap/business/<slug> oppure da ?slug=
function slugFromLocation() {
  const m = location.pathname.match(/\/acquamap\/business\/([^/?#]+)/);
  if (m && m[1] && !["apply", "dashboard"].includes(m[1])) return decodeURIComponent(m[1]);
  return qs("slug");
}

// ---------- vocabolari (label IT) ----------
const CATEGORY_LABELS = {
  bar: "Bar", ristorante: "Ristorante", hotel: "Hotel",
  palestra: "Palestra", centro_sportivo: "Centro sportivo",
  ufficio: "Ufficio", altro: "Altro",
};
const CATEGORY_ICONS = {
  bar: "☕", ristorante: "🍽️", hotel: "🏨", palestra: "🏋️",
  centro_sportivo: "🤸", ufficio: "🏢", altro: "📍",
};
const WATER_TYPE_LABELS = {
  rete: "Acqua di rete", filtrata: "Acqua filtrata",
  microfiltrata: "Acqua microfiltrata", frizzante: "Acqua frizzante",
  naturale: "Acqua naturale", altro: "Altro",
};
const FILTER_LABELS = { yes: "Sì", no: "No", undeclared: "Non dichiarato" };
const WATER_PARAM_LABELS = {
  ph: "pH", hardness: "Durezza (°F)", residue_fixed: "Residuo fisso (mg/L)",
  conductivity: "Conducibilità (µS/cm)", chlorine: "Cloro (mg/L)",
  nitrates: "Nitrati (mg/L)", sodium: "Sodio (mg/L)",
  calcium: "Calcio (mg/L)", magnesium: "Magnesio (mg/L)",
};

const catLabel = (c) => CATEGORY_LABELS[c] || "Attività";
const catIcon = (c) => CATEGORY_ICONS[c] || "📍";

// ---------- badge ----------
// Restituisce l'HTML dei badge di verifica / programma / premium.
function verifyBadgeHtml(profile) {
  const v = profile.verification_status || "not_verified";
  if (v === "business_verified") {
    return `<span class="biz-badge badge-verified" title="Profilo verificato da AcquaMap">
      <span class="bb-ico">✓</span> AcquaMap Business Verified</span>`;
  }
  if (v === "verified") {
    return `<span class="biz-badge badge-verified" title="Profilo verificato da AcquaMap">
      <span class="bb-ico">✓</span> Verificato</span>`;
  }
  return `<span class="biz-badge badge-unverified" title="Profilo non ancora verificato">
    Non verificato</span>`;
}

function expandBadgeHtml(profile) {
  if (!profile.is_expand_program) return "";
  return `<span class="biz-badge badge-expand" title="Membro AcquaMap Business Expand Program">
    ★ Expand Program</span>`;
}

function premiumBadgeHtml(profile, { locked = false } = {}) {
  if (profile.is_premium) {
    return `<span class="biz-badge badge-premium">◆ Premium</span>`;
  }
  if (locked) {
    return `<span class="biz-badge badge-premium-locked" title="Funzionalità premium in arrivo">
      🔒 Premium in arrivo</span>`;
  }
  return "";
}

// ---------- toast ----------
let _toastTimer = null;
function toast(msg, kind = "ok") {
  let el = $("biz-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "biz-toast";
    el.className = "biz-toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = `biz-toast show ${kind}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = "biz-toast"; }, 3200);
}

// ---------- fetch helper ----------
// Allega automaticamente il bearer JWT di Supabase Auth se disponibile.
async function apiFetch(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (!headers.Authorization) {
    const token = await getAccessToken();
    if (token) headers.Authorization = "Bearer " + token;
  }
  const r = await fetch(API(path), { ...opts, headers });
  let body = null;
  try { body = await r.json(); } catch (_) {}
  if (!r.ok) {
    const msg = (body && (body.description || body.error)) || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return body;
}
