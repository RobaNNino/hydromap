import React, { useRef, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Box, Button,
  Typography, Checkbox, FormControlLabel, LinearProgress,
} from "@mui/material";
import { PRIVACY_TEXT } from "../lib/constants.js";

// Modal privacy: il checkbox/CTA "Accetto" resta disabilitato finché l'utente
// non scorre fino in fondo al testo. Solo allora può accettare.
export default function PrivacyModal({ open, onClose, onAccept }) {
  const [reachedEnd, setReachedEnd] = useState(false);
  const [checked, setChecked] = useState(false);
  const [progress, setProgress] = useState(0);
  const boxRef = useRef(null);

  const handleScroll = (e) => {
    const { scrollTop, clientHeight, scrollHeight } = e.target;
    const pct = scrollHeight <= clientHeight ? 100 : Math.min(100, ((scrollTop + clientHeight) / scrollHeight) * 100);
    setProgress(pct);
    if (scrollTop + clientHeight >= scrollHeight - 20) setReachedEnd(true);
  };

  const confirm = () => { onAccept(); onClose(); };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth
      PaperProps={{ sx: { borderRadius: 4 } }}>
      <DialogTitle sx={{ fontWeight: 800 }}>Trattamento dei dati personali</DialogTitle>
      <LinearProgress variant="determinate" value={progress} sx={{ mx: 3, borderRadius: 2 }} />
      <DialogContent>
        <Box
          ref={boxRef}
          onScroll={handleScroll}
          sx={{
            maxHeight: 320, overflowY: "auto", p: 2, mt: 1,
            bgcolor: "background.default", borderRadius: 3, border: "1px solid",
            borderColor: "divider", whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.6,
          }}
        >
          <Typography component="div" sx={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.6 }}>
            {PRIVACY_TEXT}
          </Typography>
        </Box>
        <FormControlLabel
          sx={{ mt: 1.5, alignItems: "flex-start" }}
          control={
            <Checkbox
              checked={checked}
              disabled={!reachedEnd}
              onChange={(e) => setChecked(e.target.checked)}
            />
          }
          label={
            <Typography variant="body2" sx={{ mt: 1 }}>
              Ho letto e compreso l'informativa e acconsento al trattamento dei dati.
              {!reachedEnd && <b style={{ color: "#dc2626" }}> {" "}Scorri fino in fondo per attivare.</b>}
            </Typography>
          }
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit">Annulla</Button>
        <Button onClick={confirm} variant="contained" disabled={!checked}>Accetto</Button>
      </DialogActions>
    </Dialog>
  );
}
