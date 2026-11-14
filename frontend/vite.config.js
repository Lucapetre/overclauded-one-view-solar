import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../packages/contracts", import.meta.url)),
        fileURLToPath(new URL("../backend/fixtures", import.meta.url)),
      ],
      deny: [
        ".env",
        ".env.*",
        "*.{crt,pem}",
        "**/.git/**",
        "**/.local/**",
        "**/*.sqlite",
        "**/*.sqlite-*",
      ],
    },
    proxy: {
      "/api": {
        target: process.env.SOLAR_BACKEND_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
