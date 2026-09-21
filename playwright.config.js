import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser', fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:4173', browserName: 'chromium', screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:4173', reuseExistingServer: true },
});
