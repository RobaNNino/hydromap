import React, { useState } from "react";
import {
  Box, Card, CardContent, Typography, Stack, Chip, Button, TextField,
  CircularProgress, Alert, LinearProgress, Divider, List, ListItem, ListItemText,
} from "@mui/material";
import SpaceDashboardIcon from "@mui/icons-material/SpaceDashboard";
import StorefrontIcon from "@mui/icons-material/Storefront";
import VerifiedIcon from "@mui/icons-material/Verified";
import InsightsIcon from "@mui/icons-material/Insights";
import LockIcon from "@mui/icons-material/Lock";
import EditNoteIcon from "@mui/icons-material/EditNote";
import ChatIcon from "@mui/icons-material/Chat";
import NotificationsIcon from "@mui/icons-material/Notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../lib/auth.jsx";
import { supabase } from "../lib/supabase.js";
import ConsoleShell from "../components/ConsoleShell.jsx";
import LoginCard from "../components/LoginCard.jsx";
import AnalyticsView from "../components/AnalyticsView.jsx";
import { api } from "../lib/api.js";
import { BADGES, PROFILE_STATUSES, computeCompleteness, computeTrust } from "../lib/constants.js";

export default function BusinessPage() {
  const { user, loading, signOut } = useAuth();
  const qc = useQueryClient();
  const [nav, setNav] = useState("overview");
  const meQ = useQuery({ queryKey: ["me"], queryFn: () => api("/api/business/me"), enabled: !!user });

  if (loading) return <Centered><CircularProgress /></Centered>;
  if (!user) return <LoginCard title="Dashboard attività" subtitle="Accedi con l'email della tua attività." allowSignup />;
  if (meQ.isLoading) return <Centered><CircularProgress /></Centered>;
  if (meQ.error?.status === 404) return <LoginCard title="Nessuna attività" subtitle={`Nessun profilo collegato a ${user.email}.`} />;

  const me = meQ.data || {};
  const nav_ = [
    { key: "overview", label: "Overview", icon: <SpaceDashboardIcon /> },
    { key: "analytics", label: "Analytics", icon: <InsightsIcon /> },
    { key: "profilo", label: "Profilo", icon: <StorefrontIcon /> },
    { key: "modifiche", label: "Modifiche", icon: <EditNoteIcon /> },
    { key: "messaggi", label: "Messaggi", icon: <ChatIcon /> },
    { key: "notifiche", label: "Notifiche", icon: <NotificationsIcon /> },
    { key: "badge", label: "Badge", icon: <VerifiedIcon /> },
    { key: "sicurezza", label: "Sicurezza", icon: <LockIcon /> },
  ];
  const refetch = () => qc.invalidateQueries({ queryKey: ["me"] });

  return (
    <ConsoleShell title="La tua attività" subtitle="Business" nav={nav_} active={nav} onNav={setNav} onSignOut={signOut}>
      {nav === "overview" && <Overview me={me} go={setNav} />}
      {nav === "analytics" && <AnalyticsView fetchPath="/api/business/me/analytics" queryKey={["me-analytics"]} />}
      {nav === "profilo" && <ProfileEditor me={me} onSaved={refetch} />}
      {nav === "modifiche" && <ChangesPanel />}
      {nav === "messaggi" && <MessagesPanel />}
      {nav === "notifiche" && <NotificationsPanel />}
      {nav === "badge" && <BadgePanel me={me} />}
      {nav === "sicurezza" && <Security />}
    </ConsoleShell>
  );
}

const Centered = ({ children }) => <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}>{children}</Box>;

function Overview({ me, go }) {
  const completeness = computeCompleteness(me);
  const trust = computeTrust(me);
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
        <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2, mt: 2 }}>
          <Meter label="Completezza profilo" value={completeness} />
          <Meter label="Trust score" value={trust} />
        </Box>
      </CardContent></Card>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4,1fr)" }, gap: 2 }}>
        {[["Badge attivi", (me.badges || []).length], ["Stato", PROFILE_STATUSES[me.status] || me.status]].map(([l, n]) => (
          <Card key={l}><CardContent><Typography variant="h5" sx={{ fontWeight: 800 }}>{n}</Typography><Typography variant="body2" color="text.secondary">{l}</Typography></CardContent></Card>
        ))}
        <Card sx={{ cursor: "pointer" }} onClick={() => go("analytics")}><CardContent>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>📊</Typography><Typography variant="body2" color="text.secondary">Vedi analytics</Typography></CardContent></Card>
      </Box>

      <Card><CardContent>
        <Typography variant="subtitle1" gutterBottom>Suggerimenti</Typography>
        <Stack spacing={1}>
          {!me.logo_url && <Alert severity="info" sx={{ borderRadius: 3 }}>Aggiungi un logo per migliorare il profilo.</Alert>}
          {!me.cover_image_url && <Alert severity="info" sx={{ borderRadius: 3 }}>Aggiungi una foto di copertina.</Alert>}
          {(me.badges || []).length === 0 && <Alert severity="info" sx={{ borderRadius: 3 }}>Completa le info acqua per ottenere il badge Water Experience.</Alert>}
          {completeness >= 90 && <Alert severity="success" sx={{ borderRadius: 3 }}>Profilo ottimizzato al {completeness}%. Ottimo!</Alert>}
        </Stack>
      </CardContent></Card>
    </Stack>
  );
}

