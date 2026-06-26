import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Box, Container, Typography, TextField, MenuItem, Switch, FormControlLabel,
  Button, Accordion, AccordionSummary, AccordionDetails, Stack, LinearProgress,
  CircularProgress, Alert, Chip, Tooltip, InputAdornment,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import { toast } from "sonner";
import PublicTopbar from "../components/PublicTopbar.jsx";
import ImageCropField from "../components/ImageCropField.jsx";
import { api } from "../lib/api.js";
import { CATEGORIES } from "../lib/constants.js";

const DAYS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const SERVICES = ["Wi-Fi", "Prenotazione", "Tavoli esterni", "Accessibile", "Pet friendly", "Take away", "Delivery", "Adatto famiglie", "Adatto lavoro/studio"];
const WATER = [
  ["water_natural", "Acqua naturale"], ["water_sparkling", "Acqua frizzante"],
  ["water_microfiltered", "Microfiltrata"], ["water_purified", "Depurata"],
  ["water_glass", "Servita in vetro"], ["water_refill", "Refill disponibile"],
  ["water_bottles", "Accetta borracce"], ["water_plasticfree", "Plastic free friendly"],
];

// Normalizza gli orari salvati (vecchio formato stringa -> {m,p}).
function normHours(h = {}) {
  const out = {};
  for (const d of DAYS) {
    const v = h[d];
    if (typeof v === "string") out[d] = { m: v, p: "" };
    else out[d] = { m: v?.m || "", p: v?.p || "" };
  }
  return out;
}

// ---- Componenti a livello di modulo (NON dentro il render: evita il remount
//      che faceva perdere il focus agli input a ogni lettera). ----
function HintIcon({ hint }) {
  if (!hint) return null;
  return (
    <Tooltip title={hint} arrow enterTouchDelay={0} leaveTouchDelay={5000}>
      <HelpOutlineIcon sx={{ fontSize: 18, color: "text.disabled", cursor: "help" }} />
    </Tooltip>
  );
}

function Section({ id, title, desc, openId, setOpenId, children }) {
  return (
    <Accordion expanded={openId === id} onChange={() => setOpenId(openId === id ? "" : id)}
      disableGutters elevation={0}
      sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, mb: 1.5, "&:before": { display: "none" }, overflow: "hidden" }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box><Typography sx={{ fontWeight: 700 }}>{title}</Typography>
          <Typography variant="body2" color="text.secondary">{desc}</Typography></Box>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}

// Campo testo riutilizzabile con tooltip "?" (endAdornment per single-line,
// helperText per multiline). Componente STABILE a livello di modulo.
function TextRow({ label, hint, value, onChange, multiline, minRows, select, children, ...rest }) {
  const help = hint ? (
    multiline || select
      ? {}
      : { InputProps: { endAdornment: <InputAdornment position="end"><HintIcon hint={hint} /></InputAdornment> } }
  ) : {};
  return (
    <TextField
      fullWidth size="small" label={label} value={value}
      onChange={(e) => onChange(e.target.value)}
      multiline={multiline} minRows={minRows} select={select}
      helperText={hint && (multiline || select) ? hint : undefined}
      {...help} {...rest}
    >
      {children}
    </TextField>
  );
}

const SECTIONS_GRID = { display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 };

