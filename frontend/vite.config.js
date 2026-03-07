import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy REST API calls to the FastAPI backend during dev
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
