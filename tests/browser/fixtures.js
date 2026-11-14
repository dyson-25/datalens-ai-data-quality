import { test as base, expect } from '@playwright/test';

export const test = base.extend({
  browserEvidence: [async ({ context }, use, testInfo) => {
    const evidence = { consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: [] };
    const observe = page => {
      page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push(message.text()); });
      page.on('pageerror', error => evidence.pageErrors.push(error.message));
      page.on('requestfailed', request => evidence.failedRequests.push({ path: new URL(request.url()).pathname, method: request.method(), error: request.failure()?.errorText }));
      page.on('response', response => { if (response.status() >= 400) evidence.httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    };
    context.on('page', observe);
    for (const page of context.pages()) observe(page);
    await use(evidence);
    await testInfo.attach('browser-evidence', { body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: 'application/json' });
    expect(evidence.pageErrors, 'Uncaught browser errors').toEqual([]);
    expect(evidence.httpErrors.filter(item => item.status >= 500), 'Unexpected server failures').toEqual([]);
  }, { auto: true }]
});
export { expect };