export default function OnboardingPage() {
  const { token } = useParams();
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [openId, setOpenId] = useState("identita");

  useEffect(() => {
    (async () => {
      try {
        const p = await api(`/api/business/onboarding/${token}`, { auth: false });
        setForm({
          business_name: p.business_name || "", category: p.category || "altro",
          claim: p.extra?.claim || "", short_desc: p.description || "", long_desc: p.extra?.long_desc || "",
          address: p.address || "", city: p.city || "", province: p.province || "", cap: p.extra?.cap || "",
          phone: p.phone || "", public_email: p.public_email || "", website: p.website || "",
          instagram: p.instagram || "", whatsapp: p.extra?.whatsapp || "",
          logo_url: p.logo_url || "", cover_image_url: p.cover_image_url || "",
          hours: normHours(p.extra?.hours || {}), services: p.extra?.services || [], water: p.extra?.water || {},
          water_notes: p.extra?.water_notes || "",
        });
      } catch (e) { setErr(e.message || "Link non valido o scaduto."); }
      finally { setLoading(false); }
    })();
  }, [token]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setWater = (k, v) => setForm((f) => ({ ...f, water: { ...f.water, [k]: v } }));
  const setHour = (day, slot, v) => setForm((f) => ({ ...f, hours: { ...f.hours, [day]: { ...f.hours[day], [slot]: v } } }));

  const completeness = useMemo(() => {
    if (!form) return 0;
    const hoursSet = Object.values(form.hours || {}).some((h) => h.m || h.p);
    const checks = [
      form.business_name, form.category, form.address, form.city, form.phone,
      form.short_desc, form.long_desc, hoursSet, form.services?.length,
      Object.values(form.water || {}).some(Boolean), form.logo_url, form.cover_image_url,
    ];
    return Math.round((checks.filter(Boolean).length / checks.length) * 100);
  }, [form]);

  const payload = () => ({
    business_name: form.business_name, category: form.category,
    description: form.short_desc, address: form.address, city: form.city, province: form.province,
    phone: form.phone, public_email: form.public_email, website: form.website, instagram: form.instagram,
    logo_url: form.logo_url, cover_image_url: form.cover_image_url,
    extra: {
      claim: form.claim, long_desc: form.long_desc, cap: form.cap, whatsapp: form.whatsapp,
      hours: form.hours, services: form.services, water: form.water, water_notes: form.water_notes,
    },
  });

  const save = async (submit) => {
    setSaving(true);
    try {
      await api(`/api/business/onboarding/${token}`, { method: "PATCH", auth: false, body: payload() });
      if (submit) {
        await api(`/api/business/onboarding/${token}/submit`, { method: "POST", auth: false, body: {} });
        toast.success("Profilo inviato per la revisione!");
        setSubmitted(true);
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else toast.success("Bozza salvata");
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  if (loading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;
  if (err) return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}><PublicTopbar />
      <Container maxWidth="sm" sx={{ py: 8 }}><Alert severity="error" sx={{ borderRadius: 3 }}>{err}</Alert></Container></Box>
  );

  if (submitted) return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <PublicTopbar />
      <Container maxWidth="sm" sx={{ py: { xs: 6, md: 10 }, textAlign: "center" }}>
        <Typography sx={{ fontSize: 72, lineHeight: 1 }}>🎉</Typography>
        <Typography variant="h4" sx={{ mt: 1, mb: 1.5 }}>Grazie! Profilo inviato</Typography>
        <Typography color="text.secondary" sx={{ maxWidth: 460, mx: "auto" }}>
          Abbiamo ricevuto il profilo di <b>{form.business_name || "la tua attività"}</b>.
          Il team AcquaMap revisionerà i contenuti e le immagini prima della pubblicazione.
        </Typography>
        <Alert severity="info" sx={{ borderRadius: 3, mt: 3, textAlign: "left", justifyContent: "center" }}>
          Ti avviseremo via email appena il profilo sarà online. Nel frattempo puoi chiudere questa pagina.
        </Alert>
        <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
          <Button variant="contained" href="/">Vai ad AcquaMap</Button>
          <Button variant="outlined" onClick={() => setSubmitted(false)}>Torna al profilo</Button>
        </Stack>
      </Container>
    </Box>
  );

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <PublicTopbar />
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Typography variant="h4" gutterBottom>Completa il profilo</Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>Compila i dati pubblici della tua attività. Verranno revisionati prima della pubblicazione. Passa il mouse sui <b>?</b> per le spiegazioni.</Typography>
        <Stack direction="row" justifyContent="space-between"><Typography variant="body2">Completezza</Typography><Typography variant="body2">{completeness}%</Typography></Stack>
        <LinearProgress variant="determinate" value={completeness} sx={{ borderRadius: 2, mb: 3 }} />

        <Section id="identita" title="🏪 Identità attività" desc="Nome, categoria, claim." openId={openId} setOpenId={setOpenId}>
          <Box sx={SECTIONS_GRID}>
            <TextRow label="Nome commerciale" hint="Il nome/insegna con cui i clienti ti conoscono." value={form.business_name} onChange={(v) => set("business_name", v)} />
            <TextRow label="Categoria" select hint="Il tipo di attività più rappresentativo." value={form.category} onChange={(v) => set("category", v)}>
              {CATEGORIES.map((c) => <MenuItem key={c.v} value={c.v}>{c.l}</MenuItem>)}
            </TextRow>
            <Box sx={{ gridColumn: "1 / -1" }}>
              <TextRow label="Claim / frase distintiva" hint="Una frase breve che ti descrive (es. 'Caffè e brunch dal 1990')." value={form.claim} onChange={(v) => set("claim", v)} />
            </Box>
          </Box>
        </Section>

        <Section id="descrizione" title="📝 Descrizione" desc="Racconta la tua attività." openId={openId} setOpenId={setOpenId}>
          <Stack spacing={2}>
            <TextRow label="Descrizione breve" multiline minRows={2} hint="1-2 frasi che riassumono l'attività: compaiono in evidenza sul profilo." value={form.short_desc} onChange={(v) => set("short_desc", v)} />
            <TextRow label="Descrizione lunga" multiline minRows={4} hint="Descrizione estesa: storia, atmosfera, specialità, a chi ti rivolgi." value={form.long_desc} onChange={(v) => set("long_desc", v)} />
          </Stack>
        </Section>

        <Section id="posizione" title="📌 Posizione e contatti" desc="Indirizzo e recapiti pubblici." openId={openId} setOpenId={setOpenId}>
          <Box sx={SECTIONS_GRID}>
            <Box sx={{ gridColumn: "1 / -1" }}>
              <TextRow label="Indirizzo" hint="Via e numero civico (es. Via Roma 12)." value={form.address} onChange={(v) => set("address", v)} />
            </Box>
            <TextRow label="Comune" hint="La città in cui si trova l'attività." value={form.city} onChange={(v) => set("city", v)} />
            <TextRow label="Provincia" hint="Sigla della provincia (es. RM, MI, NA)." value={form.province} onChange={(v) => set("province", v)} />
            <TextRow label="CAP" hint="Codice di avviamento postale (5 cifre)." value={form.cap} onChange={(v) => set("cap", v)} />
            <TextRow label="Telefono" hint="Numero pubblico mostrato ai clienti sul profilo." value={form.phone} onChange={(v) => set("phone", v)} />
            <TextRow label="Email pubblica" hint="Email visibile ai clienti (può differire da quella della candidatura)." value={form.public_email} onChange={(v) => set("public_email", v)} />
            <TextRow label="Sito web" hint="URL completo del sito (es. https://iltuolocale.it)." value={form.website} onChange={(v) => set("website", v)} />
            <TextRow label="Instagram" hint="Solo il nome utente, senza @ (es. iltuolocale)." value={form.instagram} onChange={(v) => set("instagram", v)} />
            <TextRow label="WhatsApp" hint="Numero WhatsApp con prefisso (es. +39 333 1234567)." value={form.whatsapp} onChange={(v) => set("whatsapp", v)} />
          </Box>
        </Section>

        <Section id="orari" title="🕒 Orari" desc="Apertura per giorno, anche con pausa." openId={openId} setOpenId={setOpenId}>
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="body2" color="text.secondary">Lascia vuoto un giorno = chiuso. Usa due fasce per la pausa (es. mattina 08:00-13:00, pomeriggio 14:00-18:00).</Typography>
            <HintIcon hint="Formato consigliato HH:MM-HH:MM. La seconda fascia serve se chiudi a pranzo." />
          </Stack>
          <Stack spacing={1}>
            {DAYS.map((d) => (
              <Stack key={d} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                <Typography sx={{ width: 44, fontWeight: 600 }}>{d}</Typography>
                <TextField size="small" placeholder="Mattina (es. 08:00-13:00)" fullWidth
                  value={form.hours[d]?.m || ""} onChange={(e) => setHour(d, "m", e.target.value)} />
                <TextField size="small" placeholder="Pomeriggio (es. 14:00-18:00)" fullWidth
                  value={form.hours[d]?.p || ""} onChange={(e) => setHour(d, "p", e.target.value)} />
              </Stack>
            ))}
          </Stack>
        </Section>

        <Section id="servizi" title="🛎️ Servizi" desc="Cosa offri ai clienti." openId={openId} setOpenId={setOpenId}>
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="body2" color="text.secondary">Clicca per selezionare i servizi disponibili.</Typography>
            <HintIcon hint="Aiutano i clienti a capire subito cosa offri (compaiono come tag sul profilo)." />
          </Stack>
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {SERVICES.map((s) => {
              const on = form.services?.includes(s);
              return <Chip key={s} label={s} color={on ? "primary" : "default"} variant={on ? "filled" : "outlined"}
                onClick={() => set("services", on ? form.services.filter((x) => x !== s) : [...(form.services || []), s])} />;
            })}
          </Stack>
        </Section>

        <Section id="acqua" title="💧 Informazioni acqua" desc="Il cuore di AcquaMap." openId={openId} setOpenId={setOpenId}>
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="body2" color="text.secondary">Attiva le opzioni che descrivono l'acqua che offri.</Typography>
            <HintIcon hint="Queste voci sbloccano il badge Water Experience e migliorano la visibilità." />
          </Stack>
          <Box sx={SECTIONS_GRID}>
            {WATER.map(([k, l]) => (
              <FormControlLabel key={k} control={<Switch checked={!!form.water?.[k]} onChange={(e) => setWater(k, e.target.checked)} />} label={l} />
            ))}
          </Box>
          <Box sx={{ mt: 1 }}>
            <TextRow label="Note sull'acqua" multiline minRows={2} hint="Dettagli utili: tipo di filtrazione, marca dell'erogatore, fonte, ecc." value={form.water_notes} onChange={(v) => set("water_notes", v)} />
          </Box>
        </Section>

        <Section id="media" title="🖼️ Media" desc="Logo e copertina." openId={openId} setOpenId={setOpenId}>
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="body2" color="text.secondary">Immagini di qualità migliorano molto il profilo.</Typography>
            <HintIcon hint="Logo: immagine quadrata. Copertina: foto orizzontale (16:9). Entrambe vengono ritagliate." />
          </Stack>
          <Stack spacing={2} direction={{ xs: "column", sm: "row" }}>
            <ImageCropField label="Logo (quadrato)" value={form.logo_url} onChange={(v) => set("logo_url", v)} aspect={1} round />
            <ImageCropField label="Copertina (16:9)" value={form.cover_image_url} onChange={(v) => set("cover_image_url", v)} aspect={16 / 9} maxSize={1280} />
          </Stack>
        </Section>

        <Stack direction="row" spacing={2} sx={{ mt: 3 }}>
          <Button variant="outlined" disabled={saving} onClick={() => save(false)}>Salva bozza</Button>
          <Button variant="contained" disabled={saving} onClick={() => save(true)}>Invia per revisione</Button>
        </Stack>
      </Container>
    </Box>
  );
}
