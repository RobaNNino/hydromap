import React, { useState } from "react";
import {
  Box, Drawer, AppBar, Toolbar, Typography, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, Avatar, Tooltip, useMediaQuery, Divider,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import LogoutIcon from "@mui/icons-material/Logout";
import { useTheme } from "@mui/material/styles";

const SIDEBAR_W = 256;

export default function ConsoleShell({ title, subtitle, nav, active, onNav, topRight, onSignOut, children }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [mobileOpen, setMobileOpen] = useState(false);

  const SidebarContent = (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: "background.paper" }}>
      <Box sx={{ px: 2.5, py: 2, display: "flex", alignItems: "center", gap: 1.2 }}>
        <Box component="img" src="/LOGO.svg" alt="" sx={{ width: 28, height: 28 }} />
        <Box>
          <Typography sx={{ fontWeight: 800, lineHeight: 1.1, letterSpacing: "-0.02em" }}>AcquaMap</Typography>
          <Typography variant="caption" color="text.secondary">{subtitle || "Business"}</Typography>
        </Box>
      </Box>
      <Divider />
      <List sx={{ flex: 1, px: 1, py: 1, overflowY: "auto" }}>
        {nav.map((n) => (
          <ListItemButton key={n.key} selected={active === n.key}
            onClick={() => { onNav(n.key); setMobileOpen(false); }}
            sx={{ borderRadius: 2.5, mb: 0.3, "&.Mui-selected": { bgcolor: "primary.main", color: "#fff", "&:hover": { bgcolor: "primary.dark" }, "& .MuiListItemIcon-root": { color: "#fff" } } }}>
            <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
            <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
            {n.badge ? <Box sx={{ bgcolor: active === n.key ? "rgba(255,255,255,.25)" : "primary.main", color: "#fff", borderRadius: 999, px: 1, fontSize: 12, fontWeight: 700 }}>{n.badge}</Box> : null}
          </ListItemButton>
        ))}
      </List>
      <Divider />
      <Box sx={{ p: 1 }}>
        <ListItemButton onClick={onSignOut} sx={{ borderRadius: 2.5 }}>
          <ListItemIcon sx={{ minWidth: 38 }}><LogoutIcon /></ListItemIcon>
          <ListItemText primary="Esci" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
        </ListItemButton>
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
          sx={{ bgcolor: "rgba(255,255,255,.86)", backdropFilter: "blur(12px)", color: "text.primary", borderBottom: "1px solid", borderColor: "divider" }}>
          <Toolbar sx={{ gap: 1 }}>
            {!isDesktop && <IconButton edge="start" onClick={() => setMobileOpen(true)}><MenuIcon /></IconButton>}
            <Typography variant="h6" sx={{ fontWeight: 800 }}>{title}</Typography>
            <Box sx={{ flex: 1 }} />
            {topRight}
            <Tooltip title="Admin"><Avatar sx={{ width: 34, height: 34, bgcolor: "primary.main", fontSize: 15 }}>A</Avatar></Tooltip>
          </Toolbar>
        </AppBar>
        <Box sx={{ flex: 1, overflowY: "auto", p: { xs: 2, md: 3 } }}>{children}</Box>
      </Box>
    </Box>
  );
}
