/* Daily routines live alongside their calendar; guest and account scopes stay separate. */
const GUEST_CARE_KEY = 'scalp-ai-care-days-v1';
const CARE_CHECK_IDS = ['gentle-wash', 'low-heat', 'observe', 'flakes-care', 'sebum-care', 'hair-care', 'redness-care'];
const CARE_LABELS = { 'gentle-wash': '두피 위주로 부드럽게 씻기', 'low-heat': '수건과 드라이어는 부드럽게', observe: '같은 조건으로 다음 기록 남기기', 'flakes-care': '각질과 가려움 살펴보기', 'sebum-care': '기름지는 정도에 맞춰 씻기', 'hair-care': '모발에 가해지는 힘 줄이기', 'redness-care': '붉어짐과 불편감 확인하기' };
function validCareChecks(data, date) { return data && data.date === date && Array.isArray(data.checks) && data.checks.length <= CARE_CHECK_IDS.length && new Set(data.checks).size === data.checks.length && data.checks.every(id => CARE_CHECK_IDS.includes(id)); }
function readGuestCareDays() {
  try {
    const data = JSON.parse(localStorage.getItem(GUEST_CARE_KEY) || '{}');
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
    return Object.fromEntries(Object.entries(data).filter(([date, checks]) => validDate(date) && validCareChecks({ date, checks }, date)));
  } catch { return {}; }
}
function careMonthKey() { return `${state.year}-${String(state.month + 1).padStart(2, '0')}`; }
function careResult(date = null) {
  const records = readRecords().filter(record => !date || record.date <= date);
  if (state.result && (!date || state.result.date <= date)) records.push(state.result);
  return records.sort((a, b) => a.date.localeCompare(b.date)).at(-1);
}
function routineItems(date) {
  const result = careResult(date), plan = result ? buildCarePlan(result, state.user) : null;
  const items = plan?.items?.length ? [...plan.items] : [
    { id: 'gentle-wash', title: CARE_LABELS['gentle-wash'], text: '기름지거나 더러워지는 정도에 맞춰 두피 위주로 부드럽게 씻어요.', reason: '기본 관리 습관' },
    { id: 'low-heat', title: CARE_LABELS['low-heat'], text: '수건으로 물기를 흡수하고 드라이어는 낮은 온도로 사용해요.', reason: '기본 관리 습관' },
    { id: 'observe', title: CARE_LABELS.observe, text: '두피의 변화가 궁금할 때 같은 부위를 비슷한 조명에서 촬영해요.', reason: '나의 관찰 기록' }
  ];
  for (const id of state.careChecks) if (!items.some(item => item.id === id)) items.push({ id, title: CARE_LABELS[id], text: '이 날짜에 실천한 관리 항목이에요.', reason: '이전에 체크한 실천' });
  return items;
}
function historyCareSection() {
  const date = state.selectedDate, items = routineItems(date), complete = items.filter(item => state.careChecks.has(item.id)).length;
  const busy = state.careLoading || state.careSaving || !!state.careError || state.careDate !== date || date > today();
  return `<section class="surface care-routine" data-history-care><div class="surface-heading"><div><p class="section-kicker">${shortDate(date)} · ${date === today() ? '오늘의 실천' : '이날의 실천'}</p><h2>실천한 관리를 기록해요</h2></div><span class="care-check-count" data-care-count role="status">${complete} / ${items.length} 실천</span></div>${state.careLoading ? '<p class="form-hint" role="status">선택한 날짜의 실천 기록을 불러오고 있어요.</p>' : ''}${state.careError ? `<div class="inline-notice error" role="alert"><p>${escapeHTML(state.careError)}</p>${button('실천 기록 다시 불러오기', 'reload-care', true)}</div>` : ''}<div class="care-items">${items.map(item => `<label class="care-task ${state.careChecks.has(item.id) ? 'is-done' : ''}"><input type="checkbox" data-care-check="${escapeHTML(item.id)}" ${state.careChecks.has(item.id) ? 'checked' : ''} ${busy ? 'disabled' : ''}><span class="care-task-copy"><span class="care-reason">${escapeHTML(item.reason)}</span><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.text)}</span></span></label>`).join('')}</div><p class="save-note">${state.careSaving ? '실천 기록을 저장하고 있어요.' : state.user ? '선택한 날짜로 내 계정에 자동 저장돼요. 달력에서 지난 실천을 다시 확인할 수 있어요.' : '선택한 날짜로 현재 브라우저에 저장돼요. 계정의 실천 기록과 따로 관리돼요.'}</p></section>`;
}
function care() {
  const header = intro('분석에서 일상으로', '나에게 맞는 관리를 이어가요.', '분석 결과와 내가 선택한 정보를 바탕으로 관리 방법과 제품 선택 기준을 살펴봐요.');
  if (state.authLoading || state.recordsLoading) return `${header}<section class="surface empty-state" role="status"><h2>나의 관리 안내를 준비하고 있어요</h2></section>`;
  if (state.authUnavailable) return `${header}${accountDataError('account')}`;
  if (state.user && state.recordsError && !state.result) return `${header}${accountDataError('records')}`;
  const result = careResult();
  if (!result) return `${header}${accountContext()}${emptyState('분석 결과로 맞춤 관리를 시작해요', '사진 한 장을 분석하면 항목에 맞는 생활 관리와 제품 선택 기준을 안내해 드려요.')}<a class="button secondary" href="#history">내 기록에서 오늘의 실천 체크하기${icon('calendar')}</a>`;
  const plan = buildCarePlan(result, state.user);
  return `${header}${accountContext()}<section class="surface care-summary"><span class="section-kicker">관리 안내의 기준</span><h2>${shortDate(result.date)} 분석 결과</h2><p>${escapeHTML(plan.note)}</p><div class="care-grade-summary">${result.metrics.map(metric => `<span>${metricName(metric)}<strong class="grade-text grade-${metricGrade(metric)}">${escapeHTML(metricLabel(metric))}</strong></span>`).join('')}</div></section>${legacyAnalysisNotice(result)}<section class="surface care-personalization" id="care-personalization"><span class="section-kicker">${escapeHTML(plan.tailoringTitle || '나를 위한 관리 안내')}</span><h2>내가 선택한 정보로 살펴봐요</h2><p>${escapeHTML(plan.profileNote || '성별을 구분하지 않는 포괄적인 관리 방법을 안내해요.')}</p>${state.user && !isAdmin() ? '<a class="text-button" href="#profile">성별 정보 제공·동의 변경하기</a>' : !state.user ? '<a class="text-button" href="#register">회원가입 후 성별에 따른 안내 선택하기</a>' : ''}${(plan.profileTips || []).map(tip => `<article class="profile-care-tip"><h3>${escapeHTML(tip.title)}</h3><p>${escapeHTML(tip.text)}</p><a href="${escapeHTML(tip.source_url)}" target="_blank" rel="noopener noreferrer">안내 근거 확인 ↗</a></article>`).join('')}</section><section class="surface care-routine"><div class="surface-heading"><div><p class="section-kicker">기본 습관과 분석 항목별 관리</p><h2>일상에서 이렇게 관리해 보세요</h2></div></div><div class="care-items">${plan.items.map(item => `<article class="care-task care-guidance"><div class="care-task-copy"><span class="care-reason">${escapeHTML(item.reason)}</span><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.text)}</p></div></article>`).join('')}</div></section><section class="care-products" aria-labelledby="care-products-title"><div class="surface-heading"><div><p class="section-kicker">제품을 고를 때 확인해요</p><h2 id="care-products-title">제품 종류와 성분 선택 기준</h2><p>브랜드보다 내 두피와 모발에 맞는 사용 목적·표시사항을 확인해요.</p></div></div><div class="care-product-grid">${(plan.products || []).map(product => `<article class="surface care-product" data-product="${escapeHTML(product.id)}"><span class="section-kicker">${escapeHTML(product.type)}</span><h3>${escapeHTML(product.title)}</h3><p>${escapeHTML(product.reason)}</p><dl><dt>선택 기준·성분</dt><dd>${escapeHTML(product.ingredients)}</dd><dt>사용할 때 살펴봐요</dt><dd>${escapeHTML(product.text)}</dd></dl><p class="product-caution">${escapeHTML(product.caution)}</p><a href="${escapeHTML(product.source_url)}" target="_blank" rel="noopener noreferrer">안내 근거 확인 ↗</a></article>`).join('')}</div></section><section class="surface care-invite"><div><span class="section-kicker">오늘의 실천은 내 기록에</span><h2>관리한 날을 달력에 남겨요</h2><p>체크리스트와 지난 실천 내역을 ‘내 기록’에서 확인할 수 있어요.</p></div><a class="button" href="#history">실천 체크하러 가기${icon('calendar')}</a></section><details class="details-panel" data-details="care-sources"><summary><span>관리 안내의 근거 살펴보기</span><span>생활 관리 정보의 출처를 확인해요</span></summary><div class="details-content"><p>제품 선택을 돕는 일반 정보이며 진단·약물 처방이나 제품의 효과 보장이 아니에요.</p><ul class="care-sources">${plan.sources.map(source => `<li><a href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.title)} ↗</a></li>`).join('')}</ul></div></details><div class="bottom-actions"><a class="button secondary" href="#guide">다음 촬영 준비하기${icon('camera')}</a>${button('새 사진 분석하기', 'new', true, 'photo')}</div>`;
}
function ensureCareLoaded() {
  if (state.authLoading || state.authUnavailable || state.careSaving) return;
  const date = state.selectedDate, month = careMonthKey();
  if (state.careDate !== date) loadCareChecks(date);
  if (state.careMonth !== month && !state.careMonthLoading) loadCareMonth();
}
async function loadCareChecks(date = state.selectedDate) {
  if (state.careSaving || (state.careLoading && state.careDate === date)) return;
  const epoch = state.accountEpoch, token = ++state.careLoadToken;
  state.careLoading = true; state.careError = ''; state.careDate = date; state.careChecks = new Set(); render();
  try {
    const data = state.user ? await accountRequest(`/api/care-checks?date=${date}`) : { date, checks: readGuestCareDays()[date] || [] };
    if (epoch !== state.accountEpoch || token !== state.careLoadToken) return;
    if (!validCareChecks(data, date)) throw new Error('선택한 날짜의 실천 기록을 확인하지 못했어요.');
    state.careChecks = new Set(data.checks);
  } catch (error) { if (epoch === state.accountEpoch && token === state.careLoadToken) state.careError = error.message; }
  finally { if (epoch === state.accountEpoch && token === state.careLoadToken) { state.careLoading = false; render(); } }
}
async function loadCareMonth() {
  if (state.careMonthLoading) return;
  const month = careMonthKey(), epoch = state.accountEpoch, token = ++state.careMonthToken;
  state.careMonthLoading = true; state.careMonthError = ''; render();
  try {
    const data = state.user ? await accountRequest(`/api/care-checks?month=${month}`) : { month, days: Object.entries(readGuestCareDays()).filter(([date]) => date.startsWith(month)).map(([date, checks]) => ({ date, checks })) };
    if (epoch !== state.accountEpoch || token !== state.careMonthToken) return;
    if (data.month !== month || !Array.isArray(data.days) || data.days.length > 31 || !data.days.every(day => validDate(day.date) && day.date.startsWith(`${month}-`) && validCareChecks(day, day.date))) throw new Error('달력의 실천 기록을 확인하지 못했어요.');
    state.careDays = Object.fromEntries(data.days.map(day => [day.date, day.checks])); state.careMonth = month;
  } catch (error) { if (epoch === state.accountEpoch && token === state.careMonthToken) { state.careMonthError = error.message; state.careMonth = month; } }
  finally { if (epoch === state.accountEpoch && token === state.careMonthToken) { state.careMonthLoading = false; render(); } }
}
async function toggleCareCheck(input) {
  if (state.careLoading || state.careSaving || state.careError || state.careDate !== state.selectedDate || state.selectedDate > today() || !CARE_CHECK_IDS.includes(input.dataset.careCheck)) return;
  const epoch = state.accountEpoch, before = new Set(state.careChecks), date = state.selectedDate, id = input.dataset.careCheck;
  if (input.checked) state.careChecks.add(id); else state.careChecks.delete(id);
  // A monthly read begun before this write must not replace its updated mark.
  state.careMonthToken++; state.careMonthLoading = false;
  state.careSaving = true; render();
  try {
    const checks = [...state.careChecks];
    let data;
    if (state.user) data = await accountRequest('/api/care-checks', { method: 'PUT', body: { date, checks } });
    else { const days = readGuestCareDays(); days[date] = checks; localStorage.setItem(GUEST_CARE_KEY, JSON.stringify(days)); data = { date, checks }; }
    if (epoch !== state.accountEpoch) return;
    if (!validCareChecks(data, date)) throw new Error('저장한 실천 기록을 확인하지 못했어요.');
    state.careChecks = new Set(data.checks); state.careDays[date] = data.checks;
  } catch (error) { if (epoch === state.accountEpoch) { state.careChecks = before; state.careError = ['QuotaExceededError', 'SecurityError'].includes(error.name) ? '이 브라우저에 실천 기록을 저장하지 못했어요. 저장 공간과 브라우저 설정을 확인해 주세요.' : error.message; } }
  finally { if (epoch === state.accountEpoch) { state.careSaving = false; render(); } }
}
async function downloadPDF() {
  if (!state.result || state.pdfBusy) return;
  const result = storedRecord(state.result), epoch = state.accountEpoch;
  state.pdfBusy = true; render();
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch('/api/report/pdf', { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: { ...accountHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ result }) });
    if (!response.ok) {
      const data = await response.json();
      if (response.status === 409 && data.code === 'account_changed') await refreshChangedAccount();
      else if (response.status === 409 && ['data_changed', 'profile_changed'].includes(data.code)) await refreshChangedData();
      else if (response.status === 401 && state.user) expireSession();
      throw new Error(data.error || 'PDF를 만들지 못했어요. 다시 시도해 주세요.');
    }
    if (epoch !== state.accountEpoch) return;
    if (!response.headers.get('Content-Type')?.includes('application/pdf')) throw new Error('PDF 파일을 확인하지 못했어요.');
    const blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `두피_분석_보고서_${result.date}.pdf`; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000); toast('PDF 보고서를 저장했어요. 브라우저의 다운로드 목록을 확인해 주세요.');
  } catch (error) { if (epoch === state.accountEpoch) toast(error.name === 'AbortError' ? 'PDF 준비가 오래 걸리고 있어요. 다시 시도해 주세요.' : error.name === 'TypeError' ? '연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.' : error.message); }
  finally { clearTimeout(timeout); state.pdfBusy = false; render(); }
}
