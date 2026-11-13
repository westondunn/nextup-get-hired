import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results/artifacts',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:15173',
    browserName: 'chromium',
    trace: 'retain-on-failure',
  },
});
