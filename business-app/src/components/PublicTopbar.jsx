import React from "react";
import { AppBar, Toolbar, Box, Typography, Button } from "@mui/material";

export default function PublicTopbar({ cta }) {
  return (
    <AppBar position="sticky" elevation={0}
      sx={{ bgcolor: "rgba(255,255,255,.82)", backdropFilter: "blur(14px)", color: "text.primary", borderBottom: "1px solid", borderColor: "divider" }}>
      <Toolbar sx={{ gap: 1.5 }}>
        <Box component="a" href="/" sx={{ display: "flex", alignItems: "center", gap: 1.2, textDecoration: "none", color: "inherit" }}>
          <Box component="img" src="/LOGO.svg" alt="" sx={{ width: 28, height: 28 }} />
          <Typography sx={{ fontWeight: 800, letterSpacing: "-0.02em" }}>
            Acqua<span style={{ color: "#0492cf" }}>Map</span> Business
          </Typography>
        </Box>
        <Box sx={{ flex: 1 }} />
        {cta}
      </Toolbar>
    </AppBar>
  );
}
