import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  timeout: 90000,
  workers: 2,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5174", browserName: "chromium", reducedMotion: "reduce", screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: { command: "npm run dev -- --port 5174 --strictPort", url: "http://127.0.0.1:5174", reuseExistingServer: false },
});
