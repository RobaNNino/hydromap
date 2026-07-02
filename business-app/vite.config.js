import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// L'app è servita sotto /business-app/ (Netlify) e proxy /api -> Flask in dev.
export default defineConfig({
  base: "/business-app/",
  plugins: [react()],
  build: {
    outDir: "../frontend/business-app",
    emptyOutDir: true,
    // vendor split: il primo load (apply) non scarica charts/cropper/admin
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          mui: ["@mui/material", "@mui/icons-material", "@emotion/react", "@emotion/styled"],
          charts: ["@mui/x-charts"],
          supabase: ["@supabase/supabase-js"],
        },
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: true },
    },
  },
});
