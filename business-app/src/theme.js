import { createTheme } from "@mui/material/styles";

// Tema "Google/Material" pulito, brand AcquaMap (teal/blu acqua).
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0492cf", dark: "#096085", light: "#36b3e0", contrastText: "#fff" },
    secondary: { main: "#1bb2bd" },
    success: { main: "#16a34a" },
    warning: { main: "#ea580c" },
    error: { main: "#dc2626" },
    background: { default: "#f6f8fc", paper: "#ffffff" },
    text: { primary: "#1f2933", secondary: "#5f6b7a" },
    divider: "#e6eaf0",
  },
  shape: { borderRadius: 16 },
  typography: {
    fontFamily: 'Inter, -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 800, letterSpacing: "-0.02em" },
    h5: { fontWeight: 800, letterSpacing: "-0.02em" },
    h6: { fontWeight: 700, letterSpacing: "-0.01em" },
    button: { fontWeight: 700, textTransform: "none" },
  },
  components: {
    MuiButton: { styleOverrides: { root: { borderRadius: 999, paddingInline: 18 } } },
    MuiCard: { styleOverrides: { root: { borderRadius: 20, border: "1px solid #e6eaf0", boxShadow: "0 1px 2px rgba(15,23,42,.04), 0 8px 30px rgba(15,23,42,.05)" } } },
    MuiPaper: { styleOverrides: { rounded: { borderRadius: 16 } } },
  },
});
