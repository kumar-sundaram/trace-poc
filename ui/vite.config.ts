import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy to the FastAPI app; the production build is served by
// FastAPI itself, so paths are same-origin there.
const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/explore": api,
      "/signals": api,
      "/events": api,
      "/admin": api,
      "/healthz": api,
    },
  },
});
