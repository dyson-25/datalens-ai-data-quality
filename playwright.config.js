import { defineConfig, devices } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// Keep browser runtime files in the project, never in a system temporary directory.
const runtime = resolve('test-results/runtime');
mkdirSync(runtime, { recursive: true });
process.env.TMPDIR = runtime;
process.env.TMP = runtime;
process.env.TEMP = runtime;
process.env.PLAYWRIGHT_BROWSERS_PATH ||= resolve('node_modules/.cache/ms-playwright');
const externalURL = process.env.PLAYWRIGHT_BASE_URL;
export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/*.spec.js',
  outputDir: './test-results/artifacts',
  fullyParallel: false,
  workers: 1,
  timeout: 120000,
  expect: { timeout: 15000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: externalURL || 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    reducedMotion: 'reduce'
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: externalURL ? undefined : {
    command: 'node tests/browser/server.mjs',
    url: 'http://127.0.0.1:8765/api/v1/health',
    timeout: 120000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10000 }
  }
});
