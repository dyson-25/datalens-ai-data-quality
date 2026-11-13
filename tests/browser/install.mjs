import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
const runtime = resolve('node_modules/.cache/browser-install');
mkdirSync(runtime, { recursive: true });
const result = spawnSync(process.execPath, [resolve('node_modules/@playwright/test/cli.js'), 'install', 'chromium'], {
  stdio: 'inherit',
  env: { ...process.env, PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || resolve('node_modules/.cache/ms-playwright'), TMPDIR: runtime, TMP: runtime, TEMP: runtime }
});
process.exitCode = result.status ?? 1;
