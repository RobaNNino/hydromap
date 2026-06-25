import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// L'app è servita sotto /business-app/ (Netlify) e proxy /api -> Flask in dev.
export default defineConfig({
  base: "/business-app/",
  plugins: [react()],
  build: {
    outDir: "../frontend/business-app",
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: true },
    },
  },
});
