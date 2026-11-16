import { test, expect } from './fixtures.js';
import { mkdir } from 'node:fs/promises';

async function capture(page, name) {
  if (process.env.UPDATE_SCREENSHOTS !== '1') return;
  await mkdir('docs/screenshots', { recursive: true });
  await page.screenshot({ path: `docs/screenshots/${name}.png`, fullPage: false, animations: 'disabled' });
}

async function ready(page) {
  await page.goto('/');
  await expect(page.getByText('Local engine connected')).toBeVisible();
  await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false');
}
async function idle(page) { await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false', { timeout: 90000 }); }
async function navigate(page, hash) { await page.goto(`/#${hash}`); await idle(page); }
async function ingest(page) {
  await page.getByRole('button', { name: 'Ingest dataset', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'A clearer view of your data.' })).toBeVisible({ timeout: 90000 });
  await idle(page);
  await expect(page.locator('#error')).toBeHidden();
}
async function datasetGet(page, suffix = '') {
  return page.evaluate(async suffix => {
    const session = JSON.parse(sessionStorage.getItem('datalens.session'));
    const response = await fetch(`/api/v1/datasets/${session.dataset_id}${suffix}`, { headers: { 'X-Session-Token': session.token } });
    if (!response.ok) throw new Error(`Dataset request failed: ${response.status}`);
    return response.json();
  }, suffix);
}
async function approve(page) {
  await page.getByLabel('I reviewed the operation, affected rows, and potential data loss. I approve this exact change.').check();
  await page.getByRole('button', { name: 'Approve & apply' }).click();
  await page.getByRole('button', { name: 'Apply change', exact: true }).click();
  await idle(page);
  await expect(page.locator('#error')).toBeHidden();
}
async function downloadText(page, name) {
  const event = page.waitForEvent('download');
  await page.getByRole('button', { name, exact: true }).click();
  const download = await event;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  await idle(page);
  const bytes = Buffer.concat(chunks);
  return { text: bytes.toString('utf8'), bytes, name: download.suggestedFilename() };
}

test.afterEach(async ({ page }) => {
  await page.evaluate(async () => {
    const session = JSON.parse(sessionStorage.getItem('datalens.session') || 'null');
    if (session) await fetch(`/api/v1/datasets/${session.dataset_id}`, { method: 'DELETE', headers: { 'X-Session-Token': session.token } });
  }).catch(() => {});
});

