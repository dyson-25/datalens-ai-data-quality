import { api, datasetApi, getSession, setSession, delay } from './api.js';
import { el, icon, button, badge, heading, panel, fmt, pct, valueText, table, field, select, input, empty, metric, confirmAction } from './ui.js';
import { disposeCharts, resizeCharts, missingChart, typeChart, histogram, boxplot, categories, correlation, issueChart, anomalyChart, comparison } from './charts.js';

const views = [ ['upload', 'Upload & workspace'], ['overview', 'Overview & profiler'], ['quality', 'Quality & anomalies'], ['cleaning', 'Cleaning studio'], ['exports', 'Exports & reports'] ];
const state = {
  view: 'upload', busy: false, samples: [], samplesError: '', ai: null, meta: null,
  inspection: getSession()?.inspection || null, profile: null, issues: [], recommendations: [], history: null,
  preview: null, offset: 0, column: '', cleaningPreview: null, reviewedRevision: null,
  filters: { severity: '', category: '', column: '' }, anomalyResult: null, anomalyMethod: 'iqr', anomalyThreshold: '1.5', anomalyColumns: [],
  operation: { kind: 'trim', column: '', params: {} }, explorer: null,
  redoCount: getSession()?.redoCount || 0, job: getSession()?.job_id || null, jobStatus: '', explanation: null,
  domainDraft: { column: '', min: '', max: '' }, domainResult: null
};
const main = document.querySelector('#main');
const notice = document.querySelector('#notice');
const errorBox = document.querySelector('#error');
let retryAction = null;
let noticeTimer;

function scrollSection(selector) {
  document.querySelector(selector)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
}
function announce(message, loading = false) {
  clearTimeout(noticeTimer);
  notice.replaceChildren(loading ? el('span', { class: 'spinner', 'aria-hidden': 'true' }) : icon('check'), el('span', {}, message));
  notice.hidden = false;
  if (!loading) noticeTimer = setTimeout(() => { notice.hidden = true; }, 9000);
}
function showError(error, retry) {
  notice.hidden = true;
  retryAction = retry;
  errorBox.replaceChildren(el('span', {}, error.message || String(error)), ...(retry ? [button('Retry', () => retryAction?.(), 'small secondary')] : []), button('Dismiss', () => { errorBox.hidden = true; }, 'small ghost'));
  errorBox.hidden = false;
}
function setBusy(busy) {
  state.busy = busy;
  main.setAttribute('aria-busy', String(busy));
  for (const control of main.querySelectorAll('button, input, select, textarea')) {
    if (busy) { control.dataset.wasDisabled = String(control.disabled); control.disabled = true; }
    else { control.disabled = control.dataset.wasDisabled === 'true'; delete control.dataset.wasDisabled; }
  }
}
async function run(label, action, { retry = true } = {}) {
  if (state.busy) return;
  errorBox.hidden = true;
  setBusy(true); announce(label, true);
  try { await action(); announce('Workspace is up to date.'); }
  catch (error) {
    if (getSession() && (error.status === 404 || error.status === 410)) {
      // A missing report/column route must not discard an otherwise valid session.
      let unavailable = error.code === 'expired';
      if (!unavailable) {
        try { await datasetApi(); }
        catch (sessionError) { unavailable = sessionError.code === 'not_found' || sessionError.code === 'expired'; }
      }
      if (unavailable) {
        setSession(null); clearDatasetState(); state.inspection = null;
        render(); retry = false;
        error.message = 'This dataset session expired, was removed, or its access token is invalid. Upload the original file again (or reload the sample), then reapply reviewed changes before exporting. The cached workspace is no longer available on the server.';
      }
    }
    if (error.status === 409 && state.meta) {
      state.cleaningPreview = null;
      try { await refreshDataset(); render(); } catch { /* Preserve the actionable conflict error. */ }
      error.message = `${error.message} The workspace was refreshed. Review a new preview before applying changes.`;
    }
    showError(error, retry ? () => run(label, action, { retry }) : null);
  } finally { setBusy(false); }
}
function saveSession(extra = {}) {
  const current = getSession();
  if (current) setSession({ ...current, revision: state.meta?.revision, redoCount: state.redoCount, inspection: state.inspection, job_id: state.job, ...extra });
}
const expected = () => ({ expected_version: state.meta.active_version, expected_revision: state.meta.revision });
const isLoaded = () => Boolean(state.profile && state.meta?.active_version !== null);
function invalidatePreview() {
  state.cleaningPreview = null;
  document.querySelector('#cleaning-preview')?.remove();
}
function go(view) { location.hash = view; if (state.view === view) render(); }
function clearDatasetState() {
  state.meta = null; state.profile = null; state.preview = null; state.issues = []; state.recommendations = []; state.history = null;
  state.cleaningPreview = null; state.anomalyResult = null; state.explorer = null; state.explanation = null;
  state.offset = 0; state.column = ''; state.redoCount = 0; state.job = null; state.filters = { severity: '', category: '', column: '' };
  state.anomalyColumns = []; state.operation = { kind: 'trim', column: '', params: {} };
  state.domainDraft = { column: '', min: '', max: '' }; state.domainResult = null;
}
async function refreshDataset(attempt = 0) {
  // Frame-processing endpoints share a bounded backend semaphore; read them serially.
  const meta = await datasetApi();
  if (meta.active_version === null || meta.active_version < 0) { state.meta = meta; return; }
  const profile = await datasetApi('/profile');
  const issues = (await datasetApi('/quality')).issues;
  const recommendations = (await datasetApi('/recommendations')).recommendations;
  const preview = await datasetApi('/preview?offset=0&limit=25');
  const history = await datasetApi('/history');
  if (history.revision !== meta.revision || history.active_version !== meta.active_version) {
    if (attempt < 1) return refreshDataset(attempt + 1);
    throw new Error('The dataset changed while its profile was loading. Refresh again once other operations finish.');
  }
  Object.assign(state, { meta, profile, issues, recommendations, preview, history });
  state.offset = 0;
  if (!state.profile.column_profiles.some(c => c.name === state.column)) state.column = state.profile.column_profiles[0]?.name || '';
  if (!state.profile.column_profiles.some(c => c.name === state.operation.column)) state.operation.column = state.column;
  state.cleaningPreview = null; state.anomalyResult = null; state.explorer = null; state.explanation = null; state.domainResult = null;
  saveSession();
}
function render() {
  const focusId = main.contains(document.activeElement) ? document.activeElement.id : null;
  disposeCharts();
  document.querySelector('#navigation').replaceChildren(...views.map(([id, label], index) => el('a', { href: `#${id}`, class: `nav-item${state.view === id ? ' active' : ''}`, 'aria-current': state.view === id ? 'page' : undefined }, icon(id), el('span', {}, label), el('span', { class: 'nav-index', 'aria-hidden': 'true' }, `0${index + 1}`))));
  document.querySelector('#view-crumb').textContent = views.find(v => v[0] === state.view)?.[1] || 'Upload';
  document.querySelector('#dataset-chip').textContent = state.meta?.filename ? `${state.meta.filename}${isLoaded() ? ` · v${state.meta.active_version}` : ''}` : 'No dataset loaded';
  document.querySelector('#footer-version').textContent = isLoaded() ? `Snapshot v${state.meta.active_version} · revision ${state.meta.revision} · original preserved` : 'No data leaves your local workspace by default.';
  document.title = `DataLens · ${views.find(v => v[0] === state.view)?.[1] || 'Workspace'}`;
  if (state.view !== 'upload' && !isLoaded()) {
    main.replaceChildren(heading(views.find(v => v[0] === state.view)[1], 'A connected workspace, from first look to final export.'), panel('Start with a dataset', '', empty('Your next insight starts here', 'Upload a CSV or Excel workbook, or explore a built-in sample to unlock this workspace.', button('Go to upload', () => go('upload')))));
  } else main.replaceChildren(...({ upload: uploadView, overview: overviewView, quality: qualityView, cleaning: cleaningView, exports: exportsView }[state.view])());
  if (state.busy) setBusy(true);
  if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true });
}
function refreshButton() { return button([icon('refresh'), 'Refresh'], () => run('Refreshing the active snapshot…', async () => { await refreshDataset(); render(); }), 'secondary'); }

