import React, { useState } from "react";
import {
  Box, Card, CardContent, Typography, Stack, Chip, Button, TextField, Switch,
  FormControlLabel, CircularProgress, Alert, LinearProgress, Divider,
} from "@mui/material";
import SpaceDashboardIcon from "@mui/icons-material/SpaceDashboard";
import StorefrontIcon from "@mui/icons-material/Storefront";
import VerifiedIcon from "@mui/icons-material/Verified";
import InsightsIcon from "@mui/icons-material/Insights";
import LockIcon from "@mui/icons-material/Lock";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../lib/auth.jsx";
import { supabase } from "../lib/supabase.js";
import ConsoleShell from "../components/ConsoleShell.jsx";
import LoginCard from "../components/LoginCard.jsx";
import { api } from "../lib/api.js";
import { BADGES, badgeMeta, PROFILE_STATUSES } from "../lib/constants.js";

export default function BusinessPage() {
  const { user, loading, signOut } = useAuth();
  const qc = useQueryClient();
  const [nav, setNav] = useState("overview");

  const meQ = useQuery({ queryKey: ["me"], queryFn: () => api("/api/business/me"), enabled: !!user });

  if (loading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;
  if (!user) return <LoginCard title="Dashboard attività" subtitle="Accedi con l'email della tua attività." allowSignup />;
  if (meQ.isLoading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;
  if (meQ.error?.status === 404) return <LoginCard title="Nessuna attività" subtitle={`Nessun profilo collegato a ${user.email}. Contatta AcquaMap.`} />;

  const me = meQ.data || {};
  const nav_ = [
    { key: "overview", label: "Overview", icon: <SpaceDashboardIcon /> },
    { key: "analytics", label: "Analytics", icon: <InsightsIcon /> },
    { key: "profilo", label: "Profilo", icon: <StorefrontIcon /> },
    { key: "badge", label: "Badge", icon: <VerifiedIcon /> },
    { key: "sicurezza", label: "Sicurezza", icon: <LockIcon /> },
  ];
  const refetch = () => qc.invalidateQueries({ queryKey: ["me"] });

  return (
    <ConsoleShell title="La tua attività" subtitle="Business" nav={nav_} active={nav} onNav={setNav} onSignOut={signOut}>
      {nav === "overview" && <Overview me={me} />}
      {nav === "analytics" && <ComingSoon title="Analytics" text="Visualizzazioni, click e andamenti saranno disponibili a breve." />}
      {nav === "profilo" && <ProfileEditor me={me} onSaved={refetch} />}
      {nav === "badge" && <BadgePanel me={me} />}
      {nav === "sicurezza" && <Security />}
    </ConsoleShell>
  );
}

function Overview({ me }) {
  const completeness = me.completeness ?? 60;
  return (
    <Stack spacing={2}>
      <Card><CardContent>
        <Stack direction="row" spacing={2} alignItems="center">
          <Box sx={{ width: 64, height: 64, borderRadius: 3, overflow: "hidden", bgcolor: "background.default", display: "grid", placeItems: "center", fontSize: 30 }}>
            {me.logo_url ? <Box component="img" src={me.logo_url} sx={{ width: "100%", height: "100%", objectFit: "cover" }} /> : "🏪"}
          </Box>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6">{me.business_name}</Typography>
            <Chip size="small" label={PROFILE_STATUSES[me.status] || me.status} color={me.status === "published" ? "success" : "default"} />
          </Box>
        </Stack>
        <Box sx={{ mt: 2 }}>
          <Stack direction="row" justifyContent="space-between"><Typography variant="body2">Completezza profilo</Typography><Typography variant="body2">{completeness}%</Typography></Stack>
          <LinearProgress variant="determinate" value={completeness} sx={{ borderRadius: 2, mt: 0.5 }} />
        </Box>
      </CardContent></Card>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4,1fr)" }, gap: 2 }}>
        {[["Visualizzazioni", "—"], ["Click contatti", "—"], ["Aperture mappa", "—"], ["Badge attivi", (me.badges || []).length]].map(([l, n]) => (
          <Card key={l}><CardContent><Typography variant="h5" sx={{ fontWeight: 800 }}>{n}</Typography><Typography variant="body2" color="text.secondary">{l}</Typography></CardContent></Card>
        ))}
      </Box>

      <Card><CardContent>
        <Typography variant="subtitle1" gutterBottom>Suggerimenti</Typography>
        <Stack spacing={1}>
          {!me.logo_url && <Alert severity="info" sx={{ borderRadius: 3 }}>Aggiungi un logo per migliorare il profilo.</Alert>}
          {(me.badges || []).length === 0 && <Alert severity="info" sx={{ borderRadius: 3 }}>Completa le info acqua per ottenere il badge Water Experience.</Alert>}
          <Alert severity="success" sx={{ borderRadius: 3 }}>Aggiungi almeno 3 foto per valorizzare l'attività.</Alert>
        </Stack>
      </CardContent></Card>
    </Stack>
  );
}

function ProfileEditor({ me, onSaved }) {
  const [f, setF] = useState({
    description: me.description || "", phone: me.phone || "", public_email: me.public_email || "",
    website: me.website || "", instagram: me.instagram || "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const save = async () => {
    setBusy(true);
    try { await api("/api/business/me", { method: "PATCH", body: f }); toast.success("Profilo aggiornato"); onSaved(); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Card><CardContent sx={{ p: { xs: 2, md: 3 } }}>
      <Typography variant="h6" gutterBottom>Modifica profilo</Typography>
      <Stack spacing={2} sx={{ maxWidth: 560 }}>
        <TextField label="Descrizione" value={f.description} onChange={(e) => set("description", e.target.value)} multiline minRows={3} size="small" />
        <TextField label="Telefono" value={f.phone} onChange={(e) => set("phone", e.target.value)} size="small" />
        <TextField label="Email pubblica" value={f.public_email} onChange={(e) => set("public_email", e.target.value)} size="small" />
        <TextField label="Sito web" value={f.website} onChange={(e) => set("website", e.target.value)} size="small" />
        <TextField label="Instagram" value={f.instagram} onChange={(e) => set("instagram", e.target.value)} size="small" />
        <Button variant="contained" disabled={busy} onClick={save} sx={{ alignSelf: "flex-start" }}>Salva</Button>
      </Stack>
    </CardContent></Card>
  );
}

function BadgePanel({ me }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
      {BADGES.map((b) => {
        const on = (me.badges || []).includes(b.key);
        return (
          <Card key={b.key}><CardContent>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography sx={{ fontSize: 26 }}>{b.icon}</Typography>
              <Typography sx={{ fontWeight: 700, flex: 1 }}>{b.label}</Typography>
              <Chip size="small" label={on ? "Attivo" : "Non attivo"} color={on ? "success" : "default"} />
            </Stack>
          </CardContent></Card>
        );
      })}
    </Box>
  );
}

function Security() {
  const [pw, setPw] = useState(""); const [pin, setPin] = useState(""); const [busy, setBusy] = useState(false);
  const changePw = async () => {
    if (pw.length < 8) return toast.error("Min 8 caratteri.");
    setBusy(true);
    try { const { error } = await supabase.auth.updateUser({ password: pw }); if (error) throw new Error(error.message); toast.success("Password aggiornata"); setPw(""); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const changePin = async () => {
    if (!/^\d{4,6}$/.test(pin)) return toast.error("PIN 4-6 cifre.");
    setBusy(true);
    try { await api("/api/business/me/pin", { method: "POST", body: { pin } }); toast.success("PIN aggiornato"); setPin(""); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Card><CardContent sx={{ p: { xs: 2, md: 3 } }}>
      <Typography variant="h6" gutterBottom>Sicurezza</Typography>
      <Stack spacing={2} sx={{ maxWidth: 420 }}>
        <TextField label="Nuova password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} size="small" />
        <Button variant="outlined" disabled={busy} onClick={changePw} sx={{ alignSelf: "flex-start" }}>Cambia password</Button>
        <Divider />
        <TextField label="Nuovo PIN (4-6 cifre)" type="password" value={pin} onChange={(e) => setPin(e.target.value)} size="small" inputProps={{ inputMode: "numeric" }} />
        <Button variant="outlined" disabled={busy} onClick={changePin} sx={{ alignSelf: "flex-start" }}>Imposta PIN</Button>
      </Stack>
    </CardContent></Card>
  );
}

function ComingSoon({ title, text }) {
  return <Card><CardContent sx={{ textAlign: "center", py: 6 }}>
    <Typography variant="h6">{title}</Typography>
    <Typography color="text.secondary">{text}</Typography>
  </CardContent></Card>;
}
