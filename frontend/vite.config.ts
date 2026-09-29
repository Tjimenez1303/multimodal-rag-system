import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Vite writes this placeholder into a csp-nonce meta tag and its own tags, and
  // nginx replaces it with each response's nonce (research section 14).
  html: { cspNonce: "__CSP_NONCE__" },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // Same origin as in production, where nginx proxies /api to the API.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**"],
      exclude: [
        "src/client/**",
        "src/components/ui/**",
        "src/components/ai-elements/**",
        "src/main.tsx",
        "**/*.test.*",
      ],
      thresholds: { lines: 90 },
    },
  },
});