test('sample → profile → approved cleaning → undo/redo/restore → authorized exports', async ({ page }) => {
  const errors = [];
  const datasetRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/api/v1/datasets/')) datasetRequests.push(request); });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await ready(page);
  await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
  await idle(page);
  await ingest(page);
  const baseline = await datasetGet(page, '/profile');
  const original = await datasetGet(page);
  expect(original.active_version).toBe(0);
  expect(original.revision).toBeGreaterThanOrEqual(1);
  expect(baseline.columns).toBeGreaterThan(1);
  await expect(page.locator('canvas').first()).toBeVisible();
  await capture(page, 'dashboard-dark');
  await page.getByRole('button', { name: 'Switch to light theme' }).click();
  await capture(page, 'dashboard-light');
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await page.getByLabel('Profiled column').selectOption('amount');
  await page.locator('#column-detail').scrollIntoViewIfNeeded();
  await capture(page, 'column-profiler');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, 'mobile-overview');
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.getByRole('link', { name: /Quality & anomalies/ }).click();
  await capture(page, 'quality-lab');
  await page.getByRole('link', { name: /Cleaning studio/ }).click();
  await page.getByLabel('Operation', { exact: true }).selectOption('drop_column');
  await page.getByLabel('Target column').selectOption(baseline.column_profiles[0].name);
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await expect(page.getByRole('heading', { name: 'Review this exact change' })).toBeVisible();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(0);
  await expect(page.getByRole('button', { name: 'Approve & apply' })).toBeDisabled();
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, 'cleaning-studio');
  await approve(page);
  expect((await datasetGet(page, '/profile')).columns).toBe(baseline.columns - 1);
  expect((await datasetGet(page)).revision).toBe(original.revision + 1);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(0);
  expect((await datasetGet(page, '/profile')).columns).toBe(baseline.columns);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(1);
  await page.getByRole('button', { name: 'Restore v0', exact: true }).click();
  await page.getByRole('button', { name: 'Restore version', exact: true }).click();
  await idle(page);
  const restored = await datasetGet(page);
  expect(restored.active_version).toBe(0);
  expect(restored.revision).toBe(original.revision + 4);
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  const csv = await downloadText(page, 'Download CSV');
  expect(csv.name).toMatch(/-v0\.csv$/);
  expect(csv.text.split('\n').length).toBeGreaterThan(1);
  const json = await downloadText(page, 'Download JSON');
  expect(() => JSON.parse(json.text)).not.toThrow();
  await page.addInitScript(() => { window.print = () => { window.__printRequested = true; }; });
  await page.getByRole('button', { name: 'Print report / Save as PDF' }).click();
  await idle(page);
  await expect(page.locator('#error')).toBeHidden();
  await expect.poll(() => page.evaluate(() => document.querySelector('iframe[title="Printable quality report"]')?.contentWindow?.__printRequested === true)).toBe(true);
  expect(await page.locator('iframe[title="Printable quality report"]').getAttribute('sandbox')).not.toContain('allow-scripts');
  const session = await page.evaluate(() => JSON.parse(sessionStorage.getItem('datalens.session')));
  expect(await page.evaluate(() => localStorage.getItem('datalens.session'))).toBeNull();
  for (const request of datasetRequests) {
    expect(request.url()).not.toContain(session.token);
    if (!request.url().includes('/datasets/sample/')) expect(request.headers()['x-session-token']).toBe(session.token);
  }
  expect(errors).toEqual([]);
});

test('active region trim exports contain the cleaned snapshot and printable report', async ({ page }, testInfo) => {
  await ready(page);
  await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
  await idle(page);
  await ingest(page);
  const baseline = await datasetGet(page, '/profile');
  expect([baseline.rows, baseline.columns]).toEqual([21, 10]);
  await page.getByRole('link', { name: /Cleaning studio/ }).click();
  await page.getByLabel('Operation', { exact: true }).selectOption('trim');
  await page.getByLabel('Target column').selectOption('region');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.getByRole('button', { name: 'Approve & apply' })).toBeDisabled();
  await approve(page);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(0);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(1);
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  await expect(page.getByText(/This session expires at/)).toBeVisible();
  for (const [label, extension] of [['CSV', 'csv'], ['XLSX', 'xlsx'], ['JSON', 'json'], ['HTML', 'html'], ['Python', 'py'], ['SQL', 'sql']]) {
    const file = await downloadText(page, `Download ${label}`);
    expect(file.name).toBe(`quality_issues-v1.${extension}`);
    if (extension === 'csv') {
      expect(file.text).toContain('"00004","California"');
      expect(file.text).not.toContain(' California ');
      expect(file.text.trim().split('\n')).toHaveLength(22);
    } else if (extension === 'xlsx') {
      const actual = await page.evaluate(async () => {
        const {datasetApi} = await import('/static/api.js');
        return Array.from(new Uint8Array(await (await datasetApi('/export?format=xlsx', {blob:true})).arrayBuffer()));
      });
      expect(file.bytes.equals(Buffer.from(actual))).toBe(true);
      expect(file.bytes.subarray(0, 2).toString()).toBe('PK');
    } else if (extension === 'json') {
      const report = JSON.parse(file.text);
      expect(report.profile).toEqual(await datasetGet(page, '/profile'));
      expect(report.history.active_version).toBe(1);
      expect(report.history.versions[1].operation.column).toBe('region');
    } else if (extension === 'html') {
      expect(file.text).toContain('<!doctype html>');
      expect(file.text).toContain('&quot;active_version&quot;: 1');
      expect(file.text).toContain('region');
    } else if (extension === 'py') {
      expect(file.text).toContain('"column": "region"');
      expect(file.text).toContain('def replay(baseline):');
    } else {
      expect(file.text).toContain('SET "region" = btrim("region"');
      expect(file.text).toContain('ROLLBACK;');
    }
  }
  await page.addInitScript(() => { window.print = () => { window.__printRequested = true; }; });
  await page.getByRole('button', { name: 'Print report / Save as PDF' }).click();
  await idle(page);
  await expect.poll(() => page.evaluate(() => document.querySelector('iframe[title="Printable quality report"]')?.contentWindow?.__printRequested === true)).toBe(true);
  const reportFrame = page.frameLocator('iframe[title="Printable quality report"]');
  await expect(reportFrame.locator('body')).toContainText('"active_version": 1');
  await expect(reportFrame.locator('body')).toContainText('region');
  const printable = await page.locator('iframe[title="Printable quality report"]').getAttribute('srcdoc');
  const pdfPage = await page.context().newPage();
  await pdfPage.setContent(printable);
  const pdf = await pdfPage.pdf({path:testInfo.outputPath('active-v1-report.pdf'), printBackground:true});
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.length).toBeGreaterThan(1000);
  await pdfPage.close();
  await expect(page.locator('#error')).toBeHidden();
});

