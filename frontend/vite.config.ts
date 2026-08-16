import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // No proxy, deliberately. Proxying would put the API on the same origin and
    // hide both the CORS configuration and the cookie rules we actually ship,
    // so a reviewer running this locally would never exercise them.
    strictPort: true,
  },
});
