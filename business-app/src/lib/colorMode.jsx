import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

// Modalità colore: segue il sistema (prefers-color-scheme) finché l'utente
// non sceglie esplicitamente; la scelta è persistita in localStorage.
const KEY = "am_biz_color_mode"; // "light" | "dark" | assente = auto

const ColorModeCtx = createContext({ mode: "light", toggle: () => {} });

function systemMode() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ColorModeProvider({ children }) {
  const [mode, setMode] = useState(() => localStorage.getItem(KEY) || systemMode());

  useEffect(() => {
    // segui il sistema solo se l'utente non ha espresso una preferenza
    if (localStorage.getItem(KEY)) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setMode(mq.matches ? "dark" : "light");
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  const value = useMemo(() => ({
    mode,
    toggle: () => setMode((m) => {
      const next = m === "dark" ? "light" : "dark";
      localStorage.setItem(KEY, next);
      return next;
    }),
  }), [mode]);

  return <ColorModeCtx.Provider value={value}>{children}</ColorModeCtx.Provider>;
}

export const useColorMode = () => useContext(ColorModeCtx);
