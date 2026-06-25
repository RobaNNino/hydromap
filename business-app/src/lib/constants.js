// Vocabolari condivisi AcquaMap Business (V1).

export const CATEGORIES = [
  { v: "bar", l: "Bar" },
  { v: "ristorante", l: "Ristorante" },
  { v: "hotel", l: "Hotel" },
  { v: "palestra", l: "Palestra" },
  { v: "coworking", l: "Coworking" },
  { v: "ufficio", l: "Ufficio" },
  { v: "scuola", l: "Scuola" },
  { v: "negozio", l: "Negozio" },
  { v: "altro", l: "Altro" },
];
export const catLabel = (v) => CATEGORIES.find((c) => c.v === v)?.l || "Attività";
export const CAT_ICON = {
  bar: "☕", ristorante: "🍽️", hotel: "🏨", palestra: "🏋️",
  coworking: "💼", ufficio: "🏢", scuola: "🎓", negozio: "🛍️", altro: "📍",
};

export const REFERENT_ROLES = ["Titolare", "Manager", "Responsabile marketing", "Dipendente", "Altro"];

export const COLLAB_INTERESTS = [
  "Visibilità", "Plastic free", "Refill", "Qualità acqua",
  "Profilo verificato", "Analisi acqua future", "Dashboard analytics",
];

// Pipeline interna admin (8 step). Lo step è derivato lato backend.
export const ADMIN_STEPS = [
  { key: "new", label: "Nuove richieste", color: "#0ea5e9" },
  { key: "to_complete", label: "Profilo da completare", color: "#6366f1" },
  { key: "review", label: "Revisione contenuti", color: "#8b5cf6" },
  { key: "badge", label: "Verifica e badge", color: "#d946ef" },
  { key: "publish", label: "Pubblicazione", color: "#f59e0b" },
  { key: "access", label: "Accesso Business", color: "#10b981" },
  { key: "active", label: "Dashboard attiva", color: "#16a34a" },
  { key: "premium", label: "Analisi / Premium", color: "#475569" },
];
export const stepMeta = (k) => ADMIN_STEPS.find((s) => s.key === k) || ADMIN_STEPS[0];

// Badge V1 — pochi ma autorevoli.
export const BADGES = [
  { key: "verified", label: "AcquaMap Verified", color: "#16a34a", icon: "✓" },
  { key: "water_experience", label: "Water Experience", color: "#0492cf", icon: "💧" },
  { key: "lab_quality", label: "Lab Quality", color: "#7c3aed", icon: "🧪" },
  { key: "business_premium", label: "Business Premium", color: "#f59e0b", icon: "◆" },
];
export const badgeMeta = (k) => BADGES.find((b) => b.key === k);

export const PROFILE_STATUSES = {
  draft: "Bozza",
  in_review: "In revisione",
  changes_requested: "Modifiche richieste",
  approved: "Approvato",
  published: "Pubblicato",
  suspended: "Sospeso",
  archived: "Archiviato",
};

export const APPLICATION_STATUSES = { pending: "In attesa", accepted: "Accettata", rejected: "Rifiutata" };

// ---- Analytics (V2) ----
export const EVENT_LABELS = {
  view: "Visualizzazioni", open_map: "Aperture mappa", click_phone: "Click telefono",
  click_maps: "Click indicazioni", click_website: "Click sito", click_instagram: "Click Instagram",
  click_whatsapp: "Click WhatsApp", open_gallery: "Aperture gallery",
};

// Completezza profilo (mirror del backend) — 0..100.
export function computeCompleteness(p = {}) {
  const wi = p.water_info || {};
  const ex = p.extra || {};
  const checks = [
    p.business_name, p.category, p.address, p.city, p.phone, p.description, ex.long_desc,
    ex.hours && Object.keys(ex.hours).length, ex.services && ex.services.length,
    (wi.water_type && wi.water_type.length) || (ex.water && Object.values(ex.water).some(Boolean)),
    p.logo_url, p.cover_image_url, p.latitude != null && p.longitude != null,
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

// Trust score (mirror del backend) — 0..100.
export function computeTrust(p = {}) {
  let s = computeCompleteness(p) * 0.4;
  if (p.verification_status && p.verification_status !== "not_verified") s += 20;
  if (p.logo_url && p.cover_image_url) s += 10;
  s += Math.min(20, (p.badges || []).length * 7);
  if (p.latitude != null && p.longitude != null) s += 10;
  return Math.round(Math.min(100, s));
}

export const PRIVACY_TEXT = `Informativa sul trattamento dei dati personali — AcquaMap Business

Titolare del trattamento
Il titolare del trattamento è AcquaMap / Hydroroma. Per qualsiasi richiesta relativa ai tuoi dati puoi scrivere a acquamap@hydroroma.com.

Finalità del trattamento
I dati forniti tramite questo modulo di candidatura sono trattati per: (a) valutare la richiesta di adesione al programma AcquaMap Business Expand; (b) contattare il referente indicato; (c) creare, previa approvazione, un profilo pubblico dell'attività su AcquaMap; (d) gestire la collaborazione, le comunicazioni di servizio e l'eventuale assistenza.

Base giuridica
Il trattamento si fonda sul consenso dell'interessato e sull'esecuzione di misure precontrattuali richieste dall'interessato.

Categorie di dati
Dati identificativi dell'attività e del referente, dati di contatto, informazioni commerciali e relative ai servizi (incluse informazioni sull'acqua), eventuali immagini caricate.

Dati pubblicati
In caso di approvazione e con il tuo consenso esplicito, alcuni dati dell'attività (nome, categoria, indirizzo, contatti pubblici, descrizione, foto, servizi e informazioni sull'acqua) saranno resi pubblici sul profilo AcquaMap. I dati del referente NON sono pubblicati e restano riservati al team AcquaMap.

Comunicazioni commerciali
Con apposito e separato consenso, i dati di contatto potranno essere usati per comunicazioni relative al programma e a funzionalità future (incluse analisi dell'acqua e piani premium).

Conservazione
I dati sono conservati per il tempo necessario alle finalità indicate e, in caso di mancata approvazione, per un periodo limitato a fini di verifica e contatto, salvo richiesta di cancellazione.

Diritti dell'interessato
Hai diritto di accesso, rettifica, cancellazione, limitazione, opposizione e portabilità dei dati, oltre al diritto di revocare il consenso in qualsiasi momento e di proporre reclamo all'autorità di controllo.

Veridicità dei dati
Dichiarando di accettare, confermi che i dati inseriti sono veritieri e che sei autorizzato a fornirli per conto dell'attività indicata.

Scorrendo fino in fondo e accettando, dichiari di aver letto e compreso la presente informativa.

— Fine dell'informativa —`;