for (const state of ['removed', 'removed-reload', 'expired', 'invalid-token', 'missing-route']) {
  test(`export handles ${state} without presenting stale dataset state`, async ({ page }) => {
    await ready(page);
    await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
    await idle(page);
    await ingest(page);
    await page.getByRole('link', { name: /Exports & reports/ }).click();
    if (state.startsWith('removed')) {
      await page.evaluate(async () => {
        const {datasetApi} = await import('/static/api.js');
        await datasetApi('', {method:'DELETE'});
      });
    } else if (state === 'invalid-token') {
      await page.evaluate(async () => {
        const {getSession, setSession} = await import('/static/api.js');
        setSession({...getSession(), token:'invalid'});
      });
    } else {
      await page.route(state === 'expired' ? '**/api/v1/datasets/**' : '**/api/v1/datasets/*/report?format=json', route => route.fulfill({
        status: state === 'expired' ? 410 : 404, contentType:'application/json',
        body:JSON.stringify({error:{code:state === 'expired' ? 'expired' : 'not_found', message:'Unavailable'}})
      }));
    }
    if (state === 'removed-reload') await page.reload();
    else await page.getByRole('button', { name: 'Download JSON', exact: true }).click();
    await idle(page);
    if (state === 'missing-route') {
      expect(await page.evaluate(() => !!sessionStorage.getItem('datalens.session'))).toBe(true);
      await expect(page.getByRole('button', { name:'Download JSON', exact:true })).toBeVisible();
    } else {
      await expect(page.locator('#error')).toContainText('Upload the original file again');
      await expect(page.locator('#error')).not.toContainText('null');
      await expect(page.locator('#dataset-chip')).toHaveText('No dataset loaded');
      await expect(page.getByRole('button', { name:'Download JSON', exact:true })).toHaveCount(0);
      expect(await page.evaluate(() => sessionStorage.getItem('datalens.session'))).toBeNull();
      await expect(page.locator('#error').getByRole('button', {name:'Retry', exact:true})).toHaveCount(0);
      if (state === 'removed') {
        await page.getByRole('button', {name:'Go to upload', exact:true}).click();
        await page.getByRole('button', {name:'Explore sample: Quality Issues', exact:true}).click();
        await idle(page);
        await ingest(page);
        await page.getByRole('link', {name:/Exports & reports/}).click();
        const recovered = await downloadText(page, 'Download JSON');
        expect(JSON.parse(recovered.text).profile.rows).toBe(21);
      }
    }
  });
}

