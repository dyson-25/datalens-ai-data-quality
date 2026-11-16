import { test, expect } from './fixtures.js';

const csv = 'name,amount,code,date,category\n Alice ,1,001,2024-01-01,A\nBob,,bad,invalid,B\nBob,,bad,invalid,B\nNA,100,003,2024-01-04,A\n';
async function idle(page) { await expect(page.locator('#main')).toHaveAttribute('aria-busy', 'false', { timeout: 90000 }); }
async function ready(page) { await page.goto('/'); await expect(page.getByText('Local engine connected')).toBeVisible(); await idle(page); }
async function request(page, suffix = '', body) {
  return page.evaluate(async ({ suffix, body }) => {
    const session = JSON.parse(sessionStorage.getItem('datalens.session'));
    const response = await fetch(`/api/v1/datasets/${session.dataset_id}${suffix}`, { method: body ? 'POST' : 'GET', headers: { 'X-Session-Token': session.token, ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new Error(`${suffix}: ${response.status}`);
    return response.json();
  }, { suffix, body });
}
async function upload(page, contents = csv, name = 'verification.csv') {
  await page.locator('input[type=file]').setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from(contents) });
  await idle(page);
}
async function ingest(page) {
  await page.getByRole('button', { name: 'Ingest dataset', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'A clearer view of your data.' })).toBeVisible();
  await idle(page); await expect(page.locator('#error')).toBeHidden();
}
async function choose(page, operation) {
  await page.getByRole('link', { name: /Cleaning studio/ }).click();
  await page.getByLabel('Operation', { exact: true }).selectOption(operation.kind);
  if (operation.kind !== 'drop_duplicates') await page.getByLabel('Target column').selectOption(operation.column);
  for (const [id, value] of Object.entries(operation.inputs || {})) {
    const control = page.locator(`#${id}`);
    if (typeof value === 'boolean') await control.setChecked(value);
    else if (await control.evaluate(node => node.tagName === 'SELECT')) await control.selectOption(value);
    else await control.fill(value);
  }
}
async function approve(page) {
  await page.getByLabel('I reviewed the operation, affected rows, and potential data loss. I approve this exact change.').check();
  await page.getByRole('button', { name: 'Approve & apply' }).click();
  const applied = page.waitForResponse(response => response.url().endsWith('/cleaning/apply') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Apply change', exact: true }).click();
  expect((await applied).ok()).toBe(true);
  await idle(page); await expect(page.locator('#error')).toBeHidden();
}
async function exportCsv(page) {
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  const event = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download CSV', exact: true }).click();
  const download = await event;
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  await idle(page);
  return { name: download.suggestedFilename(), text: Buffer.concat(chunks).toString('utf8') };
}

test.afterEach(async ({ page }) => {
  await page.evaluate(async () => {
    const session = JSON.parse(sessionStorage.getItem('datalens.session') || 'null');
    if (session) await fetch(`/api/v1/datasets/${session.dataset_id}`, { method: 'DELETE', headers: { 'X-Session-Token': session.token } });
  }).catch(() => {});
});

const cases = [
  { kind: 'trim', column: 'name', expected: ['Alice', 'Bob', 'Bob', 'NA'], changed: 1 },
  { kind: 'normalize_missing', column: 'name', inputs: { 'param-tokens': '["NA"]' }, expected: [' Alice ', 'Bob', 'Bob', null], changed: 1 },
  { kind: 'drop_duplicates', inputs: { 'param-rows': '2' }, ids: [0, 1, 3], changed: 1 },
  { kind: 'to_numeric', column: 'code', inputs: { 'param-coerce': true }, expected: [1, null, null, 3], changed: 4 },
  { kind: 'to_date', column: 'date', inputs: { 'param-format': '%Y-%m-%d', 'param-coerce': true }, expected: ['2024-01-01T00:00:00', null, null, '2024-01-04T00:00:00'], changed: 4 },
  { kind: 'fill_missing', column: 'amount', inputs: { 'param-strategy': 'constant', 'param-value': '0' }, expected: [1, 0, 0, 100], changed: 2 },
  { kind: 'drop_column', column: 'category', absent: 'category', changed: 4 },
  { kind: 'case', column: 'category', inputs: { 'param-mode': 'lower' }, expected: ['a', 'b', 'b', 'a'], changed: 4 },
  { kind: 'map_categories', column: 'category', inputs: { 'param-mapping': '{"A":"Alpha"}' }, expected: ['Alpha', 'B', 'B', 'Alpha'], changed: 2 },
  { kind: 'handle_infinity', column: 'amount', source: 'name,amount\nA,1\nB,2\nC,3\n', expected: [1, 2, 3], changed: 0 },
  { kind: 'outliers', column: 'amount', inputs: { 'param-rows': '3', 'param-action': 'clip', 'param-lower': '0', 'param-upper': '10' }, expected: [1, null, null, 10], changed: 1 }
];
for (const operation of cases) {
  test(`UI-${operation.kind}: ${operation.changed ? 'preview → approval → undo → redo → reset → refresh' : 'no-op preview preserves history'}`, async ({ page, browserEvidence }) => {
    await ready(page); await upload(page, operation.source || csv); await ingest(page);
    const original = await request(page, '/preview?limit=200');
    const baseline = await request(page, '/preview?limit=200');
    const metadata = await request(page);
    await choose(page, operation);
    await page.getByRole('button', { name: 'Preview changes' }).click(); await idle(page);
    await expect(page.getByRole('heading', { name: 'Review this exact change' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve & apply' })).toBeDisabled();
    await expect(page.locator('.preview-stats > div').nth(1).locator('strong')).toHaveText(String(operation.changed));
    expect(await request(page, '/preview?limit=200')).toEqual(baseline);
    expect((await request(page)).revision).toBe(metadata.revision);
    if (!operation.changed) {
      await expect(page.locator('#approval')).toBeDisabled();
      await expect(page.getByText('No values or column types changed. No version will be created.')).toBeVisible();
      await page.getByRole('button', { name: 'Discard preview' }).click();
      expect((await request(page, '/history')).versions).toHaveLength(1);
      await page.reload(); await idle(page);
      expect(await request(page, '/preview?limit=200')).toEqual(baseline);
      expect((await exportCsv(page)).name).toContain('-v0');
      expect(browserEvidence.failedRequests).toEqual([]);
      expect(browserEvidence.consoleErrors).toEqual([]);
      return;
    }
    await approve(page);
    const cleaned = await request(page, '/preview?limit=200');
    expect((await request(page)).active_version).toBe(metadata.active_version + 1);
    if (operation.expected) expect(cleaned.rows.map(row => row.values[cleaned.columns.indexOf(operation.column)])).toEqual(operation.expected);
    if (operation.ids) expect(cleaned.rows.map(row => row.row_id)).toEqual(operation.ids);
    if (operation.absent) expect(cleaned.columns).not.toContain(operation.absent);
    const history = await request(page, '/history');
    expect(history.versions).toHaveLength(metadata.active_version + 2);
    await page.getByRole('button', { name: 'Undo', exact: true }).click(); await idle(page);
    expect(await request(page, '/preview?limit=200')).toEqual(baseline);
    await page.getByRole('button', { name: 'Redo', exact: true }).click(); await idle(page);
    expect(await request(page, '/preview?limit=200')).toEqual(cleaned);
    await page.getByRole('button', { name: 'Reset to original', exact: true }).click();
    const reset = page.waitForResponse(response => response.url().endsWith('/reset') && response.request().method() === 'POST');
    await page.getByRole('dialog').getByRole('button', { name: /Reset/ }).click();
    expect((await reset).ok()).toBe(true); await idle(page);
    expect((await request(page)).active_version).toBe(0);
    expect((await request(page)).expires_at).toBe(metadata.expires_at);
    expect(await request(page, '/preview?limit=200')).toEqual(original);
    expect((await request(page, '/history')).versions).toHaveLength(metadata.active_version + 2);
    await page.reload(); await expect(page.getByText('Local engine connected')).toBeVisible(); await idle(page);
    await expect(page.locator('#error')).toBeHidden();
    expect((await exportCsv(page)).name).toContain('-v0');
    expect(browserEvidence.failedRequests).toEqual([]);
    expect(browserEvidence.consoleErrors).toEqual([]);
  });
}

test('UI-validation: invalid parameter forms and cancelled approval never change a snapshot', async ({ page }) => {
  await ready(page); await upload(page); await ingest(page);
  const baseline = await request(page, '/preview');
  const invalid = [
    { kind: 'normalize_missing', column: 'name', inputs: { 'param-tokens': '{}' }, error: /JSON array of strings/ },
    { kind: 'drop_duplicates', inputs: { 'param-rows': '-1' }, error: /non-negative integer/ },
    { kind: 'to_date', column: 'date', error: /explicit date format/ },
    { kind: 'fill_missing', column: 'amount', inputs: { 'param-strategy': 'constant', 'param-value': '[]' }, error: /JSON scalar/ },
    { kind: 'map_categories', column: 'category', inputs: { 'param-mapping': '{}' }, error: /nonempty JSON object/ },
    { kind: 'outliers', column: 'amount', inputs: { 'param-rows': '3', 'param-lower': '10', 'param-upper': '0' }, error: /finite lower and upper/ }
  ];
  for (const operation of invalid) {
    await choose(page, operation);
    await page.getByRole('button', { name: 'Preview changes' }).click(); await idle(page);
    await expect(page.locator('#error')).toContainText(operation.error);
    expect((await request(page)).active_version).toBe(0);
  }
  await choose(page, { kind: 'trim', column: 'name' });
  await page.getByRole('button', { name: 'Preview changes' }).click(); await idle(page);
  await page.getByLabel('I reviewed the operation, affected rows, and potential data loss. I approve this exact change.').check();
  await page.getByRole('button', { name: 'Approve & apply' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click(); await idle(page);
  expect(await request(page, '/preview')).toEqual(baseline);
  expect((await request(page, '/history')).versions).toHaveLength(1);
});

for (const scenario of [
  { name: 'no header', source: 'Alice,1\nBob,2\n', header: '', rows: [['Alice', 1], ['Bob', 2]] },
  { name: 'custom header', source: 'metadata,ignore\nname,value\nAlice,1\nBob,2\n', header: 'custom', rows: [['Alice', 1], ['Bob', 2]] },
  { name: 'duplicate headers', source: 'name,name\nAlice,1\nBob,2\n', header: '0', rows: [['Alice', 1], ['Bob', 2]] }
]) {
  test(`UI-header: ${scenario.name}`, async ({ page }) => {
    await ready(page); await upload(page, scenario.source);
    await page.getByLabel('Header row', { exact: true }).selectOption(scenario.header);
    if (scenario.header === 'custom') await page.getByLabel('Header row number').fill('2');
    await ingest(page);
    const preview = await request(page, '/preview');
    expect(preview.rows.map(row => row.values)).toEqual(scenario.rows);
    expect(preview.columns).toHaveLength(2);
    expect(new Set(preview.columns).size).toBe(2);
    expect(preview.columns.every(name => name.length > 0)).toBe(true);
    expect((await request(page)).active_version).toBe(0);
  });
}

test('UI-pagination: next/previous preserves every stable row ID', async ({ page }) => {
  await ready(page); await upload(page, 'name,value\n' + Array.from({ length: 57 }, (_, i) => `row${i},${i}`).join('\n') + '\n'); await ingest(page);
  const table = page.getByRole('table', { name: 'Dataset preview', exact: true });
  await expect(table.getByRole('row')).toHaveCount(26);
  await expect(table.getByRole('row').nth(1)).toHaveText(/0row00/);
  await page.getByRole('button', { name: 'Next rows' }).click(); await idle(page);
  await expect(table.getByRole('row').nth(1)).toHaveText(/25row2525/);
  await page.getByRole('button', { name: 'Next rows' }).click(); await idle(page);
  await expect(table.getByRole('row')).toHaveCount(8);
  await expect(table.getByRole('row').nth(1)).toHaveText(/50row5050/);
  await expect(page.getByRole('button', { name: 'Next rows' })).toBeDisabled();
  await page.getByRole('button', { name: 'Previous rows' }).click(); await idle(page);
  await expect(table.getByRole('row').nth(1)).toHaveText(/25row2525/);
});

test('UI-quality: combined filters and affected-row IDs match real findings', async ({ page }) => {
  await ready(page); await page.getByRole('button', { name: 'Explore sample: Quality Issues', exact: true }).click(); await idle(page); await ingest(page);
  const quality = await request(page, '/quality');
  const issues = quality.issues;
  const issue = issues.find(item => item.column === 'region' && /whitespace/.test(item.category));
  expect(issue.row_ids).toEqual([3, 8, 13, 18]);
  await page.getByRole('link', { name: /Quality & anomalies/ }).click();
  await page.getByLabel('Severities').selectOption(issue.severity);
  await page.getByLabel('Categories').selectOption(issue.category);
  await page.getByLabel('Columns', { exact: true }).selectOption(issue.column);
  const matches = issues.filter(item => item.severity === issue.severity && item.category === issue.category && item.column === issue.column);
  await expect(page.locator('.issue-card')).toHaveCount(matches.length);
  await page.locator('.issue-card').first().getByRole('button', { name: /Explore/ }).click(); await idle(page);
  const rows = page.getByRole('table', { name: 'Affected data rows', exact: true }).getByRole('row');
  await expect(rows).toHaveCount(issue.row_ids.length + 1);
  expect(await rows.allTextContents()).toEqual(expect.arrayContaining(issue.row_ids.map(id => expect.stringMatching(new RegExp(`^${id}`)))));
  expect((await request(page)).active_version).toBe(0);
});

test('UI-anomalies: IQR, MAD and isolation forest execute without transformations', async ({ page }) => {
  await ready(page); await page.getByRole('button', { name: 'Explore sample: Statistical Anomalies', exact: true }).click(); await idle(page); await ingest(page);
  const baseline = await request(page, '/preview');
  await page.getByRole('link', { name: /Quality & anomalies/ }).click();
  for (const method of ['iqr', 'mad', 'isolation_forest']) {
    await page.getByLabel('Detection method').selectOption(method);
    await page.getByRole('group', { name: 'Numeric columns' }).getByRole('checkbox').first().check();
    if (method === 'isolation_forest') await page.getByRole('group', { name: 'Numeric columns' }).getByRole('checkbox').nth(1).check();
    await page.getByRole('button', { name: 'Run anomaly detection' }).click(); await idle(page);
    await expect(page.locator('#anomaly-results')).toBeVisible();
    await expect(page.locator('#error')).toBeHidden();
    await expect(page.locator('#anomaly-results')).toContainText('FLAGGED');
  }
  expect(await request(page, '/preview')).toEqual(baseline);
  expect((await request(page, '/history')).versions).toHaveLength(1);
});

test('UI-sessions: cancelled switch, independent tab and accepted switch preserve the previous dataset', async ({ page, context }) => {
  await ready(page); await upload(page); await ingest(page);
  const first = await page.evaluate(() => JSON.parse(sessionStorage.getItem('datalens.session')));
  const other = await context.newPage(); await ready(other);
  expect(await other.evaluate(() => sessionStorage.getItem('datalens.session'))).toBeNull();
  await other.close();
  await page.getByRole('link', { name: /Upload & workspace/ }).click();
  await page.locator('input[type=file]').setInputFiles({ name: 'second.csv', mimeType: 'text/csv', buffer: Buffer.from('value\n42\n') });
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click(); await idle(page);
  expect((await request(page)).dataset_id).toBe(first.dataset_id);
  await page.locator('input[type=file]').setInputFiles({ name: 'second.csv', mimeType: 'text/csv', buffer: Buffer.from('value\n42\n') });
  await page.getByRole('dialog').getByRole('button', { name: /Switch/ }).click(); await idle(page); await ingest(page);
  expect((await request(page)).dataset_id).not.toBe(first.dataset_id);
  expect((await request(page, '/preview')).rows[0].values).toEqual([42]);
  const previous = await page.evaluate(async session => {
    const headers = { 'X-Session-Token': session.token };
    const response = await fetch(`/api/v1/datasets/${session.dataset_id}/preview`, { headers });
    const result = await response.json();
    await fetch(`/api/v1/datasets/${session.dataset_id}`, { method: 'DELETE', headers });
    return result;
  }, first);
  expect(previous.rows[0].values[0]).toBe(' Alice ');
});

test('UI-AI: disabled provider is visibly deterministic and leaves the dataset unchanged', async ({ page }) => {
  await ready(page); await upload(page); await ingest(page);
  const baseline = await request(page);
  await page.getByRole('link', { name: /Exports & reports/ }).click();
  await expect(page.getByText(/AI disabled/)).toBeVisible();
  await page.getByRole('button', { name: 'Explain aggregate quality' }).click(); await idle(page);
  await expect(page.locator('#error')).toBeHidden();
  await expect(page.getByText('deterministic', { exact: true })).toBeVisible();
  expect((await request(page)).revision).toBe(baseline.revision);
});

test('UI-export-filename: concurrent active-version change uses authoritative download version', async ({ page }) => {
  await ready(page); await upload(page); await ingest(page);
  const metadata = await request(page);
  const preview = await request(page, '/cleaning/preview', { operation: { kind: 'trim', column: 'name', params: {} }, expected_version: metadata.active_version, expected_revision: metadata.revision });
  await request(page, '/cleaning/apply', { preview_id: preview.preview_id, expected_version: metadata.active_version, expected_revision: metadata.revision, approved: true });
  const downloaded = await exportCsv(page);
  expect(downloaded.text).toContain('"Alice","1"');
  expect(downloaded.text).not.toContain(' Alice ');
  expect(downloaded.name).toContain('-v1');
});
