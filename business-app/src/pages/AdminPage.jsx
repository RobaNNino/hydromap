import React, { useMemo, useState } from "react";
import {
  Box, Card, CardContent, Typography, Stack, Chip, Button, Drawer, IconButton,
  Tabs, Tab, Table, TableHead, TableRow, TableCell, TableBody, TextField, Divider,
  Checkbox, FormControlLabel, CircularProgress, Tooltip, MenuItem, Alert,
} from "@mui/material";
import DashboardIcon from "@mui/icons-material/Dashboard";
import InboxIcon from "@mui/icons-material/Inbox";
import StorefrontIcon from "@mui/icons-material/Storefront";
import VerifiedIcon from "@mui/icons-material/Verified";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../lib/auth.jsx";
import ConsoleShell from "../components/ConsoleShell.jsx";
import LoginCard from "../components/LoginCard.jsx";
import { api } from "../lib/api.js";
import { ADMIN_STEPS, stepMeta, catLabel, CAT_ICON, BADGES, PROFILE_STATUSES } from "../lib/constants.js";

const onboardingUrl = (t) => `${location.origin}/business-app/onboarding/${t}`;
const accountUrl = (t) => `${location.origin}/business-app/account/${t}`;
const copy = (txt) => { navigator.clipboard?.writeText(txt); toast.success("Copiato negli appunti"); };

function profileStep(p) {
  switch (p.status) {
    case "draft": return "to_complete";
    case "in_review":
    case "changes_requested": return "review";
    case "approved": return "badge";
    case "published": return p.account_created ? "active" : "access";
    default: return null; // suspended/archived/hidden
  }
}