test('CSV upload preserves raw values, trim changes only the reviewed column, preview invalidates on edit', async ({ page }) => {
  await ready(page);
  await page.getByLabel('Choose CSV or Excel file').setInputFiles({ name: 'customers.csv', mimeType: 'text/csv', buffer: Buffer.from('name,amount,category\n  Alice  ,10,A\n Bob ,20,B\nCara,30,A\n') });
  await idle(page);
  await page.getByLabel('Header row', { exact: true }).selectOption('0');
  await ingest(page);
  let rejected = false;
  await page.route('**/api/v1/datasets/*/profile', async route => {
    if (!rejected) { rejected = true; await route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ error: { code: 'busy', message: 'Engine busy' } }) }); }
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await idle(page);
  expect(rejected).toBe(true);
  await expect(page.locator('#error')).toBeHidden();
  await page.getByRole('link', { name: /Cleaning studio/ }).click();
  await page.getByLabel('Operation', { exact: true }).selectOption('trim');
  await page.getByLabel('Target column').selectOption('name');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.getByRole('region', { name: 'Cleaning change preview' })).toContainText('Alice');
  await page.getByLabel('Target column').selectOption('category');
  await expect(page.getByRole('button', { name: 'Approve & apply' })).toHaveCount(0);
  await page.getByLabel('Target column').selectOption('name');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page); await approve(page);
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  const csv = await downloadText(page, 'Download CSV');
  expect(csv.text).toMatch(/"?Alice"?,"?10"?,"?A"?/);
  expect(csv.text).not.toContain('  Alice  ');
  const python = await downloadText(page, 'Download Python');
  expect(python.text.length).toBeGreaterThan(30);
  await page.getByRole('link', { name: /Quality & anomalies/ }).click();
  const beforeRange = await datasetGet(page);
  await page.getByLabel('Range check column').selectOption('amount');
  await page.getByLabel('Expected maximum').fill('15');
  await page.getByRole('button', { name: 'Check numeric range' }).click();
  await idle(page);
  await expect(page.locator('#error')).toBeHidden();
  await expect(page.getByText('Domain range · amount', { exact: true })).toBeVisible();
  const afterRange = await datasetGet(page);
  expect(afterRange.active_version).toBe(beforeRange.active_version);
  expect(afterRange.revision).toBe(beforeRange.revision);
  await page.getByRole('group', { name: 'Numeric columns' }).getByLabel('amount', { exact: true }).check();
  await page.getByRole('button', { name: 'Run anomaly detection' }).click();
  await idle(page);
  await expect(page.getByRole('heading', { name: 'Anomaly results' })).toBeVisible();
});

test('empty, unsupported and malformed uploads show actionable errors', async ({ page }) => {
  await ready(page);
  const file = page.getByLabel('Choose CSV or Excel file');
  await file.setInputFiles({ name: 'empty.csv', mimeType: 'text/csv', buffer: Buffer.alloc(0) });
  await expect(page.getByRole('alert')).toContainText('empty');
  await file.setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('not a supported dataset') });
  await expect(page.getByRole('alert')).toContainText('Unsupported file type');
  await file.setInputFiles({ name: 'broken.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('This is not a ZIP workbook.') });
  await idle(page);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ingest dataset', exact: true })).toHaveCount(0);
});

