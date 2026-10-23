import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "workflow-smoke.spec.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: "line",
  use: { browserName: "chromium", headless: true },
});
