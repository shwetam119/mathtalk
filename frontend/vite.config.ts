import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on port 8000 (see ../run.sh). All /api calls are proxied
// to it so the frontend never needs to know the backend address.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: process.env.MATHTALK_BACKEND_URL || "http://127.0.0.1:8020",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
