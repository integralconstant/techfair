/* Each indicator has a distinct address, navigation item and grade axis. */
function selectedTrendMetric() {
  return METRICS.find(metric => metric.id === location.hash.slice(1).split('/')[1]) || METRICS[0];
}
function trendMenu(active = null) {
  return `<nav class="trend-menu" aria-label="변화를 확인할 분석 항목">${METRICS.map(metric => `<a href="#trend/${metric.id}" class="trend-menu-item ${metric.id === active ? 'is-selected' : ''}" data-trend-link="${metric.id}" ${metric.id === active ? 'aria-current="page"' : ''}><span class="trend-menu-icon" style="color:${metric.color}">${icon(metric.icon)}</span><strong>${metric.name}</strong><span>변화 보기 ${icon('arrow')}</span></a>`).join('')}</nav>`;
}
function historyTrendPicker() {
  return `<section class="surface history-trend-picker" data-history-trends><div class="surface-heading"><div><p class="section-kicker">분석 등급의 변화</p><h2>살펴볼 항목을 선택해 주세요</h2><p>각 항목의 화면에서 저장한 결과와 날짜별 변화를 따로 확인할 수 있어요.</p></div></div>${trendMenu()}</section>`;
}
function metricTrendRecords(metricId, range = state.range) {
  return graphRecords(range).filter(record => metricGrade(record.metrics.find(metric => metric.id === metricId)) !== null);
}
function singleMetricChart(records, definition, binary = false) {
  if (!records.length) return '';
  const metricFor = record => record.metrics.find(metric => metric.id === definition.id);
  const labels = gradeLabels(metricFor(records[0]));
  const days = [...new Set(records.map(record => record.date))];
  const first = Date.parse(`${days[0]}T00:00:00Z`), span = Date.parse(`${days.at(-1)}T00:00:00Z`) - first;
  const xFor = date => span ? 85 + (Date.parse(`${date}T00:00:00Z`) - first) / span * 400 : 285;
  const yFor = grade => 145 - grade * (110 / (labels.length - 1));
  const points = records.map(record => ({ record, metric: metricFor(record), x: xFor(record.date) }));
  const ticks = days.filter((_, index) => !index || index === days.length - 1 || index % Math.ceil(days.length / 5) === 0);
  const title = binary ? '피지 유무의 변화' : definition.id === 'sebum' ? '이전 피지과다 기록' : `${definition.name}의 변화`;
  return `<div class="trend-chart-wrap" tabindex="0" aria-label="${title} 그래프"><svg class="chart trend-chart" data-trend-chart data-metric-id="${definition.id}" ${binary ? 'data-sebum-chart' : 'data-severity-chart'} viewBox="0 0 520 190" role="img" aria-label="${title}: ${labels.join(', ')}">${labels.map((label, grade) => `<path d="M82 ${yFor(grade)}H495" stroke="#dddeda" stroke-dasharray="3 4" fill="none"/><text x="70" y="${yFor(grade)+4}" text-anchor="end">${escapeHTML(label)}</text>`).join('')}${points.length > 1 ? `<polyline points="${points.map(point=>`${point.x},${yFor(metricGrade(point.metric))}`).join(' ')}" stroke="${definition.color}" stroke-width="2.5" fill="none"/>` : ''}${points.map(point => `<circle cx="${point.x}" cy="${yFor(metricGrade(point.metric))}" r="4.5" fill="white" stroke="${definition.color}" stroke-width="2"><title>${point.record.date} ${escapeHTML(metricName(point.metric))} ${escapeHTML(metricLabel(point.metric))}</title></circle>`).join('')}${ticks.map(date => `<text x="${xFor(date)}" y="177" text-anchor="middle">${date.slice(5).replace('-', '.')}</text>`).join('')}</svg></div><p class="trend-scroll-hint">좁은 화면에서는 그래프를 좌우로 움직여 볼 수 있어요.</p>`;
}
function trendRecordList(records, definition) {
  return `<details class="trend-record-details" data-details="trend-record-list"><summary>날짜별 판정 보기 · ${records.length}건</summary><ol class="trend-record-list">${[...records].reverse().map(record => { const metric = record.metrics.find(item => item.id === definition.id); return `<li><time datetime="${record.date}">${shortDate(record.date)}</time><strong>${escapeHTML(metricLabel(metric))}</strong></li>`; }).join('')}</ol></details>`;
}
function trendChartPanel(records, definition) {
  if (!records.length) return '<p class="chart-empty">선택한 기간에 비교할 수 있는 기록이 없어요. 다른 달이나 최근 1주를 선택해 보세요.</p>';
  if (definition.id !== 'sebum') return singleMetricChart(records, definition) + trendRecordList(records, definition);
  const binary = records.filter(record => isBinarySebum(record.metrics.find(metric=>metric.id==='sebum')));
  const legacy = records.filter(record => !isBinarySebum(record.metrics.find(metric=>metric.id==='sebum')));
  return `${binary.length ? `<section class="trend-series"><h3>피지 유무 · 무 / 유</h3><p class="chart-footnote">유는 피지 관련 특징이 있다는 판정이며, 심각도를 나타내는 등급은 아니에요.</p>${singleMetricChart(binary, definition, true)}${trendRecordList(binary, definition)}</section>` : ''}${legacy.length ? `<section class="trend-series trend-legacy"><h3>이전 피지과다 기록 · 3등급</h3><p class="chart-footnote">예전에 저장한 정상·경증·중증 기록이에요. 현재의 무·유 판정과 연결해서 비교하지 않아요.</p>${singleMetricChart(legacy, definition)}${trendRecordList(legacy, definition)}</section>` : ''}`;
}
function trendsPage() {
  const definition = selectedTrendMetric();
  const header = intro('항목별 분석 변화', `${definition.name}의 변화를 살펴봐요.`, '내 기록에 저장한 결과 중 선택한 항목만 따로 확인해요.');
  const back = `<a class="text-button trend-back" data-trend-back href="#history">${icon('back')} 내 기록으로 돌아가기</a>`;
  if (state.authLoading || state.recordsLoading) return `${header}${back}<section class="surface empty-state" role="status"><h2>분석 기록을 불러오고 있어요</h2></section>`;
  if (state.authUnavailable) return `${header}${back}${accountDataError('account')}`;
  if (state.user && state.recordsError) return `${header}${back}${accountDataError('records')}`;
  const records = metricTrendRecords(definition.id), latest = records.at(-1)?.metrics.find(metric=>metric.id===definition.id);
  const period = state.range === 'week' ? '오늘을 포함한 최근 7일' : `${state.year}년 ${state.month+1}월`;
  return `${header}${back}${accountContext()}${trendMenu(definition.id)}<section class="surface metric-trend-panel" data-trend-panel data-metric-id="${definition.id}"><div class="surface-heading"><span class="trend-panel-icon" style="color:${definition.color}">${icon(definition.icon)}</span><div><p class="section-kicker">${period}</p><h2>${definition.name} 분석 기록</h2><p>${definition.id === 'flakes' ? '정상·경중등도·중증으로 확인해요. 경중등도는 경증과 중등도를 함께 나타내요.' : definition.id === 'sebum' ? '현재 기록은 무·유로, 이전 피지과다 기록은 별도 기준으로 확인해요.' : '정상·경증·중증으로 확인해요.'}</p></div></div><div class="trend-filters"><div class="tabs" aria-label="분석 변화 조회 기간"><button data-range="week" class="${state.range==='week'?'selected':''}" aria-pressed="${state.range==='week'}">최근 1주</button><button data-range="month" class="${state.range==='month'?'selected':''}" aria-pressed="${state.range==='month'}">선택한 달</button></div><label class="trend-month-label" for="trend-month">조회할 달<input id="trend-month" data-trend-month type="month" value="${careMonthKey()}" max="${today().slice(0,7)}"></label></div><div class="trend-summary"><span>비교할 기록 <strong>${records.length}건</strong></span><span>기간 내 마지막 판정 <strong>${latest ? `${definition.id==='sebum'&&!isBinarySebum(latest)?'이전 기준 · ':''}${escapeHTML(metricLabel(latest))}` : '기록 없음'}</strong></span></div>${trendChartPanel(records,definition)}<p class="chart-footnote">현재 확인한 결과와 같은 분석 기준의 저장 기록만 비교해요. 촬영 부위·조명·초점이 다르면 결과가 달라질 수 있으므로, 그래프만으로 호전·악화를 단정하지 마세요.</p></section>`;
}
