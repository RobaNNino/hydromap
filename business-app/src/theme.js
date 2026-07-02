import { createTheme, alpha } from "@mui/material/styles";

// Brand AcquaMap: gradiente teal→blu (allineato a frontend/style.css).
export const BRAND = {
  teal: "#1bb2bd",
  blue: "#0492cf",
  blueDark: "#096085",
  gradient: "linear-gradient(135deg, #1bb2bd 0%, #0492cf 60%, #0369a1 100%)",
  gradientSoft: "linear-gradient(135deg, rgba(27,178,189,.14), rgba(4,146,207,.10))",
};

const common = {
  shape: { borderRadius: 16 },
  typography: {
    fontFamily: 'Inter, -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 800, letterSpacing: "-0.02em" },
    h5: { fontWeight: 800, letterSpacing: "-0.02em" },
    h6: { fontWeight: 700, letterSpacing: "-0.01em" },
    button: { fontWeight: 700, textTransform: "none" },
  },
};

export function makeTheme(mode = "light") {
  const dark = mode === "dark";
  const palette = dark
    ? {
        mode: "dark",
        primary: { main: "#38bdf8", dark: "#0ea5e9", light: "#7dd3fc", contrastText: "#082f49" },
        secondary: { main: "#2dd4bf" },
        success: { main: "#4ade80" },
        warning: { main: "#fb923c" },
        error: { main: "#f87171" },
        background: { default: "#0b1220", paper: "#111a2c" },
        text: { primary: "#e2e8f0", secondary: "#94a3b8" },
        divider: "rgba(148,163,184,.16)",
      }
    : {
        mode: "light",
        primary: { main: "#0492cf", dark: "#096085", light: "#36b3e0", contrastText: "#fff" },
        secondary: { main: "#1bb2bd" },
        success: { main: "#16a34a" },
        warning: { main: "#ea580c" },
        error: { main: "#dc2626" },
        background: { default: "#f6f8fc", paper: "#ffffff" },
        text: { primary: "#1f2933", secondary: "#5f6b7a" },
        divider: "#e6eaf0",
      };

  return createTheme({
    ...common,
    palette,
    components: {
      MuiButton: {
        styleOverrides: {
          root: { borderRadius: 999, paddingInline: 18 },
          // CTA principale col gradiente brand
          containedPrimary: {
            background: BRAND.gradient,
            color: "#fff",
            "&:hover": { background: BRAND.gradient, filter: "brightness(1.06)" },
            "&.Mui-disabled": { background: "none" },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 20,
            border: "1px solid",
            borderColor: dark ? "rgba(148,163,184,.14)" : "#e6eaf0",
            backgroundImage: "none",
            boxShadow: dark
              ? "0 1px 2px rgba(0,0,0,.35), 0 8px 30px rgba(0,0,0,.25)"
              : "0 1px 2px rgba(15,23,42,.04), 0 8px 30px rgba(15,23,42,.05)",
          },
        },
      },
      MuiPaper: { styleOverrides: { rounded: { borderRadius: 16 }, root: { backgroundImage: "none" } } },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            "&.Mui-selected": {
              backgroundColor: alpha(dark ? "#38bdf8" : "#0492cf", dark ? 0.16 : 0.1),
              color: dark ? "#7dd3fc" : "#096085",
              "&:hover": { backgroundColor: alpha(dark ? "#38bdf8" : "#0492cf", dark ? 0.24 : 0.16) },
              "& .MuiListItemIcon-root": { color: "inherit" },
            },
          },
        },
      },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiTooltip: { styleOverrides: { tooltip: { borderRadius: 8, fontWeight: 500 } } },
    },
  });
}

// Compat: alcune pagine importano ancora `theme` (light statico).
export const theme = makeTheme("light");