function Meter({ label, value }) {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between"><Typography variant="body2">{label}</Typography><Typography variant="body2" sx={{ fontWeight: 700 }}>{value}%</Typography></Stack>
      <LinearProgress variant="determinate" value={value} sx={{ borderRadius: 2, mt: 0.5, height: 8 }} />
    </Box>
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
    try {
      const r = await api("/api/business/me", { method: "PATCH", body: f });
      if (r.pending_changes?.length) toast.message(`In attesa di approvazione: ${r.pending_changes.join(", ")}`);
      else toast.success("Profilo aggiornato");
      onSaved();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Card><CardContent sx={{ p: { xs: 2, md: 3 } }}>
      <Typography variant="h6" gutterBottom>Modifica profilo</Typography>
      <Alert severity="info" sx={{ borderRadius: 3, mb: 2 }}>Telefono ed email pubblica vengono pubblicati dopo l'approvazione del team.</Alert>
      <Stack spacing={2} sx={{ maxWidth: 560 }}>
        <TextField label="Descrizione" value={f.description} onChange={(e) => set("description", e.target.value)} multiline minRows={3} size="small" />
        <TextField label="Telefono (richiede approvazione)" value={f.phone} onChange={(e) => set("phone", e.target.value)} size="small" />
        <TextField label="Email pubblica (richiede approvazione)" value={f.public_email} onChange={(e) => set("public_email", e.target.value)} size="small" />
        <TextField label="Sito web" value={f.website} onChange={(e) => set("website", e.target.value)} size="small" />
        <TextField label="Instagram" value={f.instagram} onChange={(e) => set("instagram", e.target.value)} size="small" />
        <Button variant="contained" disabled={busy} onClick={save} sx={{ alignSelf: "flex-start" }}>Salva</Button>
      </Stack>
    </CardContent></Card>
  );
}

function ChangesPanel() {
  const q = useQuery({ queryKey: ["me-changes"], queryFn: () => api("/api/business/me/changes") });
  const items = q.data?.items || [];
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Modifiche in attesa</Typography>
      {items.length === 0 ? <Typography color="text.secondary">Nessuna modifica in attesa.</Typography> : (
        <List>{items.map((c) => (
          <ListItem key={c.id} divider>
            <ListItemText primary={`${c.field}: ${c.old_value || "—"} → ${c.new_value || "—"}`}
              secondary={`Stato: ${c.status}${c.admin_notes ? " · " + c.admin_notes : ""}`} />
            <Chip size="small" label={c.status} color={c.status === "approved" ? "success" : c.status === "rejected" ? "error" : "warning"} />
          </ListItem>
        ))}</List>
      )}
    </CardContent></Card>
  );
}

function MessagesPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me-messages"], queryFn: () => api("/api/business/me/messages") });
  const [text, setText] = useState("");
  const send = async () => {
    if (!text.trim()) return;
    try { await api("/api/business/me/messages", { method: "POST", body: { body: text } }); setText(""); qc.invalidateQueries({ queryKey: ["me-messages"] }); }
    catch (e) { toast.error(e.message); }
  };
  const items = q.data?.items || [];
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Messaggi con il team</Typography>
      <Stack spacing={1} sx={{ maxHeight: 360, overflowY: "auto", mb: 2 }}>
        {items.length === 0 && <Typography color="text.secondary">Nessun messaggio.</Typography>}
        {items.map((m) => (
          <Box key={m.id} sx={{ alignSelf: m.sender === "business" ? "flex-end" : "flex-start", maxWidth: "80%",
            bgcolor: m.sender === "business" ? "primary.main" : "background.default",
            color: m.sender === "business" ? "#fff" : "text.primary", px: 1.5, py: 1, borderRadius: 3 }}>
            <Typography variant="body2">{m.body}</Typography>
          </Box>
        ))}
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField fullWidth size="small" placeholder="Scrivi un messaggio…" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
        <Button variant="contained" onClick={send}>Invia</Button>
      </Stack>
    </CardContent></Card>
  );
}

function NotificationsPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me-notif"], queryFn: () => api("/api/business/me/notifications") });
  const items = q.data?.items || [];
  const read = async (id) => { await api(`/api/business/me/notifications/${id}/read`, { method: "POST" }); qc.invalidateQueries({ queryKey: ["me-notif"] }); };
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Notifiche</Typography>
      {items.length === 0 ? <Typography color="text.secondary">Nessuna notifica.</Typography> : (
        <List>{items.map((n) => (
          <ListItem key={n.id} divider secondaryAction={!n.read && <Button size="small" onClick={() => read(n.id)}>Letta</Button>}
            sx={{ opacity: n.read ? 0.6 : 1 }}>
            <ListItemText primary={n.title} secondary={n.body} />
          </ListItem>
        ))}</List>
      )}
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
