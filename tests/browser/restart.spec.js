import { test, expect } from './fixtures.js';
import { spawn } from 'node:child_process';
import { mkdir, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { resolve } from 'node:path';

async function idle(page) { await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false', { timeout: 90000 }); }
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise(resolve => {
    const timeout = setTimeout(() => child.kill('SIGKILL'), 10000);
    child.once('exit', () => { clearTimeout(timeout); resolve(); });
    child.kill('SIGTERM');
  });
}

test('UI-restart: real server process restart preserves undo/redo, reset, capability and exports', async ({ page }, testInfo) => {
  const socket = createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const root = testInfo.outputPath('isolated-storage');
  await mkdir(root, { recursive: true });
  const base = `http://127.0.0.1:${port}`;
  const logs = [];
  let server;
  async function start() {
    server = spawn(resolve('.venv/bin/python'), ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(port)], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, APP_ENV: 'test', AI_ENABLED: 'false', STORAGE_ROOT: root }
    });
    server.stdout.on('data', chunk => logs.push(chunk.toString()));
    server.stderr.on('data', chunk => logs.push(chunk.toString()));
    await expect.poll(async () => {
      try { return (await fetch(`${base}/api/v1/health`, { signal: AbortSignal.timeout(1000) })).status; } catch { return 0; }
    }, { timeout: 30000 }).toBe(200);
  }
  async function metadata() {
    return page.evaluate(async () => {
      const session = JSON.parse(sessionStorage.getItem('datalens.session'));
      return (await fetch(`/api/v1/datasets/${session.dataset_id}`, { headers: { 'X-Session-Token': session.token } })).json();
    });
  }
  try {
    await start(); await page.goto(base); await idle(page);
    await page.locator('input[type=file]').setInputFiles({ name: 'restart.csv', mimeType: 'text/csv', buffer: Buffer.from('name,value\n Alice ,1\nBob,2\n') }); await idle(page);
    await page.getByRole('button', { name: 'Ingest dataset', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'A clearer view of your data.' })).toBeVisible(); await idle(page);
    const original = await metadata();
    await page.getByRole('link', { name: /Cleaning studio/ }).click();
    await page.getByLabel('Operation', { exact: true }).selectOption('trim'); await page.getByLabel('Target column').selectOption('name');
    await page.getByRole('button', { name: 'Preview changes' }).click(); await idle(page);
    await page.getByLabel('I reviewed the operation, affected rows, and potential data loss. I approve this exact change.').check();
    await page.getByRole('button', { name: 'Approve & apply' }).click();
    const applied = page.waitForResponse(response => response.url().endsWith('/cleaning/apply') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Apply change', exact: true }).click(); expect((await applied).ok()).toBe(true); await idle(page);
    await page.getByRole('button', { name: 'Undo', exact: true }).click(); await idle(page);
    expect((await metadata()).active_version).toBe(0);
    await stop(server); await start(); await page.reload(); await expect(page.getByText('Local engine connected')).toBeVisible(); await idle(page);
    await expect(page.locator('#error')).toBeHidden();
    expect((await metadata()).dataset_id).toBe(original.dataset_id);
    expect((await metadata()).expires_at).toBe(original.expires_at);
    await expect(page.getByRole('button', { name: 'Redo', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Redo', exact: true }).click(); await idle(page);
    expect((await metadata()).active_version).toBe(1);
    await page.getByRole('button', { name: 'Reset to original', exact: true }).click();
    const reset = page.waitForResponse(response => response.url().endsWith('/reset') && response.request().method() === 'POST');
    await page.getByRole('dialog').getByRole('button', { name: 'Reset to original', exact: true }).click(); expect((await reset).ok()).toBe(true); await idle(page);
    await page.reload(); await expect(page.getByText('Local engine connected')).toBeVisible(); await idle(page); await expect(page.locator('#error')).toBeHidden();
    expect((await metadata()).active_version).toBe(0);
    await page.getByRole('link', { name: /Exports & reports/ }).click();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
    const download = await downloadEvent;
    const chunks = [];
    for await (const chunk of await download.createReadStream()) chunks.push(chunk);
    expect(Buffer.concat(chunks).toString('utf8')).toContain('" Alice "');
    expect(download.suggestedFilename()).toBe('restart-v0.csv');
    await idle(page);
  } finally {
    await stop(server);
    await testInfo.attach('restart-server-log', { body: Buffer.from(logs.join('')), contentType: 'text/plain' });
    await rm(root, { recursive: true, force: true });
  }
});
