import React, { useState } from "react";
import { Box, Card, CardContent, TextField, Button, Typography, Stack, Alert, Chip } from "@mui/material";
import { toast } from "sonner";
import { useAuth } from "../lib/auth.jsx";

export default function LoginCard({ title = "Accedi", subtitle, allowSignup = false }) {
  const { signIn, signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const submit = async (mode) => {
    if (!email || !pw) return;
    setBusy(true); setMsg(null);
    try {
      const fn = mode === "signup" ? signUp : signIn;
      const { error } = await fn(email, pw);
      if (error) throw new Error(error.message);
      if (mode === "signup") setMsg("Registrazione avviata: se richiesto conferma l'email, poi accedi.");
    } catch (e) { toast.error(e.message || "Errore"); }
    finally { setBusy(false); }
  };

  return (
    <Box sx={{ minHeight: "100dvh", display: "grid", placeItems: "center", bgcolor: "background.default", p: 2 }}>
      <Card sx={{ width: "100%", maxWidth: 420 }}>
        <CardContent sx={{ p: 4 }}>
          <Stack direction="row" spacing={1.2} alignItems="center" sx={{ mb: 1 }}>
            <Box sx={{ width: 34, height: 34, borderRadius: "11px", display: "grid", placeItems: "center",
              background: "linear-gradient(135deg, #1bb2bd 0%, #0492cf 60%, #0369a1 100%)",
              boxShadow: "0 4px 14px rgba(4,146,207,.35)" }}>
              <Box component="img" src="/LOGO.svg" alt="" sx={{ width: 20, height: 20, filter: "brightness(0) invert(1)" }} />
            </Box>
            <Typography sx={{ fontWeight: 800 }}>AcquaMap Business</Typography>
          </Stack>
          <Typography variant="h5" sx={{ mb: 0.5 }}>{title}</Typography>
          {subtitle && <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{subtitle}</Typography>}
          {msg && <Alert severity="info" sx={{ my: 2, borderRadius: 3 }}>{msg}</Alert>}
          <Stack spacing={2} sx={{ mt: 2 }}>
            <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth size="small" />
            <TextField label="Password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} fullWidth size="small"
              onKeyDown={(e) => e.key === "Enter" && submit("signin")} />
            <Button variant="contained" size="large" disabled={busy} onClick={() => submit("signin")}>Accedi</Button>
            {allowSignup && <Button variant="text" disabled={busy} onClick={() => submit("signup")}>Registrati</Button>}
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