test('untrusted headers and values remain text in tables, charts, and mobile themes', async ({ page }) => {
  const dialogs = [];
  page.on('dialog', async dialog => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  await ready(page);
  const header = '<img src=x onerror=alert(91)>';
  const payload = '<svg onload=alert(92)>';
  const quote = value => `"${value.replaceAll('"', '""')}"`;
  await page.getByLabel('Choose CSV or Excel file').setInputFiles({ name: 'untrusted.csv', mimeType: 'text/csv', buffer: Buffer.from(`${quote(header)},amount\n${quote(payload)},12\nnormal,20\nnormal,30\n`) });
  await idle(page);
  await expect(page.getByRole('region', { name: 'Raw file preview including possible header row' })).toContainText(payload);
  await page.getByLabel('Header row', { exact: true }).selectOption('0');
  await ingest(page);
  await page.getByLabel('Profiled column').selectOption(header);
  await expect(page.getByRole('region', { name: 'Dataset preview' })).toContainText(payload);
  expect(await page.locator('#main img, #main svg[onload], #main [onerror]').count()).toBe(0);
  const charts = page.locator('canvas');
  for (let i = 0; i < Math.min(await charts.count(), 3); i++) await charts.nth(i).hover();
  await page.getByRole('button', { name: 'Switch to light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: /Quality & anomalies/ }).click();
  await expect(page.getByRole('heading', { name: 'Find the signal. Question the unusual.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(dialogs).toEqual([]);
});

test('XLSX worksheet selection is submitted and an authorized workbook can be exported', async ({ page }) => {
  await ready(page);
  await page.getByRole('button', { name: 'Explore sample: Multi Sheet', exact: true }).click();
  await idle(page);
  const sheets = await page.locator('#ingest-sheet option').allTextContents();
  expect(sheets.length).toBeGreaterThan(1);
  await page.getByLabel('Worksheet', { exact: true }).selectOption(sheets[1]);
  const ingestRequest = page.waitForRequest(request => request.url().endsWith('/ingest') && request.method() === 'POST');
  await ingest(page);
  expect((await ingestRequest).postDataJSON().sheet).toBe(sheets[1]);
  expect((await datasetGet(page, '/profile')).rows).toBeGreaterThan(0);
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  const workbook = await downloadText(page, 'Download XLSX');
  expect(workbook.name).toMatch(/\.xlsx$/);
  expect(workbook.bytes.subarray(0, 2).toString()).toBe('PK');
});

test('retail refinement: approved conversions, ambiguity, whitespace, domain and no-op', async ({ page }) => {
  await ready(page);
  const rows = Array.from({ length: 10 }, (_, index) => [
    `NS-${String(index + 1).padStart(5, '0')}`, `person${index}@example.test`,
    index === 9 ? 'Californa' : 'California', index === 0 ? '  Chennai ' : 'Chennai',
    ['1', '2', '5', 'two', 'many', '-3', '0', '', '4', '7'][index],
    ['2026-09-04', '09/09/2026', '16/08/2026', '2026/10/02', '31/10/2026', '31-10-2026', '04/09/2026', '', '2026-01-01', '2026-02-01'][index],
    [-10, 125, 0, 10, 20, 25, 30, 50, 75, 100][index]
  ].join(','));
  await page.getByLabel('Choose CSV or Excel file').setInputFiles({ name: 'retail.csv', mimeType: 'text/csv', buffer: Buffer.from(`order_id,customer_email,region,city,quantity,order_date,discount_pct\n${rows.join('\n')}\n`) });
  await idle(page);
  await page.getByLabel('Header row', { exact: true }).selectOption('0');
  await ingest(page);
  await navigate(page, 'quality');
  await expect(page.getByRole('heading', { name: 'Spelling variations · order_id' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Spelling variations · customer_email' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Review-only category mapping' })).toContainText('Californa');
  await page.getByRole('button', { name: 'Review mapping', exact: true }).click();
  await expect(page.locator('#param-mapping')).toHaveValue(/Californa/);
  expect((await datasetGet(page)).active_version).toBe(0);
  await page.getByLabel('Operation', { exact: true }).selectOption('to_numeric');
  await page.getByLabel('Target column').selectOption('quantity');
  await expect(page.locator('#numeric-readiness')).toContainText('7 of 9');
  await expect(page.locator('#numeric-readiness')).toContainText('2 invalid values; 1 missing cells');
  await page.getByRole('button', { name: 'Review selected tokens as null' }).click();
  await expect(page.locator('#error')).toContainText('Select exact invalid tokens first');
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click();
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.locator('#error')).toContainText('Numeric conversion would lose invalid values');
  expect((await datasetGet(page)).active_version).toBe(0);
  await page.getByRole('group', { name: 'Invalid tokens to replace with null' }).getByLabel('"many"', { exact: true }).check();
  await page.getByRole('button', { name: 'Review selected tokens as null' }).click();
  await expect(page.locator('#param-tokens')).toHaveValue('["many"]');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.getByRole('region', { name: 'Cleaning change preview' })).toContainText('many');
  await page.getByRole('button', { name: 'Discard preview' }).click();
  expect((await datasetGet(page)).active_version).toBe(0);
  await page.getByLabel('Operation', { exact: true }).selectOption('to_numeric');
  await page.getByRole('button', { name: 'Correct values with a mapping' }).click();
  await page.locator('#param-mapping').fill('{"two":"2","many":null}');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await approve(page);
  await page.getByLabel('Operation', { exact: true }).selectOption('to_numeric');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await approve(page);
  const numeric = (await datasetGet(page, '/profile')).column_profiles.find(column => column.name === 'quantity');
  expect(numeric.numeric.finite_count).toBe(8);
  expect(numeric.numeric.min).toBe(-3);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(1);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await idle(page);
  expect((await datasetGet(page)).active_version).toBe(2);
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.getByText('No values or column types changed. No version will be created.')).toBeVisible();
  await expect(page.locator('#approval')).toBeDisabled();
  await page.getByLabel('Operation', { exact: true }).selectOption('to_date');
  await page.getByLabel('Target column').selectOption('order_date');
  await page.getByLabel('Date parsing mode').selectOption('supported');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.locator('#error')).toContainText('Ambiguous dates require');
  await page.getByLabel('Ambiguous day/month order').selectOption('day_first');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await approve(page);
  expect((await datasetGet(page)).active_version).toBe(3);
  await page.getByLabel('Operation', { exact: true }).selectOption('trim');
  await page.getByLabel('Target column').selectOption('city');
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await idle(page);
  await expect(page.getByRole('region', { name: 'Cleaning change preview' })).toContainText('\u2420\u2420Chennai\u2420');
  await navigate(page, 'quality');
  await page.getByLabel('Range check column').selectOption('discount_pct');
  await page.getByLabel('Expected minimum').fill('0');
  await page.getByLabel('Expected maximum').fill('100');
  await page.getByRole('button', { name: 'Check numeric range' }).click();
  await idle(page);
  await expect(page.getByText(/^Values violate the explicit domain minimum 0(?:\.0)?\.$/)).toBeVisible();
  await expect(page.getByText(/^Values violate the explicit domain maximum 100(?:\.0)?\.$/)).toBeVisible();
});

test('refinement themes: every section at desktop and mobile sizes', async ({ page }, testInfo) => {
  await ready(page);
  await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click();
  await idle(page);
  await ingest(page);
  for (const theme of ['light', 'dark']) {
    await page.locator('#theme-toggle').focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const section of ['upload', 'overview', 'quality', 'cleaning', 'exports']) {
        await navigate(page, section);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`${theme}-${width}-${section}.png`), animations: 'disabled' });
      }
    }
  }
});

test('offline API reference renders the live schema and filters local endpoints', async ({ page, baseURL }) => {
  const externalRequests = [];
  page.on('request', request => { if (new URL(request.url()).origin !== new URL(baseURL).origin) externalRequests.push(request.url()); });
  await page.goto('/static/api-docs.html');
  await expect(page.getByRole('heading', { name: 'Local API reference', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'GET /api/v1/health', exact: true })).toBeVisible();
  await page.getByLabel('Filter endpoints').fill('cleaning/apply');
  await expect(page.getByRole('heading', { name: 'POST /api/v1/datasets/{dataset_id}/cleaning/apply', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'GET /api/v1/health', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Download OpenAPI JSON' })).toHaveAttribute('href', '/openapi.json');
  expect(externalRequests).toEqual([]);
});
