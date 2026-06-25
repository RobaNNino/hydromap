import React, { useRef, useState } from "react";
import { Cropper } from "react-cropper";
import "cropperjs/dist/cropper.css";
import { Box, Button, Dialog, DialogContent, DialogActions, Typography } from "@mui/material";

// Campo immagine con ritaglio: scegli file -> crop -> data URL ridimensionato.
export default function ImageCropField({ label, value, onChange, aspect = 1, maxSize = 512, round = false }) {
  const [src, setSrc] = useState(null);
  const cropperRef = useRef(null);
  const inputRef = useRef(null);

  const pick = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setSrc(reader.result);
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  const confirm = () => {
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;
    const canvas = cropper.getCroppedCanvas({ maxWidth: maxSize, maxHeight: maxSize });
    onChange(canvas.toDataURL("image/jpeg", 0.85));
    setSrc(null);
  };

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>{label}</Typography>
      <Box sx={{ display: "flex", gap: 1.5, alignItems: "center" }}>
        <Box sx={{
          width: 72, height: aspect === 1 ? 72 : 48, borderRadius: round ? "50%" : 2.5,
          border: "1px solid", borderColor: "divider", overflow: "hidden", flexShrink: 0,
          bgcolor: "background.default", display: "grid", placeItems: "center", fontSize: 22,
        }}>
          {value ? <Box component="img" src={value} alt="" sx={{ width: "100%", height: "100%", objectFit: "cover" }} /> : "🖼️"}
        </Box>
        <Button variant="outlined" size="small" onClick={() => inputRef.current?.click()}>Carica</Button>
        {value && <Button size="small" color="error" onClick={() => onChange("")}>Rimuovi</Button>}
        <input ref={inputRef} type="file" accept="image/*" hidden onChange={pick} />
      </Box>

      <Dialog open={!!src} onClose={() => setSrc(null)} maxWidth="sm" fullWidth>
        <DialogContent>
          {src && (
            <Cropper ref={cropperRef} src={src} style={{ height: 360, width: "100%" }}
              aspectRatio={aspect} viewMode={1} guides background={false} responsive autoCropArea={1} />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSrc(null)} color="inherit">Annulla</Button>
          <Button onClick={confirm} variant="contained">Ritaglia</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