function uploadView() {
  const picker = input('file-input', '', { type: 'file', accept: '.csv,.xlsx', class: 'sr-only-input', 'aria-label': 'Choose CSV or Excel file', onchange: event => { const file = event.target.files?.[0]; if (file) uploadFile(file); } });
  const zone = el('div', { class: 'drop-zone', id: 'drop-zone', ondragover: event => { event.preventDefault(); if (!state.busy) zone.classList.add('dragging'); }, ondragleave: () => zone.classList.remove('dragging'), ondrop: event => {
    event.preventDefault(); zone.classList.remove('dragging');
    if (state.busy) return;
    if (event.dataTransfer.files.length !== 1) { showError(new Error('Drop one CSV or XLSX file at a time.')); return; }
    uploadFile(event.dataTransfer.files[0]);
  } }, el('div', { class: 'upload-symbol' }, icon('upload')), el('h2', {}, 'Make sense of your data.'), el('p', {}, 'Drag and drop your dataset here, or browse your files.'), picker,
    button(['Choose a file', icon('arrow')], () => picker.click()), el('p', { class: 'file-types' }, 'CSV or XLSX · Files are validated before processing'));
  const samples = state.samplesError ? empty('Samples are unavailable', state.samplesError, button('Retry samples', () => run('Loading sample datasets…', loadSamples), 'secondary')) : state.samples.length ? el('div', { class: 'sample-list' }, state.samples.map(sample => el('article', { class: 'sample-card' }, el('span', { class: 'sample-mark' }, icon('file')), el('div', {}, el('h3', {}, sample.name), el('p', {}, sample.description), button(['Explore sample', icon('arrow')], () => uploadSample(sample.id), '', { 'aria-label': `Explore sample: ${sample.name}` }))))) : el('p', { class: 'muted' }, state.busy ? 'Loading built-in datasets…' : 'No sample datasets are configured. Upload your own file to begin.');
  const nodes = [heading('Good data starts with a closer look.', 'Explore your dataset, uncover quality issues, and make confident changes — without losing the original.', isLoaded() ? [button('Open overview', () => go('overview'))] : [], 'WELCOME TO DATALENS'),
    el('div', { class: 'upload-grid' }, panel('Bring your data', 'One file. A complete understanding.', el('div', {}, zone, el('div', { class: 'upload-note' }, icon('quality'), 'Private capability access · Original file stays unchanged')), badge('CSV / XLSX')), panel('Try it with a sample', 'Real workflows. No setup required.', el('div', { class: 'panel-body' }, samples), badge('BUILT-IN', 'success')))
  ];
  if (state.inspection && state.meta) nodes.push(inspectionPanel());
  nodes.push(el('div', { class: 'steps' }, [ ['01 / UNDERSTAND', 'See the whole picture', 'Column profiles, distributions, missing values, and relationships — all in one place.'], ['02 / REFINE', 'Clean with confidence', 'Review every change before applying it. Undo, redo, or return to any saved version.'], ['03 / DELIVER', 'Take the next step', 'Export clean data, share a quality report, or reproduce your work with reference code.'] ].map(([n, title, text]) => el('article', { class: 'step-card' }, el('span', { class: 'step-number' }, n), el('h3', {}, title), el('p', {}, text)))));
  return nodes;
}
async function mayReplace() {
  if (!getSession()) return true;
  return confirmAction('Switch datasets?', 'The current dataset will remain on the server until it expires, but this tab will switch to the new dataset. Export any results you want to keep first.', 'Switch dataset');
}
async function uploadFile(file) {
  if (state.busy) return;
  if (!/\.(csv|xlsx)$/i.test(file.name)) { showError(new Error('Unsupported file type. Choose a .csv or .xlsx file.')); return; }
  if (file.size === 0) { showError(new Error('This file is empty. Choose a CSV or XLSX file containing data.')); return; }
  if (!await mayReplace()) return;
  run('Uploading and inspecting your file…', async () => { const body = new FormData(); body.append('file', file); acceptUpload(await api('/datasets/upload', { method: 'POST', body })); });
}
async function uploadSample(id) {
  if (state.busy || !await mayReplace()) return;
  run('Preparing the sample dataset…', async () => acceptUpload(await api(`/datasets/sample/${encodeURIComponent(id)}`, { method: 'POST' })));
}
function acceptUpload(result) {
  clearDatasetState(); state.meta = { dataset_id: result.dataset_id, filename: result.filename, active_version: result.active_version ?? null, revision: result.revision ?? 0 };
  state.inspection = result.inspection;
  setSession({ dataset_id: result.dataset_id, token: result.token, filename: result.filename, inspection: result.inspection });
  render(); scrollSection('#ingest-panel');
}
function inspectionPanel() {
  const info = state.inspection;
  const sheets = (info.sheets || []).map(s => typeof s === 'string' ? s : s.name);
  const isExcel = String(info.format).toLowerCase().includes('xls');
  const controls = el('div', { class: 'form-grid' },
    field('Worksheet', select('ingest-sheet', sheets.length ? sheets : [['', 'Not applicable to CSV']], sheets[0], null), isExcel ? 'Select the worksheet to analyze.' : 'CSV files have a single table.'),
    field('Header row', select('ingest-header', [['0', 'First row contains column names'], ['', 'No header — generate column names'], ['custom', 'Choose a header row…']], info.has_header === false ? '' : '0', event => { document.querySelector('#header-row-field').hidden = event.target.value !== 'custom'; })),
    el('div', { id: 'header-row-field', hidden: true }, field('Header row number', input('header-row', '1', { type: 'number', min: '1', step: '1' }), '1 means the first row; preceding rows are skipped.')),
    field('Text encoding', select('ingest-encoding', [['', 'Automatic detection'], ['utf-8', 'UTF-8'], ['utf-8-sig', 'UTF-8 with BOM'], ['latin-1', 'Latin-1'], ['cp1252', 'Windows-1252'], ['utf-16', 'UTF-16']], isExcel ? '' : info.encoding || ''), 'CSV only. Choose explicitly if accented characters look incorrect.'),
    field('Delimiter', select('ingest-delimiter', [['', 'Automatic detection'], [',', 'Comma (,)'], [';', 'Semicolon (;)'], ['\t', 'Tab'], ['|', 'Pipe (|)']], isExcel ? '' : info.delimiter || ''), 'CSV only. Used when the dataset is ingested.'));
  controls.querySelector('#ingest-sheet').disabled = !isExcel;
  controls.querySelector('#ingest-encoding').disabled = isExcel;
  controls.querySelector('#ingest-delimiter').disabled = isExcel;
  let preview = info.preview;
  let previewNode;
  if (preview?.columns && preview?.rows) {
    const rows = preview.rows.map(r => Array.isArray(r) ? r : r.values || preview.columns.map(c => r[c]));
    previewNode = table(preview.columns, rows, { caption: 'Initial file inspection preview' });
  } else if (Array.isArray(preview) && preview.length) {
    const first = preview[0];
    if (Array.isArray(first)) previewNode = table(first.map((_, i) => `Field ${i + 1}`), preview, { caption: 'Raw file preview including possible header row' });
    else previewNode = table(Object.keys(first), preview.map(row => Object.values(row)), { caption: 'Initial file inspection preview' });
  } else previewNode = el('p', { class: 'muted panel-body' }, 'The full data preview will be available after ingestion.');
  return panel(`Configure · ${state.meta.filename}`, 'Inspect the source, then create an immutable baseline snapshot.', el('div', {}, el('div', { class: 'panel-body' }, controls,
    Array.isArray(info.warnings) ? info.warnings.map(w => el('p', { class: 'warning-box section-gap' }, valueText(w))) : null,
    el('div', { class: 'button-row section-gap' }, button(isLoaded() ? 'Dataset already ingested' : state.job ? 'Check ingestion job' : 'Ingest dataset', () => run('Ingesting your dataset…', ingest), '', { disabled: isLoaded(), id: 'ingest-button' }), el('span', { class: 'muted' }, isLoaded() ? 'Upload the source again to choose different parsing options.' : 'No cleaning changes are applied during ingestion.'))),
    state.jobStatus ? el('div', { class: 'job-status', role: 'status' }, el('span', { class: 'spinner', 'aria-hidden': 'true' }), state.jobStatus) : null,
    previewNode), badge(String(info.format || 'FILE').toUpperCase()), 'section-gap');
}
async function ingest() {
  if (!state.job) {
    const headerValue = document.querySelector('#ingest-header').value;
    const header = headerValue === '' ? null : headerValue === 'custom' ? Number(document.querySelector('#header-row').value) - 1 : 0;
    if (header !== null && (!Number.isInteger(header) || header < 0)) throw new Error('Header row must be a positive whole number.');
    const body = { sheet: document.querySelector('#ingest-sheet').value || null, header, delimiter: document.querySelector('#ingest-delimiter').value || null, encoding: document.querySelector('#ingest-encoding').value || null };
    state.job = (await datasetApi('/ingest', { method: 'POST', body })).job_id;
    saveSession();
  }
  await pollJob();
}
async function pollJob() {
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    const result = await datasetApi(`/jobs/${encodeURIComponent(state.job)}`);
    state.jobStatus = result.status === 'queued' ? 'Queued — waiting for the analysis engine…' : 'Processing — creating your baseline snapshot…';
    if (result.status === 'succeeded') {
      state.job = null; state.jobStatus = ''; saveSession();
      await refreshDataset(); go('overview'); render(); return;
    }
    if (['failed', 'timed_out'].includes(result.status)) {
      state.job = null; state.jobStatus = ''; saveSession(); render();
      throw new Error(typeof result.error === 'string' ? result.error : result.error?.message || 'Ingestion failed. Review the file and parsing options, then try again.');
    }
    announce(state.jobStatus, true);
    await delay(850);
  }
  state.jobStatus = 'The job is still running. Use “Check ingestion job” to reconnect.'; render();
  throw new Error('Processing is taking longer than expected. The job has not been cancelled; retry to check its status.');
}

