import React, { useMemo, useState } from "react";
import { useForm, Controller } from "react-hook-form";
import {
  Box, Container, Typography, Button, Accordion, AccordionSummary, AccordionDetails,
  TextField, MenuItem, Switch, FormControlLabel, Chip, Stack, Card, CardContent,
  Checkbox, Alert, CircularProgress, LinearProgress,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import { motion } from "framer-motion";
import { toast } from "sonner";
import PublicTopbar from "../components/PublicTopbar.jsx";
import PrivacyModal from "../components/PrivacyModal.jsx";
import { api } from "../lib/api.js";
import { CATEGORIES, REFERENT_ROLES, COLLAB_INTERESTS } from "../lib/constants.js";

const VANTAGGI = [
  { icon: "📍", t: "Profilo su AcquaMap", d: "Una scheda dedicata con informazioni, foto, servizi e contatti." },
  { icon: "✅", t: "Badge verificati", d: "Valorizza qualità, attenzione all'acqua e sostenibilità." },
  { icon: "🔍", t: "Visibilità locale", d: "Aiuta gli utenti a trovare attività attente all'acqua e plastic free." },
  { icon: "📊", t: "Dashboard Business", d: "Statistiche, interazioni e strumenti di gestione dedicati." },
  { icon: "🧪", t: "Funzionalità future", d: "Analisi acqua, report avanzati e strumenti di promozione." },
];

// Definizione sezioni e campi (rendering generico).
const SECTIONS = [
  {
    id: "attivita", icon: "🏪", title: "Dati attività", desc: "Nome, categoria e informazioni principali.",
    fields: [
      { name: "business_name", label: "Nome attività", required: true },
      { name: "category", label: "Categoria", type: "select", options: CATEGORIES, required: true, half: true },
      { name: "tipologia", label: "Tipologia locale", half: true },
      { name: "vat", label: "P.IVA / Codice fiscale", half: true },
      { name: "short_desc", label: "Breve descrizione", type: "textarea" },
    ],
  },
  {
    id: "posizione", icon: "📌", title: "Posizione e contatti", desc: "Dove siete e come trovarvi.",
    fields: [
      { name: "address", label: "Indirizzo completo", required: true },
      { name: "city", label: "Comune", required: true, half: true },
      { name: "province", label: "Provincia", half: true },
      { name: "cap", label: "CAP", half: true },
      { name: "maps_url", label: "Google Maps URL", half: true },
      { name: "website", label: "Sito web", half: true },
      { name: "instagram", label: "Instagram", half: true },
      { name: "public_phone", label: "Telefono pubblico", type: "tel", half: true },
      { name: "public_email", label: "Email pubblica", type: "email", half: true },
    ],
  },
  {
    id: "referente", icon: "👤", title: "Referente", desc: "Chi gestisce la candidatura.",
    fields: [
      { name: "contact_name", label: "Nome e cognome referente", required: true, half: true },
      { name: "contact_role", label: "Ruolo", type: "select", options: REFERENT_ROLES.map((r) => ({ v: r, l: r })), half: true },
      { name: "contact_phone", label: "Telefono referente", type: "tel", half: true },
      { name: "contact_email", label: "Email referente", type: "email", required: true, half: true },
    ],
  },
  {
    id: "acqua", icon: "💧", title: "Informazioni sull'acqua", desc: "Cosa offrite ai clienti.",
    fields: [
      { name: "water_natural", label: "Acqua naturale", type: "switch", half: true },
      { name: "water_sparkling", label: "Acqua frizzante", type: "switch", half: true },
      { name: "water_filtered", label: "Filtrazione/depurazione", type: "switch", half: true },
      { name: "water_glass", label: "Servita in vetro", type: "switch", half: true },
      { name: "water_bottles", label: "Accettate borracce", type: "switch", half: true },
      { name: "water_refill", label: "Punto refill", type: "switch", half: true },
      { name: "water_analysis", label: "Avete analisi acqua", type: "switch", half: true },
      { name: "water_notes", label: "Note sull'acqua", type: "textarea" },
    ],
  },
  {
    id: "obiettivi", icon: "🎯", title: "Obiettivi collaborazione", desc: "Perché entrare in AcquaMap.",
    fields: [
      { name: "goal_why", label: "Perché vuoi entrare in AcquaMap Business?", type: "textarea" },
      { name: "interests", label: "Cosa ti interessa di più?", type: "chips", options: COLLAB_INTERESTS },
      { name: "available_profile", label: "Disponibile a completare il profilo con foto e info", type: "switch", half: true },
      { name: "available_contact", label: "Disponibile a essere contattato dal team", type: "switch", half: true },
      { name: "extra_notes", label: "Note aggiuntive", type: "textarea" },
    ],
  },
];

const REQUIRED = ["business_name", "category", "address", "city", "contact_name", "contact_email"];

export default function ApplyPage() {
  const { register, handleSubmit, control, watch, setValue, formState: { errors } } = useForm({
    defaultValues: { category: "", contact_role: "", interests: [] },
    mode: "onChange",
  });
  const [open, setOpen] = useState("attivita");
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [consents, setConsents] = useState({ privacy: false, commercial: false, publish: false, expand: false, truth: false });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);

  const values = watch();

  const sectionComplete = (s) =>
    s.fields.filter((f) => f.required).every((f) => values[f.name]) &&
    s.fields.some((f) => values[f.name]);

  const overall = useMemo(() => {
    const total = REQUIRED.length + 1; // + privacy
    const filled = REQUIRED.filter((k) => values[k]).length + (consents.privacy ? 1 : 0);
    return Math.round((filled / total) * 100);
  }, [values, consents.privacy]);

  const emailValid = (e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e || "");

  const onSubmit = async (data) => {
    if (!consents.privacy) { toast.error("Devi accettare il trattamento dei dati."); return; }
    if (!consents.expand) { toast.error("Devi accettare il programma Business Expand."); return; }
    if (!emailValid(data.contact_email)) { toast.error("Email referente non valida."); return; }
    setSubmitting(true);
    try {
      const payload = {
        ...data,
        wants_expand_program: true,
        privacy_accepted: consents.privacy,
        consent_commercial: consents.commercial,
        consent_publish: consents.publish,
        consent_truth: consents.truth,
      };
      const res = await api("/api/business/apply", { method: "POST", body: payload, auth: false });
      setDone(res);
      toast.success("Candidatura inviata!");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      toast.error(e.message || "Errore durante l'invio.");
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
        <PublicTopbar />
        <Container maxWidth="sm" sx={{ py: 8, textAlign: "center" }}>
          <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
            <Typography sx={{ fontSize: 64 }}>✅</Typography>
            <Typography variant="h4" gutterBottom>Candidatura inviata!</Typography>
            <Typography color="text.secondary">
              Grazie. Il team AcquaMap esaminerà la richiesta e ti contatterà via email.
            </Typography>
            <Alert severity="success" sx={{ mt: 3, borderRadius: 3, justifyContent: "center" }}>
              Codice richiesta: <b>{done.application_id}</b>
            </Alert>
            <Button href="/" variant="outlined" sx={{ mt: 3 }}>Torna alla mappa</Button>
          </motion.div>
        </Container>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <PublicTopbar cta={<Button variant="contained" href="#form">Candidati</Button>} />

      {/* HERO */}
      <Box sx={{ background: "radial-gradient(1100px 480px at 50% -10%, rgba(27,178,189,.18), transparent 70%)", py: { xs: 6, md: 9 }, textAlign: "center" }}>
        <Container maxWidth="md">
          <motion.div initial={{ y: 18, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.5 }}>
            <Chip label="AcquaMap Business Expand Program" color="primary" sx={{ mb: 2, fontWeight: 700 }} />
            <Typography variant="h3" sx={{ fontWeight: 800, letterSpacing: "-0.03em", mb: 2 }}>
              Entra in AcquaMap Business
            </Typography>
            <Typography variant="h6" color="text.secondary" sx={{ fontWeight: 400, maxWidth: 620, mx: "auto" }}>
              Porta la tua attività dentro AcquaMap e rendila visibile a chi cerca qualità dell'acqua,
              refill e locali plastic free. Il programma Expand è gratuito per le prime attività selezionate.
            </Typography>
          </motion.div>
        </Container>
      </Box>

      {/* VANTAGGI */}
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "repeat(5,1fr)" }, gap: 2 }}>
          {VANTAGGI.map((v) => (
            <Card key={v.t}>
              <CardContent>
                <Typography sx={{ fontSize: 30 }}>{v.icon}</Typography>
                <Typography sx={{ fontWeight: 700, mt: 1 }}>{v.t}</Typography>
                <Typography variant="body2" color="text.secondary">{v.d}</Typography>
              </CardContent>
            </Card>
          ))}
        </Box>
      </Container>

      {/* FORM */}
      <Container maxWidth="md" sx={{ pb: 10 }} id="form">
        <Card>
          <CardContent sx={{ p: { xs: 2, md: 4 } }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="h5">Candidatura</Typography>
              <Typography variant="body2" color="text.secondary">{overall}% completata</Typography>
            </Stack>
            <LinearProgress variant="determinate" value={overall} sx={{ borderRadius: 2, mb: 3 }} />

            <form onSubmit={handleSubmit(onSubmit)}>
              {SECTIONS.map((s) => (
                <Accordion key={s.id} expanded={open === s.id} onChange={() => setOpen(open === s.id ? "" : s.id)}
                  disableGutters elevation={0}
                  sx={{ border: "1px solid", borderColor: "divider", borderRadius: 3, mb: 1.5, "&:before": { display: "none" }, overflow: "hidden" }}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flex: 1 }}>
                      {sectionComplete(s)
                        ? <CheckCircleIcon color="success" />
                        : <RadioButtonUncheckedIcon color="disabled" />}
                      <Box>
                        <Typography sx={{ fontWeight: 700 }}>{s.icon} {s.title}</Typography>
                        <Typography variant="body2" color="text.secondary">{s.desc}</Typography>
                      </Box>
                    </Stack>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>
                      {s.fields.map((f) => (
                        <Box key={f.name} sx={{ gridColumn: f.half ? "auto" : "1 / -1" }}>
                          {renderField(f, { register, control, errors })}
                        </Box>
                      ))}
                    </Box>
                  </AccordionDetails>
                </Accordion>
              ))}

              {/* CONSENSI */}
              <Box sx={{ mt: 3 }}>
                <Typography variant="h6" gutterBottom>Consensi e privacy</Typography>
                <Stack spacing={0.5}>
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <Checkbox checked={consents.privacy} disabled readOnly />
                    <Typography variant="body2" sx={{ flex: 1 }}>
                      Trattamento dei dati personali {consents.privacy && <b style={{ color: "#16a34a" }}>— Accettato ✓</b>}
                    </Typography>
                    {!consents.privacy && (
                      <Button size="small" onClick={() => setPrivacyOpen(true)}>Leggi e accetta</Button>
                    )}
                  </Stack>
                  {[
                    ["expand", "Accetto di aderire al programma AcquaMap Business Expand"],
                    ["publish", "Consenso alla pubblicazione dei dati pubblici dell'attività"],
                    ["commercial", "Consenso al contatto commerciale (facoltativo)"],
                    ["truth", "Confermo la veridicità dei dati inseriti"],
                  ].map(([k, label]) => (
                    <FormControlLabel key={k}
                      control={<Checkbox checked={consents[k]} onChange={(e) => setConsents((c) => ({ ...c, [k]: e.target.checked }))} />}
                      label={<Typography variant="body2">{label}</Typography>} />
                  ))}
                </Stack>
              </Box>

              <Button type="submit" variant="contained" size="large" disabled={submitting}
                sx={{ mt: 3 }} startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}>
                {submitting ? "Invio…" : "Invia candidatura"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </Container>

      <PrivacyModal open={privacyOpen} onClose={() => setPrivacyOpen(false)}
        onAccept={() => setConsents((c) => ({ ...c, privacy: true }))} />
    </Box>
  );
}

