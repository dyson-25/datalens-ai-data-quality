import { el, badge, button } from './ui.js';
const methods = new Set(['get', 'post', 'put', 'patch', 'delete', 'head', 'options']);
const status = document.querySelector('#schema-status');
let endpoints = [];
function details(title, value) {
  return el('details', { class: 'issue-card' }, el('summary', { class: 'table-action' }, title), el('pre', { class: 'code-block section-gap' }, JSON.stringify(value, null, 2)));
}
function renderEndpoints() {
  const query = document.querySelector('#endpoint-search').value.toLowerCase().trim();
  const filtered = endpoints.filter(({ path, method, operation }) => `${method} ${path} ${operation.summary || ''} ${operation.description || ''}`.toLowerCase().includes(query));
  document.querySelector('#endpoint-count').textContent = `${filtered.length} of ${endpoints.length} endpoints`;
  document.querySelector('#endpoint-list').replaceChildren(...filtered.map(({ path, method, operation, shared }) => el('article', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {}, el('h2', {}, `${method.toUpperCase()} ${path}`), el('p', {}, operation.summary || operation.operationId || 'Endpoint')), badge(method.toUpperCase(), method === 'get' ? 'success' : 'warning')),
    el('div', { class: 'panel-body stack' }, operation.description ? el('p', { class: 'muted' }, operation.description) : null,
      shared?.length || operation.parameters?.length ? details('Path, query, and header parameters', [...(shared || []), ...(operation.parameters || [])]) : null,
      operation.requestBody ? details('Request body', operation.requestBody) : null,
      details('Responses', operation.responses || {}),
      operation.security ? details('Security requirements', operation.security) : null))));
}
async function loadSchema() {
  status.textContent = 'Loading the server schema…';
  try {
    const response = await fetch('/openapi.json', { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error(`The schema request failed (${response.status}).`);
    const schema = await response.json();
    endpoints = Object.entries(schema.paths || {}).flatMap(([path, item]) => Object.entries(item).filter(([method]) => methods.has(method)).map(([method, operation]) => ({ path, method, operation, shared: item.parameters })));
    renderEndpoints();
    document.querySelector('#component-list').replaceChildren(...Object.entries(schema.components?.schemas || {}).map(([name, value]) => details(name, value)));
    status.textContent = `${schema.info?.title || 'DataLens'} · version ${schema.info?.version || 'unspecified'} · OpenAPI ${schema.openapi || ''}`;
  } catch (error) {
    status.replaceChildren(el('span', {}, error.message), button('Retry schema', loadSchema, 'secondary small'));
  }
}
document.querySelector('#endpoint-search').addEventListener('input', renderEndpoints);
loadSchema();
