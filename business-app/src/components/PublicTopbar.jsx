import React from "react";
import { AppBar, Toolbar, Box, Typography } from "@mui/material";
import { useTheme } from "@mui/material/styles";

export default function PublicTopbar({ cta }) {
  const dark = useTheme().palette.mode === "dark";
  return (
    <AppBar position="sticky" elevation={0}
      sx={{ bgcolor: dark ? "rgba(11,18,32,.82)" : "rgba(255,255,255,.82)", backdropFilter: "blur(14px)", color: "text.primary", borderBottom: "1px solid", borderColor: "divider" }}>
      <Toolbar sx={{ gap: 1.5 }}>
        <Box component="a" href="/" sx={{ display: "flex", alignItems: "center", gap: 1.2, textDecoration: "none", color: "inherit" }}>
          <Box component="img" src="/LOGO.svg" alt="" sx={{ width: 28, height: 28 }} />
          <Typography sx={{ fontWeight: 800, letterSpacing: "-0.02em" }}>
            Acqua<span style={{ background: "linear-gradient(135deg,#1bb2bd,#0492cf)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>Map</span> Business
          </Typography>
        </Box>
        <Box sx={{ flex: 1 }} />
        {cta}
      </Toolbar>
    </AppBar>
  );
}
