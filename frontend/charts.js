import { el, fmt } from './ui.js';
const charts = new Set();
const palette = ['#6cc9aa', '#82a8e6', '#c2a0e7', '#dfb46e', '#e29099', '#6dc2cf'];
let observer;
function colors() {
  const style = getComputedStyle(document.documentElement);
  return { text: style.getPropertyValue('--muted').trim(), line: style.getPropertyValue('--line').trim() };
}
export function disposeCharts() { observer?.disconnect(); for (const chart of charts) chart.dispose(); charts.clear(); }
export function resizeCharts() { for (const chart of charts) chart.resize(); }
window.addEventListener('resize', resizeCharts);
export function chart(title, option, available = true, tall = false) {
  if (!available) return el('div', { class: 'chart-empty', role: 'status' }, 'No suitable data for this visualization.');
  const node = el('div', { class: `chart${tall ? ' tall' : ''}`, role: 'img', 'aria-label': title });
  requestAnimationFrame(() => {
    if (!node.isConnected) return;
    if (!window.echarts) { node.className = 'chart-empty'; node.textContent = 'Charts could not load. Rebuild local assets and reload.'; return; }
    const c = colors();
    const instance = window.echarts.init(node, null, { renderer: 'canvas' });
    charts.add(instance);
    instance.setOption({ color: palette, backgroundColor: 'transparent', textStyle: { color: c.text, fontFamily: 'system-ui', fontSize: 10 },
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      aria: { enabled: true, label: { description: title } },
      tooltip: { trigger: 'axis', renderMode: 'richText', confine: true },
      legend: { bottom: 0, textStyle: { color: c.text, fontSize: 10 }, icon: 'roundRect', itemWidth: 10, itemHeight: 7 },
      grid: { left: 24, right: 26, top: 28, bottom: 40, containLabel: true },
      ...option,
      xAxis: option.xAxis ? { axisLine: { lineStyle: { color: c.line } }, axisLabel: { color: c.text, fontSize: 9, hideOverlap: true }, axisTick: { show: false }, splitLine: { lineStyle: { color: c.line, type: 'dashed' } }, ...option.xAxis } : undefined,
      yAxis: option.yAxis ? { axisLine: { show: false }, axisLabel: { color: c.text, fontSize: 9 }, axisTick: { show: false }, splitLine: { lineStyle: { color: c.line, type: 'dashed' } }, ...option.yAxis } : undefined
    });
    observer ||= new ResizeObserver(entries => { for (const entry of entries) window.echarts.getInstanceByDom(entry.target)?.resize(); });
    observer.observe(node);
  });
  return node;
}
export function missingChart(profile) {
  const cols = [...profile.column_profiles].sort((a, b) => b.missing_percentage - a.missing_percentage).slice(0, 18).reverse();
  return chart('Missing values by column, percentage. Showing up to 18 columns with most missing data.', {
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true, valueFormatter: value => `${fmt(value)}%` },
    grid: { left: 24, right: 30, top: 20, bottom: 30, containLabel: true },
    xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%', fontSize: 9 } },
    yAxis: { type: 'category', data: cols.map(c => c.name), axisLabel: { width: 110, overflow: 'truncate', fontSize: 10 }, splitLine: { show: false } },
    series: [{ name: 'Missing values', type: 'bar', barMaxWidth: 16, data: cols.map(c => c.missing_percentage), itemStyle: { borderRadius: [0, 3, 3, 0] } }]
  }, cols.length > 0);
}
export function typeChart(profile) {
  const values = Object.entries(profile.type_distribution || {}).map(([name, value]) => ({ name, value }));
  return chart('Column type distribution', {
    tooltip: { trigger: 'item', renderMode: 'richText', confine: true },
    legend: { bottom: 16, textStyle: { color: colors().text, fontSize: 10 } },
    series: [{ name: 'Column types', type: 'pie', radius: ['45%', '68%'], center: ['50%', '43%'], label: { show: false }, emphasis: { label: { show: true, formatter: '{b}: {c}', color: colors().text } }, itemStyle: { borderRadius: 4, borderWidth: 3, borderColor: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() }, data: values }]
  }, values.length > 0);
}
export function histogram(column) {
  const h = column.numeric?.histogram;
  const labels = h?.counts?.map((_, i) => `${fmt(h.edges[i])}–${fmt(h.edges[i + 1])}`) || [];
  return chart(`Histogram for ${column.name}. Counts per numeric interval.`, {
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 25, fontSize: 9 } }, yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', name: 'Records', data: h?.counts || [], barCategoryGap: '8%', itemStyle: { borderRadius: [3, 3, 0, 0] } }]
  }, labels.length > 0);
}
export function boxplot(column) {
  const n = column.numeric;
  const points = n ? [n.min, n.q1, n.median, n.q3, n.max] : [];
  return chart(`Five-number box plot for ${column.name}: minimum, first quartile, median, third quartile, maximum. Whiskers represent full range.`, {
    xAxis: { type: 'category', data: [column.name], axisLabel: { width: 150, overflow: 'truncate' } }, yAxis: { type: 'value', scale: true },
    series: [{ name: 'Full-range box plot', type: 'boxplot', data: [points], itemStyle: { color: '#6cc9aa44', borderColor: '#6cc9aa' } }]
  }, points.length === 5 && points.every(Number.isFinite));
}
export function categories(column) {
  const values = (column.common_values || []).slice(0, 12);
  return chart(`Most common values for ${column.name}, up to 12 categories`, {
    xAxis: { type: 'category', data: values.map(v => String(v.value ?? 'null')), axisLabel: { rotate: 25, width: 70, overflow: 'truncate', fontSize: 9 } },
    yAxis: { type: 'value', minInterval: 1 }, series: [{ name: 'Records', type: 'bar', data: values.map(v => v.count), itemStyle: { color: '#82a8e6', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 36 }]
  }, values.length > 0);
}
export function correlation(profile) {
  const columns = profile.correlation?.columns || [];
  const matrix = profile.correlation?.matrix || [];
  const data = [];
  matrix.forEach((row, y) => row.forEach((v, x) => { if (Number.isFinite(v)) data.push([x, y, v]); }));
  return chart('Pearson correlation heatmap. Association is not causation; null correlations are omitted.', {
    tooltip: { position: 'top', trigger: 'item', renderMode: 'richText', confine: true, formatter: params => `${columns[params.value[0]]} / ${columns[params.value[1]]}\nCorrelation: ${fmt(params.value[2])}` },
    grid: { left: 25, right: 35, top: 15, bottom: 70, containLabel: true },
    xAxis: { type: 'category', data: columns, axisLabel: { rotate: 30, width: 85, overflow: 'truncate', fontSize: 9 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: columns, axisLabel: { width: 100, overflow: 'truncate', fontSize: 9 } },
    visualMap: { min: -1, max: 1, orient: 'horizontal', left: 'center', bottom: 0, calculable: true, textStyle: { color: colors().text }, inRange: { color: ['#839bd1', '#26383c', '#7ed9b7'] } },
    series: [{ name: 'Correlation', type: 'heatmap', data, label: { show: columns.length <= 8, formatter: p => fmt(p.value[2]), color: '#fff', fontSize: 10 } }]
  }, columns.length > 1 && data.length > 0, true);
}
export function issueChart(issues) {
  const counts = {};
  for (const issue of issues) counts[issue.category] = (counts[issue.category] || 0) + issue.count;
  return chart('Quality findings by category. A record may appear in multiple findings.', {
    xAxis: { type: 'category', data: Object.keys(counts), axisLabel: { rotate: 20, width: 90, overflow: 'truncate', fontSize: 9 } },
    yAxis: { type: 'value', minInterval: 1 }, series: [{ name: 'Affected records (overlaps possible)', type: 'bar', data: Object.values(counts), barMaxWidth: 36, itemStyle: { color: '#dfb46e', borderRadius: [3, 3, 0, 0] } }]
  }, issues.length > 0);
}
export function anomalyChart(result) {
  const findings = result?.findings || [];
  const series = findings.filter(f => f.values?.length).map((f, index) => ({ name: f.column || `Finding ${index + 1}`, type: 'scatter', symbolSize: 9, data: f.row_ids.map((id, i) => [id, f.values[i]]).filter(point => Number.isFinite(point[1])) }));
  return chart('Flagged anomaly values by stable row ID. Only returned flagged records are plotted; column scales may differ.', {
    xAxis: { type: 'value', name: 'Row ID', nameLocation: 'middle', nameGap: 25 }, yAxis: { type: 'value', scale: true }, series,
    legend: { type: 'scroll', bottom: 0, textStyle: { color: colors().text, fontSize: 10 } },
    grid: { left: 25, right: 30, top: 25, bottom: 65, containLabel: true }
  }, series.some(s => s.data.length));
}
export function comparison(preview) {
  const before = preview.metrics_before || {}, after = preview.metrics_after || {};
  return chart('Before and after preview: missing cells and duplicate rows. These metrics have different units.', {
    xAxis: { type: 'category', data: ['Missing cells', 'Duplicate rows'] }, yAxis: { type: 'value', minInterval: 1 },
    series: [{ name: 'Before', type: 'bar', data: [before.missing_cells, before.duplicate_rows], itemStyle: { color: '#82a8e6' }, barMaxWidth: 40 }, { name: 'After preview', type: 'bar', data: [after.missing_cells, after.duplicate_rows], itemStyle: { color: '#6cc9aa' }, barMaxWidth: 40 }]
  }, Number.isFinite(before.missing_cells) && Number.isFinite(after.missing_cells));
}