function renderField(f, { register, control, errors }) {
  if (f.type === "switch") {
    return (
      <Controller name={f.name} control={control} defaultValue={false}
        render={({ field }) => (
          <FormControlLabel control={<Switch checked={!!field.value} onChange={(e) => field.onChange(e.target.checked)} />} label={f.label} />
        )} />
    );
  }
  if (f.type === "select") {
    return (
      <Controller name={f.name} control={control} defaultValue=""
        rules={f.required ? { required: true } : {}}
        render={({ field }) => (
          <TextField select fullWidth size="small" label={f.label} required={f.required}
            error={!!errors[f.name]} {...field}>
            {f.options.map((o) => <MenuItem key={o.v} value={o.v}>{o.l}</MenuItem>)}
          </TextField>
        )} />
    );
  }
  if (f.type === "chips") {
    return (
      <Controller name={f.name} control={control} defaultValue={[]}
        render={({ field }) => (
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{f.label}</Typography>
            <Stack direction="row" flexWrap="wrap" gap={1}>
              {f.options.map((o) => {
                const sel = (field.value || []).includes(o);
                return (
                  <Chip key={o} label={o} variant={sel ? "filled" : "outlined"} color={sel ? "primary" : "default"}
                    onClick={() => field.onChange(sel ? field.value.filter((x) => x !== o) : [...(field.value || []), o])} />
                );
              })}
            </Stack>
          </Box>
        )} />
    );
  }
  return (
    <TextField fullWidth size="small" label={f.label} required={f.required}
      type={f.type === "textarea" ? "text" : f.type || "text"}
      multiline={f.type === "textarea"} minRows={f.type === "textarea" ? 2 : undefined}
      error={!!errors[f.name]}
      {...register(f.name, f.required ? { required: true } : {})} />
  );
}