function overviewView() {
  const p = state.profile;
  const selected = p.column_profiles.find(c => c.name === state.column) || p.column_profiles[0];
  const inventory = table(['Column', 'Semantic type', 'Missing', 'Distinct', 'Storage'], p.column_profiles.map(c => [button(c.name, () => { state.column = c.name; render(); scrollSection('#column-detail'); }, 'ghost small table-action'), badge(c.semantic_type), `${fmt(c.missing_count)} (${pct(c.missing_percentage)})`, fmt(c.distinct_count), c.storage_type]), { caption: 'Column inventory' });
  const nodes = [heading('A clearer view of your data.', `${state.meta.filename} · Profiled from the active snapshot. Every chart reflects your actual data.`, [refreshButton(), button('Investigate quality', () => go('quality'))], 'OVERVIEW & PROFILER'),
    el('div', { class: 'metrics' }, metric('TOTAL ROWS', fmt(p.rows), 'Stable row IDs across transformations'), metric('COLUMNS', fmt(p.columns), `${fmt(p.empty_columns?.length ?? 0)} empty · ${fmt(p.constant_columns?.length ?? 0)} constant`), metric('MISSING CELLS', pct(p.missing_percentage), `${fmt(p.missing_cells)} of ${fmt(p.total_cells)} cells`), metric('DUPLICATE ROWS', fmt(p.duplicate_rows), `${fmt(p.memory_bytes / 1024)} KB in memory`)),
    el('div', { class: 'two-col' }, panel('Missingness by column', 'Up to 18 columns with the highest missing percentages.', missingChart(p)), panel('Dataset composition', 'Semantic column types in this snapshot.', typeChart(p))),
    panel('Column inventory', 'Select a column to explore its distribution and statistics.', inventory, badge(`${fmt(p.columns)} COLUMNS`), 'section-gap')
  ];
  if (selected) nodes.push(columnDetail(selected));
  nodes.push(panel('Relationships between numeric columns', 'Pearson correlation · Undefined correlations are omitted. Correlation does not imply causation.', correlation(p), null, 'section-gap'), dataPreviewPanel());
  return nodes;
}
function columnDetail(c) {
  const numeric = c.numeric;
  const stats = numeric ? Object.entries(numeric).filter(([key, value]) => !['histogram', 'percentiles'].includes(key) && (value === null || typeof value !== 'object')) : [];
  const detail = panel('Column explorer', 'Choose a column; inspect numeric, categorical, or date signals.', el('div', { class: 'panel-body' },
    field('Profiled column', select('profile-column', state.profile.column_profiles.map(p => p.name), c.name, event => { state.column = event.target.value; render(); })),
    el('div', { class: 'metrics section-gap' }, metric('PRESENT', fmt(c.non_null_count), 'Non-null values'), metric('MISSING', pct(c.missing_percentage), `${fmt(c.missing_count)} cells`), metric('DISTINCT', fmt(c.distinct_count), pct(c.distinct_percentage)), metric('TYPE', c.semantic_type, c.storage_type)),
    numeric ? el('div', { class: 'two-col' }, panel('Numeric distribution', 'Frequency by interval.', histogram(c)), panel('Five-number summary', 'Whiskers show minimum and maximum, not IQR fences.', boxplot(c))) : null,
    el('div', { class: 'two-col section-gap' }, panel('Most frequent values', 'Top returned values, including numeric or date values.', categories(c)), panel(numeric ? 'Descriptive statistics' : c.dates ? 'Date analysis' : 'Column details', 'Calculated from this version only.', numeric ? table(['Statistic', 'Value'], stats.map(([key, value]) => [humanize(key), value === null ? null : fmt(value)])) : el('div', { class: 'panel-body' }, objectDetails(c.dates || c.categorical || { semantic_type: c.semantic_type, non_null_count: c.non_null_count, distinct_count: c.distinct_count })))),
    el('div', { class: 'section-gap' }, el('h3', {}, 'Sample values'), el('p', { class: 'muted', style: 'margin-top:8px;overflow-wrap:anywhere' }, (c.samples || []).map(valueText).join(' · ') || 'No non-null sample values.'))), badge(c.semantic_type), 'section-gap');
  detail.id = 'column-detail'; return detail;
}
function objectDetails(object) {
  return table(['Metric', 'Value'], Object.entries(object).map(([key, value]) => [humanize(key), typeof value === 'object' ? valueText(value) : value]), { caption: 'Profile metrics' });
}
function humanize(value) { return String(value || '').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
function dataPreviewPanel() {
  const data = state.preview;
  return panel('Data preview', 'Row IDs are stable identifiers, not data columns. Null cells are marked explicitly.', el('div', {}, data ? table(['Row ID', ...data.columns], data.rows.map(r => [r.row_id, ...r.values]), { caption: 'Dataset preview' }) : empty('No preview', 'Refresh the workspace to load rows.'),
    el('div', { class: 'pager' }, el('span', {}, data?.total ? `${fmt(state.offset + 1)}–${fmt(Math.min(state.offset + data.rows.length, data.total))} of ${fmt(data.total)} rows` : '0 rows'), el('div', { class: 'button-row' }, button('Previous rows', () => paginate(-25), 'secondary small', { disabled: state.offset === 0 }), button('Next rows', () => paginate(25), 'secondary small', { disabled: !data || state.offset + data.rows.length >= data.total })))), badge(`v${state.meta.active_version}`), 'section-gap');
}
function paginate(delta) { run('Loading data rows…', async () => { const offset = Math.max(0, state.offset + delta); state.preview = await datasetApi(`/preview?offset=${offset}&limit=25`); state.offset = offset; render(); }); }

function qualityView() {
  const issues = state.domainResult?.issues || state.issues;
  const filtered = issues.filter(issue => (!state.filters.severity || issue.severity === state.filters.severity) && (!state.filters.category || issue.category === state.filters.category) && (!state.filters.column || issue.column === state.filters.column));
  const filter = (key, label, values) => field(label, select(`filter-${key}`, [['', `All ${label.toLowerCase()}`], ...[...new Set(values.filter(v => v != null))].sort()], state.filters[key], event => { state.filters[key] = event.target.value; render(); }));
  const nodes = [heading('Find the signal. Question the unusual.', 'Explainable quality checks and statistical anomaly detection. Findings are prompts for review, not automatic deletions.', [refreshButton(), button('Open cleaning studio', () => go('cleaning'))], 'QUALITY & ANOMALY LAB'),
    el('div', { class: 'metrics' }, metric('QUALITY FINDINGS', fmt(issues.length), 'Counts can overlap across categories'), metric('HIGH / CRITICAL', fmt(issues.filter(i => ['high', 'critical'].includes(i.severity)).length), 'Prioritize a closer review'), metric('REVIEW REQUIRED', fmt(issues.filter(i => i.human_review).length), 'Context matters before changing data'), metric('RECOMMENDATIONS', fmt(state.recommendations.length), 'Every change requires your approval')),
    el('div', { class: 'two-col' }, panel('Quality signals', 'Affected record counts can overlap; not a unique-row total.', issueChart(issues)), anomalyControls()),
    domainControls(),
    panel('Findings', 'Filter, understand the method, and explore the affected rows.', el('div', { class: 'panel-body' }, el('div', { class: 'filter-bar' }, filter('severity', 'Severities', issues.map(i => i.severity)), filter('category', 'Categories', issues.map(i => i.category)), filter('column', 'Columns', issues.map(i => i.column))),
      el('div', { class: 'stack' }, filtered.length ? filtered.map(issueCard) : empty('No matching findings', issues.length ? 'Try changing your filters.' : 'The configured checks found no issues. This is not a guarantee of domain correctness.'))), badge(`${filtered.length} FINDINGS`), 'section-gap')];
  if (state.anomalyResult) nodes.push(anomalyResults());
  if (state.explorer) nodes.push(explorerPanel());
  return nodes;
}
function domainControls() {
  const numeric = state.profile.column_profiles.filter(c => c.numeric).map(c => c.name);
  const draft = state.domainDraft;
  if (!numeric.includes(draft.column)) draft.column = numeric[0] || '';
  return panel('Optional domain range check', 'Apply your knowledge: set an expected minimum, maximum, or both for a numeric column. This is analysis only.', el('div', { class: 'panel-body' },
    el('div', { class: 'filter-bar' }, field('Range check column', select('domain-column', numeric.length ? numeric : [['', 'No numeric columns']], draft.column, event => { draft.column = event.target.value; })),
      field('Expected minimum', input('domain-min', draft.min, { type: 'number', step: 'any', placeholder: 'Optional', oninput: event => { draft.min = event.target.value; } })),
      field('Expected maximum', input('domain-max', draft.max, { type: 'number', step: 'any', placeholder: 'Optional', oninput: event => { draft.max = event.target.value; } })),
      button('Check numeric range', () => run('Checking your explicit numeric range…', async () => {
        const bounds = {};
        for (const key of ['min', 'max']) if (draft[key] !== '') {
          const value = Number(draft[key]);
          if (!Number.isFinite(value)) throw new Error('Range bounds must be finite numbers.');
          bounds[key] = value;
        }
        if (!Object.keys(bounds).length) throw new Error('Enter at least one expected bound.');
        if (bounds.min !== undefined && bounds.max !== undefined && bounds.min > bounds.max) throw new Error('Expected minimum cannot exceed expected maximum.');
        const result = await datasetApi('/quality', { method: 'POST', body: { domain_rules: { [draft.column]: bounds } } });
        state.domainResult = { ...result, column: draft.column, bounds }; state.filters = { severity: '', category: '', column: '' }; render();
      }), 'secondary', { disabled: !numeric.length })),
    state.domainResult ? el('div', { class: 'info-box' }, `Findings below include the range check for ${state.domainResult.column}: ${valueText(state.domainResult.bounds)}. Dataset and versions are unchanged. These ad-hoc rules are not included in standard exports.`, button('Clear range results', () => { state.domainResult = null; render(); }, 'ghost small')) : el('p', { class: 'muted' }, 'One column per check. Empty bounds are omitted. Results are cleared when you refresh or change the active version.')), badge('NO DATA CHANGES', 'success'), 'section-gap');
}
function issueCard(issue) {
  return el('article', { class: 'issue-card' }, el('div', { class: 'issue-heading' }, el('h3', {}, `${humanize(issue.category)}${issue.column != null ? ` · ${issue.column}` : ' · Dataset'}`), badge(issue.severity, issue.severity)),
    el('p', {}, issue.explanation), el('div', { class: 'issue-meta' }, badge(issue.method || 'Quality check'), el('span', {}, `${fmt(issue.count)} affected records`), issue.confidence != null ? el('span', {}, `Confidence: ${typeof issue.confidence === 'number' ? pct(issue.confidence * 100) : issue.confidence}`) : null, issue.human_review ? el('span', {}, 'Human review required') : null),
    el('p', {}, typeof issue.suggestion === 'object' ? valueText(issue.suggestion) : issue.suggestion),
    el('div', { class: 'issue-actions' }, button('Explore affected rows', () => exploreRows(issue.row_ids || [], `${humanize(issue.category)}${issue.column ? ` · ${issue.column}` : ''}`, issue.count), 'secondary small', { disabled: !issue.row_ids?.length }), el('span', { class: 'muted' }, `${fmt(issue.row_ids?.length || 0)} returned row IDs`)));
}
function anomalyControls() {
  const numeric = state.profile.column_profiles.filter(c => c.numeric).map(c => c.name);
  const columns = el('div', { class: 'field' }, el('span', { class: 'field-label', id: 'anomaly-columns-label' }, 'Numeric columns'), el('div', { role: 'group', 'aria-labelledby': 'anomaly-columns-label', style: 'display:flex;flex-wrap:wrap;gap:10px;max-height:120px;overflow:auto' }, numeric.length ? numeric.map(name => el('label', { class: 'check-field' }, el('input', { type: 'checkbox', checked: state.anomalyColumns.includes(name), onchange: event => { state.anomalyColumns = event.target.checked ? [...state.anomalyColumns, name] : state.anomalyColumns.filter(c => c !== name); } }), name)) : el('p', { class: 'muted' }, 'No numeric columns are available.')));
  return panel('Statistical anomaly detection', 'Unusual does not mean incorrect. Always review in context.', el('div', { class: 'panel-body stack', style: 'gap:15px' }, el('div', { class: 'form-grid' },
    field('Detection method', select('anomaly-method', [['iqr', 'IQR fences'], ['mad', 'Median absolute deviation'], ['isolation_forest', 'Isolation forest']], state.anomalyMethod, event => { state.anomalyMethod = event.target.value; state.anomalyThreshold = state.anomalyMethod === 'iqr' ? '1.5' : '3.5'; render(); })),
    field('Threshold', input('anomaly-threshold', state.anomalyThreshold, { type: 'number', min: '0.01', step: '0.1', disabled: state.anomalyMethod === 'isolation_forest', oninput: event => { state.anomalyThreshold = event.target.value; } }), state.anomalyMethod === 'isolation_forest' ? 'Isolation forest ignores this threshold.' : 'IQR default 1.5; MAD default 3.5.')), columns,
    button('Run anomaly detection', () => run('Calculating statistical anomalies…', async () => {
      if (!state.anomalyColumns.length) throw new Error('Select at least one numeric column.');
      const threshold = Number(state.anomalyThreshold);
      if (state.anomalyMethod !== 'isolation_forest' && (!Number.isFinite(threshold) || threshold <= 0)) throw new Error('Enter a positive anomaly threshold.');
      state.anomalyResult = await datasetApi('/anomalies', { method: 'POST', body: { method: state.anomalyMethod, columns: state.anomalyColumns, threshold } }); render(); scrollSection('#anomaly-results');
    }), 'secondary', { disabled: !numeric.length })));
}
function anomalyResults() {
  const result = state.anomalyResult;
  const node = panel('Anomaly results', `${humanize(result.method)} · Plot includes only returned flagged values. Different columns may use different scales.`, el('div', {}, anomalyChart(result), el('div', { class: 'panel-body stack' },
    (result.warnings || []).map(w => el('div', { class: 'warning-box' }, valueText(w))),
    result.findings?.length ? result.findings.map(finding => el('article', { class: 'issue-card' }, el('div', { class: 'issue-heading' }, el('h3', {}, finding.column || 'Multivariate result'), badge(`${fmt(finding.count)} FLAGGED`, 'warning')), el('p', {}, finding.explanation), el('pre', { class: 'code-block' }, JSON.stringify(finding.thresholds, null, 2)), button('Explore anomaly rows', () => exploreRows(finding.row_ids || [], finding.column || 'Anomaly rows', finding.count), 'secondary small', { disabled: !finding.row_ids?.length }))) : empty('No anomalies returned', 'No records matched this method and threshold.'))), null, 'section-gap');
  node.id = 'anomaly-results'; return node;
}
function exploreRows(rowIds, title, total) {
  run('Locating affected records…', async () => {
    state.explorer = { ids: [...new Set(rowIds)], title, total, rows: [], columns: state.preview.columns, scanned: 0, datasetTotal: state.profile.rows };
    await scanRows(); render(); scrollSection('#row-explorer');
  });
}
async function scanRows() {
  const explorer = state.explorer;
  const wanted = new Set(explorer.ids);
  for (let pages = 0; pages < 5 && explorer.scanned < explorer.datasetTotal && explorer.rows.length < wanted.size; pages++) {
    const page = await datasetApi(`/preview?offset=${explorer.scanned}&limit=200`);
    explorer.columns = page.columns; explorer.datasetTotal = page.total;
    explorer.rows.push(...page.rows.filter(row => wanted.has(row.row_id)));
    explorer.scanned += page.rows.length;
    if (!page.rows.length) break;
  }
}
function explorerPanel() {
  const e = state.explorer;
  const node = panel(`Affected row explorer · ${e.title}`, `${fmt(e.total)} findings in total; ${fmt(e.ids.length)} stable row IDs supplied by the API. Original IDs can have gaps.`, el('div', {}, el('div', { class: 'panel-body' },
    el('p', { class: 'muted', style: 'overflow-wrap:anywhere' }, `Returned row IDs: ${e.ids.join(', ')}`)), table(['Row ID', ...e.columns], e.rows.map(r => [r.row_id, ...r.values]), { caption: 'Affected data rows' }),
    el('div', { class: 'pager' }, el('span', {}, `${fmt(e.rows.length)} matching rows found · scanned ${fmt(e.scanned)} of ${fmt(e.datasetTotal)} records`), button('Search next 1,000 rows', () => run('Searching the next rows…', async () => { await scanRows(); render(); }), 'secondary small', { disabled: e.scanned >= e.datasetTotal || e.rows.length >= e.ids.length }))), button('Close explorer', () => { state.explorer = null; render(); }, 'ghost small'), 'section-gap');
  node.id = 'row-explorer'; return node;
}

const operations = [ ['trim', 'Trim whitespace'], ['normalize_missing', 'Normalize missing tokens'], ['drop_duplicates', 'Remove selected duplicate rows'], ['to_numeric', 'Convert to numeric'], ['to_date', 'Parse dates'], ['fill_missing', 'Fill missing values'], ['drop_column', 'Drop a column'], ['case', 'Normalize letter case'], ['map_categories', 'Map category values'], ['handle_infinity', 'Replace infinity with null'], ['outliers', 'Handle selected outliers'] ];
function cleaningView() {
  const active = state.history?.versions.find(v => v.version === state.meta.active_version);
  return [heading('Make changes. Keep your confidence.', 'Preview the exact operation, inspect its effects, then approve. Your original snapshot is always preserved.', [
    button('Undo', () => navigateVersion('undo'), 'secondary', { disabled: active?.parent == null, id: 'undo-button' }), button('Redo', () => navigateVersion('redo'), 'secondary', { disabled: state.redoCount === 0, id: 'redo-button' }), button('Reset to original', () => navigateVersion('reset'), 'danger', { disabled: state.meta.active_version === 0 })
  ], 'CLEANING STUDIO'),
    el('div', { class: 'info-box', style: 'margin-bottom:22px' }, `Working on snapshot v${state.meta.active_version}, revision ${state.meta.revision}. Previewing never modifies the dataset. Approval applies only the server-held operation you reviewed.`),
    el('div', { class: 'studio-grid' }, panel('Suggested next steps', 'Recommendations inform your decision; they do not run automatically.', el('div', { class: 'panel-body recommendation-list' }, state.recommendations.length ? state.recommendations.map(recommendationCard) : empty('No recommendations', 'You can still use custom operations to refine your data.')), badge(`${state.recommendations.length}`)),
      el('div', { class: 'stack' }, operationPanel(), state.cleaningPreview ? cleaningPreviewPanel() : panel('Review before you commit', '', empty('Nothing has changed yet', 'Select a suggestion or configure a custom operation. A preview will show its exact impact.')))),
    historyPanel()];
}
function recommendationCard(rec) {
  return el('article', { class: 'recommendation' }, el('div', { class: 'issue-heading' }, el('h3', {}, `${humanize(rec.operation.kind)}${rec.column != null ? ` · ${rec.column}` : ''}`), rec.potential_data_loss ? badge('REVIEW', 'warning') : badge('SUGGESTED')),
    el('p', {}, rec.reason), el('p', {}, rec.expected_benefit), el('div', { class: 'issue-meta' }, el('span', {}, `${fmt(rec.affected_records)} affected records`), el('span', {}, rec.potential_data_loss ? 'Potential data loss' : 'Review still required')),
    rec.tradeoffs ? el('p', { class: 'tradeoff' }, Array.isArray(rec.tradeoffs) ? rec.tradeoffs.join(' · ') : valueText(rec.tradeoffs)) : null,
    button('Review suggestion', () => { state.operation = structuredClone(rec.operation); state.operation.column ??= state.column; state.cleaningPreview = null; render(); scrollSection('#operation-panel'); }, 'secondary small'));
}
function operationPanel() {
  const op = state.operation;
  const wholeDataset = op.kind === 'drop_duplicates';
  const kind = select('operation-kind', operations, op.kind, event => { state.operation = { kind: event.target.value, column: state.operation.column || state.column, params: {} }; state.cleaningPreview = null; render(); });
  const column = select('operation-column', state.profile.column_profiles.map(c => c.name), op.column || state.column, event => { state.operation.column = event.target.value; invalidatePreview(); });
  column.disabled = wholeDataset;
  const node = panel('Custom operation', 'Make the target and every parameter explicit.', el('div', { class: 'panel-body' },
    el('div', { class: 'form-grid' }, field('Operation', kind), field('Target column', column, wholeDataset ? 'Duplicates are compared across the entire row.' : 'Choose the column this operation will change.')),
    el('div', { class: 'operation-params', id: 'operation-params' }, operationParams()),
    button(['Preview changes', icon('arrow')], () => run('Computing a non-destructive preview…', previewOperation), '', { id: 'preview-operation' })));
  node.id = 'operation-panel'; return node;
}
function operationParams() {
  const { kind, params: p = {} } = state.operation;
  const update = (key, value) => { state.operation.params[key] = value; invalidatePreview(); };
  const paramInput = (key, id, value, attrs = {}) => input(id, value, { ...attrs, oninput: event => update(key, event.target.value) });
  const paramSelect = (key, id, options, value, rerender = false) => select(id, options, value, event => { update(key, event.target.value); if (rerender) render(); });
  const coerce = () => el('label', { class: 'check-field' }, el('input', { id: 'param-coerce', type: 'checkbox', checked: p.coerce === true, onchange: event => update('coerce', event.target.checked) }), 'Coerce invalid values to null (potential data loss). Leave unchecked to fail on invalid values.');
  const rowIds = () => field('Explicit row IDs', paramInput('row_ids', 'param-rows', Array.isArray(p.row_ids) ? p.row_ids.join(', ') : p.row_ids || '', { placeholder: 'For example: 2, 7, 18' }), 'Stable row IDs only, separated by commas. Find them in the Quality Lab row explorer. No rows are selected automatically.');
  if (kind === 'normalize_missing') return [field('Missing tokens (JSON array)', el('textarea', { id: 'param-tokens', class: 'control', oninput: event => update('tokens', event.target.value) }, typeof p.tokens === 'string' ? p.tokens : JSON.stringify(p.tokens || ['', 'NA', 'N/A', 'null'])), 'Exact string tokens to replace with null, e.g. ["", "NA"]. This is an explicit transformation.')];
  if (kind === 'drop_duplicates') return [rowIds(), el('div', { class: 'warning-box' }, 'Only the duplicate row IDs you explicitly select will be removed. The engine validates each selection.')];
  if (kind === 'to_numeric') return [coerce(), el('p', { class: 'muted' }, 'Converting identifiers can remove leading zeros. Review the preview before approval.')];
  if (kind === 'to_date') return [field('Date format', paramInput('format', 'param-format', p.format || '', { placeholder: '%Y-%m-%d' }), 'Explicit strptime format, e.g. %Y-%m-%d or %d/%m/%Y. Ambiguous dates are never guessed.'), coerce()];
  if (kind === 'fill_missing') return [field('Fill strategy', paramSelect('strategy', 'param-strategy', ['median', 'mean', 'mode', 'constant'], p.strategy || 'median', true)), (p.strategy === 'constant') ? field('Constant value (JSON scalar)', input('param-value', state.operation.constantDraft ?? JSON.stringify(p.value === undefined ? 'Unknown' : p.value), { oninput: event => { state.operation.constantDraft = event.target.value; invalidatePreview(); } }), 'Use a JSON string ("Unknown"), number (0), or boolean (false).') : el('p', { class: 'muted' }, 'The fill value is calculated from the active snapshot. Mean and median require numeric data.')];
  if (kind === 'case') return [field('Letter case', paramSelect('mode', 'param-mode', ['lower', 'upper', 'title'], p.mode || 'lower'))];
  if (kind === 'map_categories') return [field('Category mapping (JSON object)', el('textarea', { id: 'param-mapping', class: 'control', placeholder: '{"NY": "New York", "ny": "New York"}', oninput: event => update('mapping', event.target.value) }, typeof p.mapping === 'string' ? p.mapping : JSON.stringify(p.mapping || {}, null, 2)), 'Map exact old values to replacement values. Unlisted categories stay unchanged.')];
  if (kind === 'outliers') return [rowIds(), field('Selected-row action', paramSelect('action', 'param-action', [['clip', 'Clip to explicit bounds'], ['remove', 'Remove selected rows']], p.action || 'clip', true)), (p.action || 'clip') === 'clip' ? el('div', { class: 'form-grid' }, field('Lower bound', paramInput('lower', 'param-lower', p.lower ?? '', { type: 'number', step: 'any' })), field('Upper bound', paramInput('upper', 'param-upper', p.upper ?? '', { type: 'number', step: 'any' }))) : el('div', { class: 'warning-box' }, 'Removing rows changes the dataset size. Statistical outliers can be legitimate observations.')];
  if (kind === 'drop_column') return [el('div', { class: 'warning-box' }, 'This removes the selected column from the new snapshot. The original and prior versions remain available.')];
  return [el('p', { class: 'muted' }, kind === 'trim' ? 'Remove leading and trailing whitespace from string values in the selected column.' : 'Replace positive and negative infinity in the selected column with null.')];
}
function parseJson(text, label) { try { return JSON.parse(text); } catch { throw new Error(`${label} must be valid JSON.`); } }
function readOperation() {
  const kind = document.querySelector('#operation-kind').value;
  const column = kind === 'drop_duplicates' ? null : document.querySelector('#operation-column').value;
  const params = {};
  const value = id => document.querySelector(`#${id}`)?.value;
  if (kind === 'normalize_missing') {
    params.tokens = parseJson(value('param-tokens'), 'Missing tokens');
    if (!Array.isArray(params.tokens) || !params.tokens.every(v => typeof v === 'string')) throw new Error('Missing tokens must be a JSON array of strings.');
  }
  if (['drop_duplicates', 'outliers'].includes(kind)) {
    const tokens = (value('param-rows') || '').split(',').map(v => v.trim());
    if (!tokens.length || tokens.some(v => !/^\d+$/.test(v) || !Number.isSafeInteger(Number(v)))) throw new Error('Enter explicit, non-negative integer row IDs separated by commas.');
    params.row_ids = [...new Set(tokens.map(Number))];
  }
  if (['to_numeric', 'to_date'].includes(kind)) params.coerce = document.querySelector('#param-coerce').checked;
  if (kind === 'to_date') { params.format = value('param-format'); if (!params.format?.trim()) throw new Error('Provide an explicit date format.'); }
  if (kind === 'fill_missing') {
    params.strategy = value('param-strategy');
    if (params.strategy === 'constant') { params.value = parseJson(value('param-value'), 'Constant value'); if (params.value !== null && typeof params.value === 'object') throw new Error('Constant value must be a JSON scalar, not an array or object.'); }
  }
  if (kind === 'case') params.mode = value('param-mode');
  if (kind === 'map_categories') {
    params.mapping = parseJson(value('param-mapping'), 'Category mapping');
    if (params.mapping === null || typeof params.mapping !== 'object' || Array.isArray(params.mapping) || !Object.keys(params.mapping).length) throw new Error('Category mapping must be a nonempty JSON object.');
  }
  if (kind === 'outliers') {
    params.action = value('param-action');
    if (params.action === 'clip') {
      const lower = value('param-lower'), upper = value('param-upper');
      if (lower === '' || upper === '' || !Number.isFinite(Number(lower)) || !Number.isFinite(Number(upper)) || Number(lower) > Number(upper)) throw new Error('Enter finite lower and upper clipping bounds, with lower ≤ upper.');
      params.lower = Number(lower); params.upper = Number(upper);
    }
  }
  return { kind, column, params };
}
async function previewOperation() {
  const operation = readOperation();
  state.cleaningPreview = await datasetApi('/cleaning/preview', { method: 'POST', body: { operation, ...expected() } });
  state.reviewedRevision = state.meta.revision; state.operation = operation;
  render(); scrollSection('#cleaning-preview');
}
function cleaningPreviewPanel() {
  const p = state.cleaningPreview;
  const approval = el('input', { type: 'checkbox', id: 'approval', onchange: event => { document.querySelector('#apply-operation').disabled = !event.target.checked; } });
  const node = panel('Review this exact change', `Preview for snapshot v${p.version}, revision ${state.reviewedRevision}. No data has changed yet.`, el('div', {},
    el('div', { class: 'preview-stats' }, el('div', {}, el('strong', {}, fmt(p.affected_cells)), el('span', {}, 'cells affected')), el('div', {}, el('strong', {}, fmt(p.affected_rows)), el('span', {}, 'rows affected')), el('div', {}, el('strong', {}, `${fmt(p.rows_removed)} / ${fmt(p.rows_added)}`), el('span', {}, 'rows removed / added'))),
    el('div', { class: 'panel-body', style: 'padding-top:0' }, el('pre', { class: 'code-block' }, JSON.stringify(p.operation, null, 2))), comparison(p),
    table(['Row ID', 'Column', 'Before', 'After'], (p.changes || []).map(c => [c.row_id, c.column, c.before, c.after]), { caption: 'Cleaning change preview' }),
    el('div', { class: 'panel-body stack', style: 'gap:14px' }, el('p', { class: 'muted' }, 'The table may be a bounded sample of changes. Counts and before/after metrics cover the complete operation.'), el('label', { class: 'check-field' }, approval, 'I reviewed the operation, affected rows, and potential data loss. I approve this exact change.'),
      button('Approve & apply', () => applyPreview(), '', { id: 'apply-operation', disabled: true }), button('Discard preview', () => { state.cleaningPreview = null; render(); }, 'ghost'))), badge('NOT APPLIED', 'warning'));
  node.id = 'cleaning-preview'; return node;
}
async function applyPreview() {
  if (!document.querySelector('#approval')?.checked || !state.cleaningPreview) return;
  if (!await confirmAction('Apply the reviewed transformation?', 'A new version will be created from this exact preview. The original stays intact, and you can undo this operation.', 'Apply change')) return;
  run('Applying the approved transformation…', async () => {
    const reviewed = state.cleaningPreview;
    if (!reviewed) throw new Error('The preview is no longer current. Generate a new preview.');
    await datasetApi('/cleaning/apply', { method: 'POST', body: { preview_id: reviewed.preview_id, expected_version: reviewed.version, expected_revision: state.reviewedRevision, approved: true } });
    state.redoCount = 0; await refreshDataset(); render();
  }, { retry: false });
}
async function navigateVersion(action, version) {
  const destructive = ['reset', 'restore'].includes(action);
  if (destructive && !await confirmAction(action === 'reset' ? 'Return to the original snapshot?' : `Restore snapshot v${version}?`, 'The active view will change and any pending preview will be discarded. Saved versions are retained; the revision counter will advance.', action === 'reset' ? 'Reset to original' : 'Restore version')) return;
  run(`${humanize(action)}ing the active snapshot…`, async () => {
    const body = { ...expected(), ...(version !== undefined ? { version } : {}) };
    await datasetApi(`/${action}`, { method: 'POST', body });
    state.redoCount = action === 'undo' ? state.redoCount + 1 : action === 'redo' ? Math.max(0, state.redoCount - 1) : 0;
    await refreshDataset(); render();
  }, { retry: false });
}
function historyPanel() {
  const versions = state.history?.versions || [];
  return panel('Version history', 'Immutable snapshots. Restoring changes the active version, never your source file.', el('div', {}, versions.map(v => {
    const active = v.version === state.meta.active_version;
    const timestamp = typeof v.created_at === 'number' ? new Date(v.created_at * 1000) : new Date(v.created_at);
    return el('div', { class: 'history-item' }, el('span', { class: 'history-version' }, `v${v.version}`), el('div', { class: 'history-content' }, el('strong', {}, v.version === 0 ? 'Original baseline' : `${humanize(v.operation?.kind || 'Snapshot')}${v.operation?.column ? ` · ${v.operation.column}` : ''}`), el('span', {}, `${Number.isNaN(timestamp.valueOf()) ? '' : timestamp.toLocaleString()}${v.parent != null ? ` · parent v${v.parent}` : ''}`)), active ? badge('ACTIVE', 'success') : button(`Restore v${v.version}`, () => navigateVersion('restore', v.version), 'secondary small'));
  })), badge(`${versions.length} VERSIONS`), 'section-gap');
}

function exportsView() {
  const cards = [
    ['CSV', 'Cleaned CSV', 'A portable, spreadsheet-compatible copy of the active snapshot. Formula-like strings are escaped.', '/export?format=csv', 'csv', 'Download CSV'],
    ['XLSX', 'Excel workbook', 'A formatted workbook for your next analysis step, with spreadsheet formula protection.', '/export?format=xlsx', 'xlsx', 'Download XLSX'],
    ['JSON', 'Quality summary', 'Machine-readable profile, quality findings, and transformation history for your records.', '/report?format=json', 'json', 'Download JSON'],
    ['HTML', 'Quality report', 'A standalone report that combines profiling, quality findings, and the version history.', '/report?format=html', 'html', 'Download HTML'],
    ['PY', 'Python reference', 'Reviewable reference code for reproducing the applied transformations. Not executed here.', '/code?language=python', 'py', 'Download Python'],
    ['SQL', 'PostgreSQL reference', 'PostgreSQL-oriented reference SQL. Unsupported operations are identified in comments.', '/code?language=sql', 'sql', 'Download SQL']
  ];
  return [heading('Ready for what comes next.', 'Take your refined data and a transparent record of how it got here. Downloads use your private session authorization.', [], 'EXPORTS & REPORTS'),
    el('div', { class: 'info-box', style: 'margin-bottom:24px' }, `Exporting ${state.meta.filename} · snapshot v${state.meta.active_version} · ${fmt(state.profile.rows)} rows × ${fmt(state.profile.columns)} columns. The original file is not overwritten.`),
    el('div', { class: 'exports-grid' }, cards.map(([mark, title, description, path, extension, label]) => el('article', { class: 'panel export-card' }, el('span', { class: 'export-mark' }, mark), el('h2', {}, title), el('p', {}, description), button([icon('exports'), label], () => download(path, extension), 'secondary')))),
    panel('Need a PDF?', 'Use your browser’s print engine for a faithful, local PDF of the HTML report.', el('div', { class: 'panel-body' }, el('div', { class: 'button-row' }, button('Print report / Save as PDF', printReport, 'secondary'), el('span', { class: 'muted' }, 'Choose “Save as PDF” in the system print dialog. No PDF endpoint or cloud converter is used.'))), badge('BROWSER PRINT'), 'section-gap'),
    panel('Optional aggregate explanation', 'Core profiling and cleaning work without AI. Explanations use aggregate metrics only, not raw samples or column names.', el('div', { class: 'panel-body stack', style: 'gap:15px' },
      el('p', { class: 'muted' }, state.ai ? `${state.ai.enabled ? 'AI enabled' : 'AI disabled'} · ${state.ai.available ? 'Provider available' : 'Provider unavailable'}${state.ai.model ? ` · ${state.ai.model}` : ''}${state.ai.reason ? ` · ${state.ai.reason}` : ''}` : 'AI status could not be loaded; core analysis remains available.'),
      button('Explain aggregate quality', () => run('Preparing an aggregate-only explanation…', async () => { state.explanation = await datasetApi('/ai/explain', { method: 'POST', body: {} }); render(); }), 'secondary'),
      state.explanation ? el('div', {}, badge(state.explanation.source || 'Explanation'), el('p', { class: 'muted', style: 'white-space:pre-wrap;margin-top:12px' }, typeof state.explanation.explanation === 'string' ? state.explanation.explanation : JSON.stringify(state.explanation.explanation, null, 2)), state.explanation.reason ? el('p', { class: 'muted section-gap' }, state.explanation.reason) : null, (state.explanation.warnings || []).map(w => el('p', { class: 'warning-box section-gap' }, valueText(w)))) : null), null, 'section-gap'),
    panel('Workspace lifecycle', `The private capability is stored only for this browser tab. This session expires at ${new Date(state.meta.expires_at * 1000).toLocaleString()}; download your work before then. Server cleanup removes the original and all snapshots after expiry.`,  el('div', { class: 'panel-body button-row' }, button('Delete this dataset', deleteDataset, 'danger')), null, 'section-gap')];
}
function download(path, extension) {
  run('Preparing your authorized download…', async () => {
    const { blob, filename } = await datasetApi(path, { attachment: true });
    const url = URL.createObjectURL(blob);
    const downloadName = (filename || `dataset.${extension}`).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');
    const anchor = el('a', { href: url, download: downloadName, hidden: true });
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  });
}
function printReport() {
  run('Preparing the printable HTML report…', async () => {
    const blob = await datasetApi('/report?format=html', { blob: true });
    const frame = el('iframe', { title: 'Printable quality report', sandbox: 'allow-same-origin allow-modals', style: 'position:fixed;width:1px;height:1px;left:-10000px;top:0;border:0' });
    const clean = () => frame.remove();
    const loaded = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { clean(); reject(new Error('The printable report could not load. Download the HTML report and print it from your browser instead.')); }, 15000);
      frame.addEventListener('load', () => { clearTimeout(timeout); resolve(); }, { once: true });
    });
    // Only the server-generated, escaped report is embedded; the sandbox forbids scripts.
    frame.srcdoc = await blob.text(); document.body.append(frame); await loaded;
    frame.contentWindow.addEventListener('afterprint', clean, { once: true });
    try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch { clean(); throw new Error('Browser printing is unavailable. Download the HTML report, open it locally, and use Print / Save as PDF.'); }
    setTimeout(clean, 120000);
  });
}
async function deleteDataset() {
  if (!await confirmAction('Permanently delete this dataset?', 'This removes the original, all snapshots, and reports from local server storage. This cannot be undone. Download anything you need first.', 'Delete dataset')) return;
  run('Deleting the dataset and its snapshots…', async () => { await datasetApi('', { method: 'DELETE' }); setSession(null); clearDatasetState(); state.inspection = null; go('upload'); render(); }, { retry: false });
}
async function loadSamples() {
  try { state.samples = (await api('/samples')).samples; state.samplesError = ''; }
  catch (error) { state.samplesError = error.message; }
  render();
}
async function initialize() {
  try { document.documentElement.dataset.theme = localStorage.getItem('datalens.theme') || 'dark'; } catch { /* The workbench is usable without persistent theme storage. */ }
  updateThemeButton();
  state.view = views.some(v => v[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'upload'; render();
  await run('Connecting to the local workspace…', async () => {
    try { const health = await api('/health'); document.querySelector('#health-status').textContent = health.status === 'ok' || health.status === 'healthy' ? 'Local engine connected' : `Engine: ${health.status}`; document.querySelector('#health-dot').classList.remove('offline'); }
    catch (error) { document.querySelector('#health-status').textContent = 'Local engine unavailable'; document.querySelector('#health-dot').classList.add('offline'); throw error; }
    await loadSamples();
    try { state.ai = await api('/ai/status'); } catch { state.ai = null; }
    if (getSession()) {
      state.meta = await datasetApi();
      if (state.job) await pollJob();
      else if (state.meta.active_version !== null && state.meta.active_version >= 0) {
        if (state.meta.revision !== getSession().revision) state.redoCount = 0;
        await refreshDataset();
      }
    }
    render();
  });
}
function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === 'dark';
  const control = document.querySelector('#theme-toggle'); control.textContent = dark ? '☀' : '☾'; control.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
}
document.querySelector('#theme-toggle').addEventListener('click', () => {
  const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('datalens.theme', theme); } catch { /* Theme still changes when storage is disabled. */ }
  updateThemeButton(); render();
});
document.querySelector('#menu-toggle').addEventListener('click', () => {
  const open = document.querySelector('#sidebar').classList.toggle('open'); document.querySelector('#menu-toggle').setAttribute('aria-expanded', String(open)); document.querySelector('#menu-toggle').setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
});
document.addEventListener('click', event => {
  if (!event.target.closest('#sidebar, #menu-toggle')) { document.querySelector('#sidebar').classList.remove('open'); document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false'); }
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') { document.querySelector('#sidebar').classList.remove('open'); document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false'); } });
window.addEventListener('hashchange', () => {
  if (location.hash === '#main') { main.focus(); return; }
  state.view = views.some(v => v[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'upload';
  document.querySelector('#sidebar').classList.remove('open'); document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false');
  render(); main.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); resizeCharts();
});
initialize();
