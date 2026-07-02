import React, { useState } from "react";
import {
  Box, Drawer, AppBar, Toolbar, Typography, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, Avatar, Tooltip, useMediaQuery, Divider,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import LogoutIcon from "@mui/icons-material/Logout";
import DarkModeIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeIcon from "@mui/icons-material/LightModeOutlined";
import { useTheme, alpha } from "@mui/material/styles";
import { BRAND } from "../theme.js";
import { useColorMode } from "../lib/colorMode.jsx";

const SIDEBAR_W = 256;

export default function ConsoleShell({ title, subtitle, nav, active, onNav, topRight, onSignOut, children }) {
  const theme = useTheme();
  const dark = theme.palette.mode === "dark";
  const { mode, toggle } = useColorMode();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [mobileOpen, setMobileOpen] = useState(false);

  const SidebarContent = (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: "background.paper" }}>
      {/* Header brand col gradiente AcquaMap */}
      <Box sx={{
        px: 2.5, py: 2, display: "flex", alignItems: "center", gap: 1.2,
        background: BRAND.gradientSoft,
        borderBottom: "1px solid", borderColor: "divider",
      }}>
        <Box sx={{
          width: 36, height: 36, borderRadius: "12px", display: "grid", placeItems: "center",
          background: BRAND.gradient, boxShadow: "0 4px 14px rgba(4,146,207,.35)",
        }}>
          <Box component="img" src="/LOGO.svg" alt="" sx={{ width: 22, height: 22, filter: "brightness(0) invert(1)" }} />
        </Box>
        <Box>
          <Typography sx={{ fontWeight: 800, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
            Acqua<Box component="span" sx={{ color: "primary.main" }}>Map</Box>
          </Typography>
          <Typography variant="caption" color="text.secondary">{subtitle || "Business"}</Typography>
        </Box>
      </Box>
      <List sx={{ flex: 1, px: 1, py: 1, overflowY: "auto" }}>
        {nav.map((n) => (
          <ListItemButton key={n.key} selected={active === n.key}
            onClick={() => { onNav(n.key); setMobileOpen(false); }}
            sx={{ borderRadius: 2.5, mb: 0.3 }}>
            <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
            <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
            {n.badge ? (
              <Box sx={{
                bgcolor: active === n.key ? "primary.main" : alpha(theme.palette.primary.main, 0.85),
                color: theme.palette.primary.contrastText,
                borderRadius: 999, px: 1, fontSize: 12, fontWeight: 700,
              }}>{n.badge}</Box>
            ) : null}
          </ListItemButton>
        ))}
      </List>
      <Divider />
      <Box sx={{ p: 1 }}>
        <ListItemButton onClick={onSignOut} sx={{ borderRadius: 2.5 }}>
          <ListItemIcon sx={{ minWidth: 38 }}><LogoutIcon /></ListItemIcon>
          <ListItemText primary="Esci" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
        </ListItemButton>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", textAlign: "center", pb: 0.5 }}>
          AcquaMap Business · v2
        </Typography>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ height: "100dvh", minHeight: "100dvh", overflow: "hidden", display: "flex", bgcolor: "background.default" }}>
      {/* Sidebar */}
      {isDesktop ? (
        <Box sx={{ width: SIDEBAR_W, flexShrink: 0, borderRight: "1px solid", borderColor: "divider" }}>{SidebarContent}</Box>
      ) : (
        <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} ModalProps={{ keepMounted: true }}
          sx={{ "& .MuiDrawer-paper": { width: SIDEBAR_W } }}>{SidebarContent}</Drawer>
      )}

      {/* Main */}
      <Box sx={{ flex: 1, height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        <AppBar position="static" elevation={0}
          sx={{
            bgcolor: dark ? "rgba(17,26,44,.85)" : "rgba(255,255,255,.86)",
            backdropFilter: "blur(12px)", color: "text.primary",
            borderBottom: "1px solid", borderColor: "divider",
          }}>
          <Toolbar sx={{ gap: 1 }}>
            {!isDesktop && <IconButton edge="start" onClick={() => setMobileOpen(true)}><MenuIcon /></IconButton>}
            <Typography variant="h6" sx={{ fontWeight: 800 }}>{title}</Typography>
            <Box sx={{ flex: 1 }} />
            {topRight}
            <Tooltip title={mode === "dark" ? "Tema chiaro" : "Tema scuro"}>
              <IconButton onClick={toggle} size="small" sx={{ color: "text.secondary" }}>
                {mode === "dark" ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Tooltip title="Account">
              <Avatar sx={{ width: 34, height: 34, background: BRAND.gradient, fontSize: 15 }}>A</Avatar>
            </Tooltip>
          </Toolbar>
        </AppBar>
        <Box sx={{ flex: 1, overflowY: "auto", p: { xs: 2, md: 3 } }}>{children}</Box>
      </Box>
    </Box>
  );
}
