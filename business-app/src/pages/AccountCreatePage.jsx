import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Box, Container, Card, CardContent, Typography, TextField, Button, Stack, Alert, CircularProgress } from "@mui/material";
import { toast } from "sonner";
import PublicTopbar from "../components/PublicTopbar.jsx";
import { api } from "../lib/api.js";
import { supabase } from "../lib/supabase.js";

export default function AccountCreatePage() {
  const { token } = useParams();
  const [ctx, setCtx] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pw, setPw] = useState(""); const [pw2, setPw2] = useState("");
  const [pin, setPin] = useState(""); const [pin2, setPin2] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    (async () => {
      try { setCtx(await api(`/api/business/account/${token}`, { auth: false })); }
      catch (e) { setErr(e.message || "Link non valido o scaduto."); }
      finally { setLoading(false); }
    })();
  }, [token]);

  const submit = async () => {
    if (pw.length < 8) return toast.error("Password troppo corta (min 8).");
    if (pw !== pw2) return toast.error("Le password non coincidono.");
    if (!/^\d{4,6}$/.test(pin)) return toast.error("Il PIN deve avere 4-6 cifre.");
    if (pin !== pin2) return toast.error("I PIN non coincidono.");
    setBusy(true);
    try {
      const { data, error } = await supabase.auth.signUp({ email: ctx.owner_email, password: pw });
      if (error && !/already registered/i.test(error.message)) throw new Error(error.message);
      // Se abbiamo una sessione, completiamo subito (set PIN + collega account).
      const { data: sess } = await supabase.auth.getSession();
      if (sess?.session) {
        await api(`/api/business/account/${token}/complete`, { method: "POST", body: { pin } });
        toast.success("Account creato!");
      } else {
        toast.message("Conferma l'email ricevuta, poi accedi alla dashboard per finalizzare.");
      }
      setDone(true);
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };

  if (loading) return <Box sx={{ display: "grid", placeItems: "center", height: "100dvh" }}><CircularProgress /></Box>;

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <PublicTopbar />
      <Container maxWidth="sm" sx={{ py: 6 }}>
        {err ? <Alert severity="error" sx={{ borderRadius: 3 }}>{err}</Alert> : done ? (
          <Card><CardContent sx={{ p: 4, textAlign: "center" }}>
            <Typography sx={{ fontSize: 56 }}>🔐</Typography>
            <Typography variant="h5" gutterBottom>Accesso pronto</Typography>
            <Typography color="text.secondary">Ora puoi entrare nella dashboard della tua attività.</Typography>
            <Button href="/business-app/dashboard" variant="contained" sx={{ mt: 3 }}>Vai alla dashboard</Button>
          </CardContent></Card>
        ) : (
          <Card><CardContent sx={{ p: 4 }}>
            <Typography variant="h5" gutterBottom>Crea il tuo accesso Business</Typography>
            <Typography color="text.secondary" sx={{ mb: 1 }}>{ctx?.business_name}</Typography>
            <Alert severity="info" sx={{ borderRadius: 3, mb: 2 }}>Account per: <b>{ctx?.owner_email}</b></Alert>
            <Stack spacing={2}>
              <TextField label="Password (min 8)" type="password" value={pw} onChange={(e) => setPw(e.target.value)} size="small" />
              <TextField label="Conferma password" type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} size="small" />
              <TextField label="PIN di sicurezza (4-6 cifre)" type="password" value={pin} onChange={(e) => setPin(e.target.value)} size="small" inputProps={{ inputMode: "numeric" }} />
              <TextField label="Conferma PIN" type="password" value={pin2} onChange={(e) => setPin2(e.target.value)} size="small" inputProps={{ inputMode: "numeric" }} />
              <Typography variant="caption" color="text.secondary">La password serve per accedere. Il PIN protegge le azioni sensibili.</Typography>
              <Button variant="contained" size="large" disabled={busy} onClick={submit}>Crea accesso</Button>
            </Stack>
          </CardContent></Card>
        )}
      </Container>
    </Box>
  );
}
