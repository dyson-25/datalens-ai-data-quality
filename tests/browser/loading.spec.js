import { test, expect } from './fixtures.js';

const sample = { name: 'loading.csv', mimeType: 'text/csv', buffer: Buffer.from('name,value\n Alice ,1\nBob,2\n') };
const idle = page => expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
async function ready(page) {
  await page.goto('/');
  await expect(page.getByText('Local engine connected')).toHaveCount(1);
  await idle(page);
}
async function holdResponse(page, pattern) {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let count = 0;
  const handler = async route => {
    count++;
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  };
  await page.route(pattern, handler);
  return { release, count: () => count, remove: () => page.unroute(pattern, handler) };
}
async function loading(page, message) {
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('#notice')).toHaveAttribute('data-state', 'loading');
  await expect(page.locator('#notice')).toContainText(message);
  await expect(page.locator('#notice .loading-progress')).toBeVisible();
  await expect(page.locator('#notice .loading-progress')).toHaveAttribute('aria-hidden', 'true');
  await expect(page.locator('#notice')).not.toContainText(/\d+%/);
  await expect(page.locator('#main button:enabled, #main input:enabled, #main select:enabled, #main textarea:enabled')).toHaveCount(0);
  await expect(page.locator('#error')).toBeHidden();
}
async function success(page) {
  await idle(page);
  await expect(page.locator('#notice')).toHaveAttribute('data-state', 'success');
  await expect(page.locator('#notice')).toHaveText('Workspace is up to date.');
  await expect(page.locator('#notice svg')).toBeVisible();
  await expect(page.locator('#notice .loading-progress')).toHaveCount(0);
  await expect(page.locator('#error')).toBeHidden();
}
async function fitsViewport(page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const bounds = await page.locator('#notice').boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
  expect(bounds.height).toBeLessThan(110);
}

test.afterEach(async ({ page }) => {
  await page.evaluate(async () => {
    const session = JSON.parse(sessionStorage.getItem('datalens.session') || 'null');
    if (session) await fetch(`/api/v1/datasets/${session.dataset_id}`, { method: 'DELETE', headers: { 'X-Session-Token': session.token } });
  }).catch(() => {});
});

for (const scenario of [
  { name: 'desktop-dark-motion', width: 1440, height: 1000, theme: 'dark', motion: 'no-preference' },
  { name: 'desktop-light-reduced', width: 1440, height: 1000, theme: 'light', motion: 'reduce' },
  { name: 'mobile-dark-reduced', width: 390, height: 844, theme: 'dark', motion: 'reduce' },
  { name: 'mobile-light-motion', width: 390, height: 844, theme: 'light', motion: 'no-preference' }
]) {
  test(`Loading presentation: ${scenario.name} → success → error`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: scenario.width, height: scenario.height });
    await page.emulateMedia({ reducedMotion: scenario.motion });
    await ready(page);
    if (scenario.theme === 'light') await page.getByRole('button', { name: 'Switch to light theme' }).click();
    const upload = await holdResponse(page, '**/api/v1/datasets/upload');
    try {
      await page.locator('input[type=file]').setInputFiles(sample);
      await loading(page, 'Uploading and inspecting file');
      await expect(page.locator('#notice')).toHaveAttribute('role', 'status');
      await expect(page.locator('#notice')).toHaveAttribute('aria-live', 'polite');
      await expect(page.locator('#notice')).toHaveAttribute('aria-atomic', 'true');
      await expect(page.locator('.spinner')).toHaveCount(0);
      const style = await page.locator('.loading-progress').evaluate(node => {
        const track = getComputedStyle(node), bar = getComputedStyle(node, '::after');
        const color = document.createElement('span');
        color.style.color = 'var(--accent)'; node.append(color);
        const accent = getComputedStyle(color).color; color.remove();
        return { height: track.height, width: track.width, animation: bar.animationName, duration: bar.animationDuration, iterations: bar.animationIterationCount, background: bar.backgroundColor, accent, transform: bar.transform };
      });
      expect(style.height).toBe('3px'); expect(style.width).toBe('72px');
      expect(style.background).toBe(style.accent);
      if (scenario.motion === 'reduce') {
        expect(style.animation).toBe('none');
        expect(style.transform).not.toBe('none');
        expect(await page.locator('.loading-progress').evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
      } else {
        expect(style.animation).toBe('loading-traverse'); expect(style.duration).toBe('2.2s'); expect(style.iterations).toBe('infinite');
      }
      const loadingBackground = await page.locator('#notice').evaluate(node => getComputedStyle(node).backgroundColor);
      await fitsViewport(page);
      await page.screenshot({ path: testInfo.outputPath(`${scenario.name}-loading.png`) });
      await expect.poll(upload.count).toBe(1);
      await page.locator('input[type=file]').dispatchEvent('change');
      expect(upload.count()).toBe(1);
      // Keyboard navigation and theme controls remain available outside the busy workspace.
      await page.locator('#theme-toggle').focus(); await page.keyboard.press('Enter');
      await expect(page.locator('html')).toHaveAttribute('data-theme', scenario.theme === 'dark' ? 'light' : 'dark');
      await page.keyboard.press('Enter');
      upload.release();
      await success(page);
      expect(upload.count()).toBe(1);
      await expect(page.getByRole('button', { name: 'Ingest dataset', exact: true })).toBeEnabled();
      await expect(page.getByLabel('Worksheet', { exact: true })).toBeDisabled();
      expect(await page.locator('#notice').evaluate(node => getComputedStyle(node).backgroundColor)).not.toBe(loadingBackground);
      await page.locator('#notice').scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`${scenario.name}-success.png`) });
      await page.locator('input[type=file]').setInputFiles({ name: 'empty.csv', mimeType: 'text/csv', buffer: Buffer.alloc(0) });
      await expect(page.locator('#error')).toContainText('This file is empty');
      await expect(page.locator('#error')).toHaveAttribute('role', 'alert');
      await expect(page.locator('#notice')).toBeHidden();
      await idle(page);
      await page.screenshot({ path: testInfo.outputPath(`${scenario.name}-error.png`) });
      await page.getByRole('button', { name: 'Dismiss', exact: true }).focus(); await page.keyboard.press('Enter');
      await expect(page.locator('#error')).toBeHidden();
    } finally { upload.release(); await upload.remove(); }
  });
}