export default function AdminPage() {
  const { user, loading, signOut } = useAuth();
  const qc = useQueryClient();
  const [nav, setNav] = useState("pipeline");
  const [view, setView] = useState("kanban");
  const [sel, setSel] = useState(null); // {type:'app'|'profile', data}

  const appsQ = useQuery({ queryKey: ["apps"], queryFn: () => api("/api/admin/business/applications"), enabled: !!user });
  const profsQ = useQuery({ queryKey: ["profiles"], queryFn: () => api("/api/admin/business/profiles"), enabled: !!user });

  const apps = appsQ.data?.items || [];
  const profiles = profsQ.data?.items || [];
  const forbidden = appsQ.error?.status === 403;

  const items = useMemo(() => {
    const list = [];
    apps.filter((a) => a.status === "pending").forEach((a) => list.push({ type: "app", step: "new", data: a }));
    profiles.forEach((p) => { const s = profileStep(p); if (s) list.push({ type: "profile", step: s, data: p }); });
    return list;
  }, [apps, profiles]);

  const kpis = [
    { l: "Nuove richieste", n: apps.filter((a) => a.status === "pending").length, c: "#0ea5e9" },
    { l: "Da completare", n: profiles.filter((p) => p.status === "draft").length, c: "#6366f1" },
    { l: "In revisione", n: profiles.filter((p) => p.status === "in_review").length, c: "#8b5cf6" },
    { l: "Pubblicati", n: profiles.filter((p) => p.status === "published").length, c: "#16a34a" },
    { l: "Dashboard attive", n: profiles.filter((p) => p.account_created).length, c: "#0492cf" },
  ];

  const refetch = () => { qc.invalidateQueries({ queryKey: ["apps"] }); qc.invalidateQueries({ queryKey: ["profiles"] }); };

  if (loading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;
  if (!user) return <LoginCard title="Pannello Admin" subtitle="Accedi con il tuo account amministratore." />;

  const navItems = [
    { key: "pipeline", label: "Pipeline", icon: <DashboardIcon />, badge: kpis[0].n || undefined },
    { key: "richieste", label: "Richieste", icon: <InboxIcon /> },
    { key: "profili", label: "Profili", icon: <StorefrontIcon /> },
    { key: "badge", label: "Badge", icon: <VerifiedIcon /> },
  ];

  return (
    <ConsoleShell
      title="Console Admin" subtitle="Business · Admin" nav={navItems} active={nav} onNav={setNav}
      onSignOut={signOut}
      topRight={<Button size="small" variant="outlined" onClick={refetch}>Aggiorna</Button>}
    >
      {forbidden && <Alert severity="error" sx={{ mb: 2, borderRadius: 3 }}>Questo account non ha permessi admin (aggiungi l'email a BUSINESS_ADMIN_EMAILS).</Alert>}

      {/* KPI */}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(5,1fr)" }, gap: 2, mb: 3 }}>
        {kpis.map((k) => (
          <Card key={k.l}><CardContent>
            <Typography variant="h4" sx={{ color: k.c, fontWeight: 800 }}>{k.n}</Typography>
            <Typography variant="body2" color="text.secondary">{k.l}</Typography>
          </CardContent></Card>
        ))}
      </Box>

      {nav === "pipeline" && (
        <>
          <Tabs value={view} onChange={(_e, v) => setView(v)} sx={{ mb: 2 }}>
            <Tab value="kanban" label="Kanban" />
            <Tab value="table" label="Tabella" />
          </Tabs>
          {appsQ.isLoading || profsQ.isLoading ? <CircularProgress /> :
            view === "kanban"
              ? <Kanban items={items} onOpen={setSel} />
              : <PipelineTable items={items} onOpen={setSel} />}
        </>
      )}

      {nav === "richieste" && <AppsTable apps={apps} onOpen={(a) => setSel({ type: "app", data: a })} />}
      {nav === "profili" && <ProfilesTable profiles={profiles} onOpen={(p) => setSel({ type: "profile", data: p })} />}
      {nav === "badge" && <BadgeBoard profiles={profiles} onOpen={(p) => setSel({ type: "profile", data: p })} />}

      <DetailDrawer sel={sel} onClose={() => setSel(null)} onChanged={() => { refetch(); }} setSel={setSel} />
    </ConsoleShell>
  );
}

function Kanban({ items, onOpen }) {
  return (
    <Box sx={{ display: "flex", gap: 2, overflowX: "auto", pb: 1 }}>
      {ADMIN_STEPS.map((s) => {
        const col = items.filter((i) => i.step === s.key);
        return (
          <Box key={s.key} sx={{ minWidth: 280, width: 280, flexShrink: 0 }}>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
              <Box sx={{ width: 10, height: 10, borderRadius: 999, bgcolor: s.color }} />
              <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{s.label}</Typography>
              <Chip size="small" label={col.length} />
            </Stack>
            <Stack spacing={1.2}>
              {col.map((i) => <PipelineCard key={i.type + i.data.id} item={i} onOpen={onOpen} />)}
              {col.length === 0 && <Box sx={{ border: "1px dashed", borderColor: "divider", borderRadius: 3, p: 2, textAlign: "center", color: "text.disabled", fontSize: 13 }}>—</Box>}
            </Stack>
          </Box>
        );
      })}
    </Box>
  );
}

function PipelineCard({ item, onOpen }) {
  const d = item.data;
  const name = d.business_name || "Attività";
  return (
    <Card sx={{ cursor: "pointer", "&:hover": { boxShadow: 4 } }} onClick={() => onOpen(item)}>
      <CardContent sx={{ p: 1.8, "&:last-child": { pb: 1.8 } }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Box sx={{ fontSize: 22 }}>{CAT_ICON[d.category] || "📍"}</Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{name}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {[d.city, catLabel(d.category)].filter(Boolean).join(" · ")}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
          {item.type === "app"
            ? <Chip size="small" label={d.contact_name || "—"} variant="outlined" />
            : (d.badges || []).slice(0, 2).map((b) => <Chip key={b} size="small" label={BADGES.find((x) => x.key === b)?.label || b} color="success" variant="outlined" />)}
        </Stack>
      </CardContent>
    </Card>
  );
}

function PipelineTable({ items, onOpen }) {
  return (
    <Card><Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead><TableRow>
          <TableCell>Attività</TableCell><TableCell>Città</TableCell><TableCell>Categoria</TableCell><TableCell>Step</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>
          {items.map((i) => (
            <TableRow key={i.type + i.data.id} hover>
              <TableCell><b>{i.data.business_name}</b></TableCell>
              <TableCell>{i.data.city || "—"}</TableCell>
              <TableCell>{catLabel(i.data.category)}</TableCell>
              <TableCell><Chip size="small" label={stepMeta(i.step).label} sx={{ bgcolor: stepMeta(i.step).color, color: "#fff" }} /></TableCell>
              <TableCell align="right"><Button size="small" onClick={() => onOpen(i)}>Apri</Button></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box></Card>
  );
}

function AppsTable({ apps, onOpen }) {
  return (
    <Card><Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead><TableRow>
          <TableCell>Attività</TableCell><TableCell>Referente</TableCell><TableCell>Email</TableCell><TableCell>Città</TableCell><TableCell>Stato</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>
          {apps.map((a) => (
            <TableRow key={a.id} hover>
              <TableCell><b>{a.business_name}</b></TableCell>
              <TableCell>{a.contact_name}</TableCell>
              <TableCell>{a.contact_email}</TableCell>
              <TableCell>{a.city || "—"}</TableCell>
              <TableCell><Chip size="small" label={a.status} /></TableCell>
              <TableCell align="right"><Button size="small" onClick={() => onOpen(a)}>Apri</Button></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box></Card>
  );
}

function ProfilesTable({ profiles, onOpen }) {
  return (
    <Card><Box sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead><TableRow>
          <TableCell>Attività</TableCell><TableCell>Città</TableCell><TableCell>Stato</TableCell><TableCell>Badge</TableCell><TableCell>Account</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>
          {profiles.map((p) => (
            <TableRow key={p.id} hover>
              <TableCell><b>{p.business_name}</b><br /><Typography variant="caption" color="text.secondary">/{p.slug}</Typography></TableCell>
              <TableCell>{p.city || "—"}</TableCell>
              <TableCell><Chip size="small" label={PROFILE_STATUSES[p.status] || p.status} /></TableCell>
              <TableCell>{(p.badges || []).length}</TableCell>
              <TableCell>{p.account_created ? "✓" : "—"}</TableCell>
              <TableCell align="right"><Button size="small" onClick={() => onOpen(p)}>Apri</Button></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box></Card>
  );
}

function BadgeBoard({ profiles, onOpen }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
      {profiles.map((p) => (
        <Card key={p.id} sx={{ cursor: "pointer" }} onClick={() => onOpen(p)}><CardContent>
          <Typography sx={{ fontWeight: 700 }}>{p.business_name}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            {BADGES.map((b) => {
              const on = (p.badges || []).includes(b.key);
              return <Chip key={b.key} size="small" label={`${b.icon} ${b.label}`} color={on ? "success" : "default"} variant={on ? "filled" : "outlined"} />;
            })}
          </Stack>
        </CardContent></Card>
      ))}
    </Box>
  );
}

function DetailDrawer({ sel, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  if (!sel) return null;
  const isApp = sel.type === "app";
  const d = sel.data;

  const run = async (fn) => { setBusy(true); try { await fn(); onChanged(); onClose(); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };

  const accept = () => run(async () => {
    const res = await api(`/api/admin/business/applications/${d.id}/approve`, { method: "POST", body: {} });
    const link = await api(`/api/admin/business/profiles/${res.profile.id}/onboarding-link`, { method: "POST", body: {} });
    copy(onboardingUrl(link.token));
    toast.success("Accettata. Link onboarding generato e copiato.");
  });
  const reject = () => run(() => api(`/api/admin/business/applications/${d.id}/reject`, { method: "POST", body: { admin_notes: note } }));
  const setStatus = (status) => run(() => api(`/api/admin/business/profiles/${d.id}`, { method: "PATCH", body: { status, ...(note ? { admin_notes: note } : {}) } }));
  const genOnboarding = () => run(async () => { const l = await api(`/api/admin/business/profiles/${d.id}/onboarding-link`, { method: "POST", body: {} }); copy(onboardingUrl(l.token)); });
  const genAccount = () => run(async () => { const l = await api(`/api/admin/business/profiles/${d.id}/account-link`, { method: "POST", body: {} }); copy(accountUrl(l.token)); });
  const toggleBadge = (key) => run(() => {
    const cur = new Set(d.badges || []);
    cur.has(key) ? cur.delete(key) : cur.add(key);
    return api(`/api/admin/business/profiles/${d.id}`, { method: "PATCH", body: { badges: [...cur] } });
  });

  const step = isApp ? "new" : profileStep(d);

  return (
    <Drawer anchor="right" open onClose={onClose} PaperProps={{ sx: { width: { xs: "100%", sm: 440 }, p: 0 } }}>
      <Box sx={{ p: 2.5, borderBottom: "1px solid", borderColor: "divider", display: "flex", alignItems: "center", gap: 1 }}>
        <Box sx={{ fontSize: 26 }}>{CAT_ICON[d.category] || "📍"}</Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800 }} noWrap>{d.business_name}</Typography>
          <Typography variant="caption" color="text.secondary">{catLabel(d.category)} · {d.city || "—"}</Typography>
        </Box>
        <IconButton onClick={onClose}><CloseIcon /></IconButton>
      </Box>

      <Box sx={{ p: 2.5, overflowY: "auto" }}>
        <Chip size="small" label={stepMeta(step).label} sx={{ bgcolor: stepMeta(step).color, color: "#fff", mb: 2 }} />

        {isApp ? (
          <Stack spacing={1}>
            <Field k="Referente" v={d.contact_name} />
            <Field k="Email" v={d.contact_email} />
            <Field k="Telefono" v={d.contact_phone} />
            <Field k="Indirizzo" v={[d.address, d.city, d.province].filter(Boolean).join(", ")} />
            <Field k="Sito" v={d.website} />
            <Field k="Messaggio" v={d.message || d.goal_why} />
          </Stack>
        ) : (
          <Stack spacing={1}>
            <Field k="Slug" v={`/${d.slug}`} />
            <Field k="Stato" v={PROFILE_STATUSES[d.status] || d.status} />
            <Field k="Account" v={d.account_created ? "Creato ✓" : "Non creato"} />
            <Field k="Email titolare" v={d.owner_email} />
          </Stack>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Azioni per step */}
        {step === "new" && (
          <Stack spacing={1.5}>
            <TextField label="Note admin (per rifiuto)" size="small" value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
            <Button variant="contained" disabled={busy} onClick={accept}>✓ Accetta &amp; genera link onboarding</Button>
            <Button color="error" disabled={busy} onClick={reject}>Rifiuta</Button>
          </Stack>
        )}
        {step === "to_complete" && (
          <Stack spacing={1.5}>
            <Button variant="contained" startIcon={<ContentCopyIcon />} disabled={busy} onClick={genOnboarding}>Genera/copia link onboarding</Button>
            <Button variant="outlined" disabled={busy} onClick={() => setStatus("in_review")}>Segna come "in revisione"</Button>
          </Stack>
        )}
        {step === "review" && (
          <Stack spacing={1.5}>
            <Typography variant="subtitle2">Revisione contenuti</Typography>
            <TextField label="Note (se richiedi modifiche)" size="small" value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
            <Button variant="contained" disabled={busy} onClick={() => setStatus("approved")}>Approva contenuti</Button>
            <Button color="warning" disabled={busy} onClick={() => setStatus("changes_requested")}>Richiedi modifiche</Button>
          </Stack>
        )}
        {step === "badge" && (
          <Stack spacing={1.5}>
            <Typography variant="subtitle2">Assegna badge</Typography>
            {BADGES.map((b) => (
              <FormControlLabel key={b.key}
                control={<Checkbox checked={(d.badges || []).includes(b.key)} disabled={busy} onChange={() => toggleBadge(b.key)} />}
                label={`${b.icon} ${b.label}`} />
            ))}
            <Button variant="contained" disabled={busy} onClick={() => setStatus("published")}>Pubblica profilo</Button>
          </Stack>
        )}
        {step === "access" && (
          <Stack spacing={1.5}>
            <Alert severity="success" sx={{ borderRadius: 3 }}>Profilo pubblicato.</Alert>
            <Button variant="contained" startIcon={<ContentCopyIcon />} disabled={busy} onClick={genAccount}>Genera link creazione account</Button>
            <Button variant="text" href={`/business-app/onboarding/preview`} target="_blank">Anteprima</Button>
          </Stack>
        )}
        {step === "active" && <Alert severity="success" sx={{ borderRadius: 3 }}>Account attivo e dashboard abilitata.</Alert>}
      </Box>
    </Drawer>
  );
}

function Field({ k, v }) {
  return (
    <Stack direction="row" spacing={1}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 110, flexShrink: 0 }}>{k}</Typography>
      <Typography variant="body2" sx={{ wordBreak: "break-word" }}>{v || "—"}</Typography>
    </Stack>
  );
}
