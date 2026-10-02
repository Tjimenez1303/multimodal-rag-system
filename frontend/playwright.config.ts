import { defineConfig, devices } from "@playwright/test";

const PREVIEW_PORT = 4173;
// FR-043: the smallest supported desktop window.
const viewport = { width: 1280, height: 720 };

export default defineConfig({
  // End-to-end specs run in parallel, retried on CI only
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: process.env["CI"] ? 2 : 0,
  reporter: process.env["CI"] ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PREVIEW_PORT}`,
    trace: "on-first-retry",
  },
  // The three browser engines at the same window size
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport } },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport } },
  ],
  // Build the client and serve it with vite preview before the tests
  webServer: {
    command: `npm run build && npm run preview -- --port ${PREVIEW_PORT} --strictPort`,
    url: `http://localhost:${PREVIEW_PORT}`,
    reuseExistingServer: !process.env["CI"],
    timeout: 120_000,
  },
});
