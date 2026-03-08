import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Proxy REST API calls to the FastAPI backend during dev
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
