export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'checked' || key === 'disabled' || key === 'selected') node[key] = Boolean(value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const paths = {
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5',
  overview: 'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z',
  quality: 'M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7zM8 12l3 3 5-6',
  cleaning: 'm15 3 6 6M13 5l6 6-10 10-6-6zM3 3v4m-2-2h4M20 17v4m-2-2h4',
  exports: 'M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  file: 'M14 2H5v20h14V7zm0 0v6h5M8 12h8m-8 4h8',
  refresh: 'M20 11a8 8 0 1 0-2 7M20 3v8h-8',
  check: 'm4 12 5 5L20 6'
};
export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'nav-icon'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', paths[name] || paths.file); svg.append(path); return svg;
}
export function button(text, action, style = '', attrs = {}) {
  return el('button', { type: 'button', class: `button ${style}`, onclick: action, ...attrs }, text);
}
export function badge(text, tone = '') { return el('span', { class: `badge ${tone}` }, text); }
export function heading(title, description, actions = [], eyebrow = 'YOUR DATA. A CLEARER PICTURE.') {
  return el('div', { class: 'page-header' }, el('div', {}, el('div', { class: 'eyebrow' }, eyebrow), el('h1', {}, title), el('p', {}, description)), el('div', { class: 'header-actions' }, actions));
}
export function panel(title, subtitle, body, action = null, cls = '') {
  return el('section', { class: `panel ${cls}` }, el('div', { class: 'panel-head' }, el('div', {}, el('h2', {}, title), subtitle ? el('p', {}, subtitle) : null), action), body);
}
export const fmt = value => typeof value === 'number' ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value) : '—';
export const pct = value => `${fmt(value)}%`;
export function valueText(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
export function table(columns, rows, { caption, rowClass } = {}) {
  return el('div', { class: 'table-scroll', tabindex: '0', role: 'region', 'aria-label': caption || 'Data table' },
    el('table', {}, caption ? el('caption', { class: 'sr-only' }, caption) : null,
      el('thead', {}, el('tr', {}, columns.map(name => el('th', { scope: 'col' }, name)))),
      el('tbody', {}, rows.length ? rows.map((row, index) => el('tr', { class: rowClass?.(index) || '' }, row.map(cell => el('td', { class: cell === null ? 'cell-null' : '', title: cell instanceof Node ? undefined : valueText(cell) }, cell instanceof Node ? cell : valueText(cell))))) : el('tr', {}, el('td', { colspan: columns.length }, 'No rows to display.')))));
}
export function field(label, control, help = '') {
  return el('div', { class: 'field' }, el('label', { for: control.id, class: 'field-label' }, label), control, help ? el('span', { class: 'field-help' }, help) : null);
}
export function select(id, options, value, change) {
  const control = el('select', { id, class: 'control', onchange: change }, options.map(option => {
    const [key, label] = Array.isArray(option) ? option : [option, option];
    return el('option', { value: key, selected: String(key) === String(value) }, label);
  }));
  return control;
}
export function input(id, value = '', attrs = {}) { return el('input', { id, class: 'control', value, ...attrs }); }
export function empty(title, description, action) { return el('div', { class: 'empty-state' }, icon('overview'), el('h2', {}, title), el('p', {}, description), action); }
export function metric(label, value, detail) { return el('div', { class: 'metric' }, el('div', { class: 'metric-label' }, label), el('strong', { class: 'metric-value' }, value), el('span', { class: 'metric-detail' }, detail)); }
export function confirmAction(title, message, action = 'Continue') {
  const dialog = document.querySelector('#confirmation');
  document.querySelector('#confirm-title').textContent = title;
  document.querySelector('#confirm-message').textContent = message;
  document.querySelector('#confirm-action').textContent = action;
  dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    dialog.showModal();
  });
}