test('Loading phases: sample, queued ingestion, profiling, quality, approved apply and export', async ({ page }, testInfo) => {
  await ready(page);
  const prepared = await holdResponse(page, '**/api/v1/datasets/sample/quality_issues');
  const profile = await holdResponse(page, '**/api/v1/datasets/*/profile');
  const quality = await holdResponse(page, '**/api/v1/datasets/*/quality');
  let phase = 'queued', polls = 0;
  // Only job presentation is delayed/injected; ingestion and all data operations use the real backend.
  await page.route('**/api/v1/datasets/*/jobs/*', async route => {
    const response = await route.fetch();
    polls++;
    if (phase) await route.fulfill({ response, json: { ...await response.json(), status: phase } });
    else await route.fulfill({ response });
  });
  try {
    await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
    await loading(page, 'Preparing sample dataset');
    prepared.release(); await success(page);
    await page.getByRole('button', { name: 'Ingest dataset', exact: true }).click();
    await loading(page, 'Waiting for analysis engine');
    await expect(page.locator('#notice')).toContainText('no need to submit again');
    await page.locator('.loading-progress').evaluate(node => { node.dataset.identity = 'unchanged'; });
    const firstPolls = polls;
    await expect.poll(() => polls).toBeGreaterThan(firstPolls);
    await expect(page.locator('.loading-progress')).toHaveAttribute('data-identity', 'unchanged');
    phase = 'running';
    await loading(page, 'Creating baseline snapshot');
    await expect(page.locator('#notice')).toContainText('the original file is preserved');
    await page.locator('#notice').scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('ingestion-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await fitsViewport(page);
    await page.screenshot({ path: testInfo.outputPath('ingestion-mobile.png') });
    await page.setViewportSize({ width: 1440, height: 1000 });
    phase = null;
    await loading(page, 'Profiling columns');
    profile.release(); await loading(page, 'Detecting quality issues');
    quality.release(); await success(page);
    await profile.remove(); await quality.remove();
    await page.getByRole('link', { name: /Cleaning studio/ }).click();
    await page.getByLabel('Operation', { exact: true }).selectOption('trim');
    await page.getByLabel('Target column').selectOption('region');
    await page.getByRole('button', { name: 'Preview changes' }).click(); await success(page);
    await expect(page.getByRole('button', { name: 'Approve & apply' })).toBeDisabled();
    await page.getByLabel('I reviewed the operation, affected rows, and potential data loss. I approve this exact change.').check();
    const apply = await holdResponse(page, '**/api/v1/datasets/*/cleaning/apply');
    try {
      await page.getByRole('button', { name: 'Approve & apply' }).click();
      await page.getByRole('button', { name: 'Apply change', exact: true }).click();
      await loading(page, 'Applying approved transformation');
      apply.release(); await success(page);
    } finally { apply.release(); await apply.remove(); }
    await page.getByRole('link', { name: /Exports & reports/ }).click();
    const exported = await holdResponse(page, '**/api/v1/datasets/*/export?format=csv');
    try {
      const downloaded = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
      await loading(page, 'Generating export');
      exported.release();
      const download = await downloaded;
      expect(download.suggestedFilename()).toContain('-v1.csv');
      const chunks = [];
      for await (const chunk of await download.createReadStream()) chunks.push(chunk);
      expect(Buffer.concat(chunks).toString()).toContain('region');
      await success(page);
    } finally { exported.release(); await exported.remove(); }
  } finally { phase = null; prepared.release(); profile.release(); quality.release(); }
});

test('Loading failure clears progress, restores controls and supports keyboard retry', async ({ page }) => {
  await ready(page);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let attempts = 0;
  await page.route('**/api/v1/datasets/sample/quality_issues', async route => {
    attempts++;
    if (attempts > 1) return route.continue();
    await gate;
    await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: { code: 'validation_error', message: 'Synthetic inspection failure' } }) });
  });
  try {
    await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
    await loading(page, 'Preparing sample dataset');
    release();
    await expect(page.locator('#error')).toContainText('Synthetic inspection failure');
    await expect(page.locator('#notice')).toBeHidden(); await idle(page);
    await expect(page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Retry', exact: true }).focus(); await page.keyboard.press('Enter');
    await success(page);
    expect(attempts).toBe(2);
    await expect(page.getByRole('button', { name: 'Ingest dataset', exact: true })).toBeEnabled();
  } finally { release(); }
});
