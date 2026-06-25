import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Box, Container, Card, CardContent, Typography, TextField, MenuItem, Switch,
  FormControlLabel, Button, Accordion, AccordionSummary, AccordionDetails, Stack,
  LinearProgress, CircularProgress, Alert, Chip,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { toast } from "sonner";
import PublicTopbar from "../components/PublicTopbar.jsx";
import ImageCropField from "../components/ImageCropField.jsx";
import { api } from "../lib/api.js";
import { CATEGORIES, catLabel } from "../lib/constants.js";

const DAYS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const SERVICES = ["Wi-Fi", "Prenotazione", "Tavoli esterni", "Accessibile", "Pet friendly", "Take away", "Delivery", "Adatto famiglie", "Adatto lavoro/studio"];
const WATER = [
  ["water_natural", "Acqua naturale"], ["water_sparkling", "Acqua frizzante"],
  ["water_microfiltered", "Microfiltrata"], ["water_purified", "Depurata"],
  ["water_glass", "Servita in vetro"], ["water_refill", "Refill disponibile"],
  ["water_bottles", "Accetta borracce"], ["water_plasticfree", "Plastic free friendly"],
];

export default function OnboardingPage() {
  const { token } = useParams();
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState("identita");

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
          hours: p.extra?.hours || {}, services: p.extra?.services || [], water: p.extra?.water || {},
          water_notes: p.extra?.water_notes || "",
        });
      } catch (e) { setErr(e.message || "Link non valido o scaduto."); }
      finally { setLoading(false); }
    })();
  }, [token]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setWater = (k, v) => setForm((f) => ({ ...f, water: { ...f.water, [k]: v } }));

  const completeness = useMemo(() => {
    if (!form) return 0;
    const checks = [
      form.business_name, form.category, form.address, form.city, form.phone,
      form.short_desc, form.long_desc, Object.keys(form.hours || {}).length, form.services?.length,
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
      } else toast.success("Bozza salvata");
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  if (loading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;
  if (err) return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}><PublicTopbar />
      <Container maxWidth="sm" sx={{ py: 8 }}><Alert severity="error" sx={{ borderRadius: 3 }}>{err}</Alert></Container></Box>
  );

  const Section = ({ id, title, desc, children }) => (
    <Accordion expanded={open === id} onChange={() => setOpen(open === id ? "" : id)} disableGutters elevation={0}
      sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, mb: 1.5, "&:before": { display: "none" }, overflow: "hidden" }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box><Typography sx={{ fontWeight: 700 }}>{title}</Typography>
          <Typography variant="body2" color="text.secondary">{desc}</Typography></Box>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
  const grid = { display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 };

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <PublicTopbar />
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Typography variant="h4" gutterBottom>Completa il profilo</Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>Compila i dati pubblici della tua attività. Verranno revisionati prima della pubblicazione.</Typography>
        <Stack direction="row" justifyContent="space-between"><Typography variant="body2">Completezza</Typography><Typography variant="body2">{completeness}%</Typography></Stack>
        <LinearProgress variant="determinate" value={completeness} sx={{ borderRadius: 2, mb: 3 }} />

        <Section id="identita" title="🏪 Identità attività" desc="Nome, categoria, claim.">
          <Box sx={grid}>
            <TextField label="Nome commerciale" value={form.business_name} onChange={(e) => set("business_name", e.target.value)} size="small" />
            <TextField select label="Categoria" value={form.category} onChange={(e) => set("category", e.target.value)} size="small">
              {CATEGORIES.map((c) => <MenuItem key={c.v} value={c.v}>{c.l}</MenuItem>)}
            </TextField>
            <Box sx={{ gridColumn: "1 / -1" }}><TextField fullWidth label="Claim / frase distintiva" value={form.claim} onChange={(e) => set("claim", e.target.value)} size="small" /></Box>
          </Box>
        </Section>

        <Section id="descrizione" title="📝 Descrizione" desc="Racconta la tua attività.">
          <Stack spacing={2}>
            <TextField label="Descrizione breve" value={form.short_desc} onChange={(e) => set("short_desc", e.target.value)} size="small" multiline minRows={2} />
            <TextField label="Descrizione lunga" value={form.long_desc} onChange={(e) => set("long_desc", e.target.value)} size="small" multiline minRows={4} />
          </Stack>
        </Section>

        <Section id="posizione" title="📌 Posizione" desc="Indirizzo e contatti.">
          <Box sx={grid}>
            <Box sx={{ gridColumn: "1 / -1" }}><TextField fullWidth label="Indirizzo" value={form.address} onChange={(e) => set("address", e.target.value)} size="small" /></Box>
            <TextField label="Comune" value={form.city} onChange={(e) => set("city", e.target.value)} size="small" />
            <TextField label="Provincia" value={form.province} onChange={(e) => set("province", e.target.value)} size="small" />
            <TextField label="CAP" value={form.cap} onChange={(e) => set("cap", e.target.value)} size="small" />
            <TextField label="Telefono" value={form.phone} onChange={(e) => set("phone", e.target.value)} size="small" />
            <TextField label="Email pubblica" value={form.public_email} onChange={(e) => set("public_email", e.target.value)} size="small" />
            <TextField label="Sito web" value={form.website} onChange={(e) => set("website", e.target.value)} size="small" />
            <TextField label="Instagram" value={form.instagram} onChange={(e) => set("instagram", e.target.value)} size="small" />
            <TextField label="WhatsApp" value={form.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} size="small" />
          </Box>
        </Section>

        <Section id="orari" title="🕒 Orari" desc="Apertura per giorno.">
          <Stack spacing={1}>
            {DAYS.map((d) => (
              <Stack key={d} direction="row" spacing={1} alignItems="center">
                <Typography sx={{ width: 44 }}>{d}</Typography>
                <TextField placeholder="es. 08:00-20:00 (vuoto = chiuso)" size="small" fullWidth
                  value={form.hours?.[d] || ""} onChange={(e) => set("hours", { ...form.hours, [d]: e.target.value })} />
              </Stack>
            ))}
          </Stack>
        </Section>

        <Section id="servizi" title="🛎️ Servizi" desc="Cosa offri.">
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {SERVICES.map((s) => {
              const on = form.services?.includes(s);
              return <Chip key={s} label={s} color={on ? "primary" : "default"} variant={on ? "filled" : "outlined"}
                onClick={() => set("services", on ? form.services.filter((x) => x !== s) : [...(form.services || []), s])} />;
            })}
          </Stack>
        </Section>

        <Section id="acqua" title="💧 Informazioni acqua" desc="Il cuore di AcquaMap.">
          <Box sx={grid}>
            {WATER.map(([k, l]) => (
              <FormControlLabel key={k} control={<Switch checked={!!form.water?.[k]} onChange={(e) => setWater(k, e.target.checked)} />} label={l} />
            ))}
          </Box>
          <TextField sx={{ mt: 1 }} fullWidth label="Note sull'acqua" value={form.water_notes} onChange={(e) => set("water_notes", e.target.value)} size="small" multiline minRows={2} />
        </Section>

        <Section id="media" title="🖼️ Media" desc="Logo e copertina.">
          <Stack spacing={2} direction={{ xs: "column", sm: "row" }}>
            <ImageCropField label="Logo" value={form.logo_url} onChange={(v) => set("logo_url", v)} aspect={1} round />
            <ImageCropField label="Copertina" value={form.cover_image_url} onChange={(v) => set("cover_image_url", v)} aspect={16 / 9} maxSize={1280} />
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
