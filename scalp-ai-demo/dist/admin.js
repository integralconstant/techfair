/* Account administration stays separate from personal scalp analysis. */
const adminState = {
  counts: null, health: null, users: [], actions: [], loaded: false,
  loading: false, mutating: false, error: '', credentials: null, generation: 0
};
function resetAdminScope() {
  adminState.generation++;
  adminState.counts = null; adminState.health = null;
  adminState.users = []; adminState.actions = []; adminState.loaded = false;
  adminState.loading = false; adminState.mutating = false; adminState.error = ''; adminState.credentials = null;
}
function adminRender(focus = false) {
  if (currentPage() === 'admin') render(focus);
  else renderAccountMenu();
}
function adminDate(timestamp) {
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp * 1000));
}
function validAdminCounts(counts) {
  return counts && ['accounts', 'members', 'admins', 'records', 'care_days'].every(key => Number.isInteger(counts[key]) && counts[key] >= 0)
    && counts.accounts === counts.members + counts.admins;
}
function validAdminMember(user) {
  return user && Number.isInteger(user.id) && user.id > 0 && typeof user.nickname === 'string' && user.nickname.length > 0 && user.nickname.length <= 40
    && ['user', 'admin'].includes(user.role) && Number.isFinite(user.created_at) && user.created_at >= 0
    && Number.isInteger(user.record_count) && user.record_count >= 0 && Number.isInteger(user.care_days) && user.care_days >= 0;
}
function validAdminHealth(health) {
  return health && ['loading', 'ready', 'error'].includes(health.status)
    && (health.configuration_id == null || (typeof health.configuration_id === 'string' && health.configuration_id.length <= 300))
    && (health.error == null || (typeof health.error === 'string' && health.error.length <= 10000))
    && Array.isArray(health.models) && health.models.length <= 20
    && health.models.every(model => model && typeof model.id === 'string' && typeof model.name === 'string' && model.name.length <= 100
      && typeof model.ready === 'boolean' && typeof model.settings_verified === 'boolean'
      && Array.isArray(model.grade_labels) && model.grade_labels.length <= 4 && model.grade_labels.every(label => typeof label === 'string' && label.length <= 100));
}
function validAdminAction(action) {
  return action && Number.isInteger(action.id) && action.id > 0 && Number.isInteger(action.actor_id) && action.actor_id > 0
    && typeof action.actor_nickname === 'string' && action.actor_nickname.length <= 100
    && Number.isInteger(action.target_id) && action.target_id > 0 && typeof action.target_nickname === 'string' && action.target_nickname.length <= 100
    && typeof action.action === 'string' && action.action.length <= 100 && Number.isFinite(action.created_at) && action.created_at >= 0
    && action.details && typeof action.details === 'object' && !Array.isArray(action.details);
}
function adminPage() {
  const header = intro('서비스 관리', '관리자 페이지', '계정과 저장 기록을 정리하고 분석 서비스의 준비 상태를 확인해요.');
  if (state.authLoading) return `${header}<section class="surface empty-state" role="status"><h2>관리자 권한을 확인하고 있어요</h2></section>`;
  if (state.authUnavailable) return `${header}${accountDataError('account')}`;
  if (!isAdmin()) return `${header}<section class="surface empty-state" data-admin-denied><h2>${state.user ? '관리자 계정으로 이용할 수 있어요' : '먼저 관리자 계정으로 로그인해 주세요'}</h2><p>${state.user ? '현재 계정에서는 사진 분석과 내 기록, 맞춤 관리를 이용할 수 있어요.' : '운영자가 만든 관리자 계정으로 로그인하면 관리 화면을 열 수 있어요.'}</p><a class="button" href="${state.user ? '#analysis' : '#login'}">${state.user ? '사진 분석으로 이동' : '로그인하기'}${icon('arrow')}</a></section>`;
  const reload = `<button class="button secondary" data-admin-reload ${adminState.loading || adminState.mutating ? 'disabled' : ''}>${adminState.loading ? '불러오는 중' : '운영 정보 새로고침'}${icon('arrow')}</button>`;
  const error = adminState.error ? `<div class="inline-notice error admin-error" role="alert" data-admin-error><strong>운영 정보를 확인해 주세요</strong><p>${escapeHTML(adminState.error)}</p></div>` : '';
  return `${header}<div class="admin-toolbar"><p>${icon('lock')} ${escapeHTML(state.user.nickname)}님 · 관리자</p>${reload}</div>${error}${adminState.loading && !adminState.loaded ? '<section class="surface empty-state" role="status"><h2>운영 정보를 불러오고 있어요</h2></section>' : ''}${adminState.loaded ? `<div data-admin-dashboard aria-busy="${adminState.loading || adminState.mutating}">${adminSummary()}${adminCredentials()}${adminUsers()}${adminModels()}${adminActions()}</div>` : ''}`;
}
function adminSummary() {
  const counts = adminState.counts;
  return `<section class="admin-section" aria-labelledby="admin-overview-title"><div class="admin-section-heading"><div><p class="section-kicker">운영 현황</p><h2 id="admin-overview-title">현재 저장된 데이터를 살펴봐요</h2></div></div><div class="admin-stats">${[
    ['accounts', '전체 계정', '개'], ['members', '일반 회원', '명'], ['records', '저장된 분석 기록', '건'], ['care_days', '저장된 관리 날짜', '일']
  ].map(([key, title, suffix]) => `<article class="surface admin-stat"><span>${title}</span><strong data-admin-count="${key}">${counts[key]}<small>${suffix}</small></strong></article>`).join('')}</div><p class="metric-note">관리자 계정은 ${counts.admins}개예요. 기록 수는 이 서버에 저장한 결과 기준이며, 게스트의 브라우저 기록과 저장하지 않은 분석은 포함하지 않아요.</p></section>`;
}
function adminCredentials() {
  const credential = adminState.credentials;
  if (!credential) return '';
  return `<section class="surface admin-credentials" data-admin-credentials role="status"><div><p class="section-kicker">임시 비밀번호 발급 완료</p><h2>${escapeHTML(credential.nickname)} <small>#${credential.id}</small></h2><p>회원에게 아래 비밀번호를 전달해 주세요. 기존 로그인은 모두 해제했어요. 이 화면을 닫거나 다른 페이지로 이동하면 비밀번호 표시는 사라져요.</p><output class="admin-password" data-admin-password aria-label="발급된 임시 비밀번호">${escapeHTML(credential.password)}</output></div><button class="button secondary" data-admin-dismiss-password>확인했어요${icon('check')}</button></section>`;
}
function adminUsers() {
  const busy = adminState.loading || adminState.mutating;
  return `<section class="surface admin-section" aria-labelledby="admin-users-title"><div class="admin-section-heading"><div><p class="section-kicker">회원 관리</p><h2 id="admin-users-title">계정별로 필요한 작업을 진행해요</h2><p>닉네임이 같아도 계정 ID로 구분해 주세요. 관리 작업은 일반 회원에게만 실행할 수 있어요.</p></div></div><div class="admin-user-list">${adminState.users.map(user => `<article class="admin-user-row" data-admin-user="${user.id}"><div class="admin-user-info"><div class="admin-user-title"><strong>${escapeHTML(user.nickname)}</strong><span class="admin-role ${user.role === 'admin' ? 'is-admin' : ''}">${user.role === 'admin' ? '관리자' : '일반 회원'}</span><span class="admin-user-id">#${user.id}</span></div><p>가입 ${adminDate(user.created_at)}</p><div class="admin-member-counts"><span>분석 기록 <b>${user.record_count}</b>건</span><span>관리 날짜 <b>${user.care_days}</b>일</span></div></div>${user.role === 'user' ? `<div class="admin-user-buttons"><button class="button secondary" data-admin-action="reset-password" data-user-id="${user.id}" ${busy ? 'disabled' : ''}>비밀번호 초기화</button><button class="button secondary" data-admin-action="clear-data" data-user-id="${user.id}" ${busy ? 'disabled' : ''}>기록 초기화</button><button class="text-button admin-delete" data-admin-action="delete-user" data-user-id="${user.id}" ${busy ? 'disabled' : ''}>계정 삭제</button></div>` : '<p class="admin-readonly">관리자 계정은 이 화면에서 변경하지 않아요.</p>'}</article>`).join('') || '<p class="chart-empty">표시할 계정이 없어요.</p>'}</div></section>`;
}
function adminModels() {
  const health = adminState.health;
  const status = { ready: '분석 준비 완료', loading: '모델을 불러오는 중', error: '모델 연결 확인 필요' }[health.status];
  return `<section class="surface admin-section" data-admin-models aria-labelledby="admin-models-title"><div class="admin-section-heading"><div><p class="section-kicker">모델 상태</p><h2 id="admin-models-title">분석 서비스의 준비 상태</h2></div><span class="admin-model-status status-${health.status}">${status}</span></div>${health.error ? `<div class="inline-notice error"><strong>모델 로딩 실패 원인</strong><p>${escapeHTML(health.error)}</p></div>` : ''}<div class="admin-model-grid">${health.models.map(model => `<article class="admin-model-card"><div><h3>${escapeHTML(model.name)}</h3><span class="admin-role ${model.ready ? 'is-ready' : ''}">${model.ready ? '연결됨' : health.status === 'error' ? '연결 실패' : '준비 중'}</span></div><p>표시 기준: ${model.grade_labels.map(escapeHTML).join(' · ')}</p><span class="metric-note">${model.settings_verified ? '제공 코드의 처리 설정 확인' : '학습 처리 설정 확인 중'}</span></article>`).join('') || '<p>모델 상태 정보가 아직 없어요.</p>'}</div><p class="metric-note">처리 설정 확인은 제공된 코드와의 대조 여부예요. 모델의 정확도를 뜻하지 않아요.</p>${health.configuration_id ? `<p class="admin-config-id">현재 분석 설정 <code>${escapeHTML(health.configuration_id)}</code></p>` : ''}</section>`;
}
function adminActions() {
  const names = { admin_credentials_updated: '관리자 계정 정보 변경', admin_created: '관리자 계정 생성', password_reset: '비밀번호 초기화', data_cleared: '기록 초기화', user_deleted: '계정 삭제', reset_password: '비밀번호 초기화', clear_data: '기록 초기화', delete_user: '계정 삭제' };
  return `<section class="surface admin-section" data-admin-actions aria-labelledby="admin-actions-title"><div class="admin-section-heading"><div><p class="section-kicker">최근 작업 내역</p><h2 id="admin-actions-title">관리 작업을 다시 확인해요</h2><p>실행 시각과 작업 대상, 처리 내용을 남겨요.</p></div></div><ol class="admin-audit-list">${adminState.actions.map(action => `<li><div><strong>${escapeHTML(names[action.action] || action.action)}</strong><time datetime="${new Date(action.created_at * 1000).toISOString()}">${adminDate(action.created_at)}</time></div><p>${escapeHTML(action.actor_nickname)} #${action.actor_id} → ${escapeHTML(action.target_nickname)} #${action.target_id}</p>${Number.isInteger(action.details.deleted_records) || Number.isInteger(action.details.deleted_care_days) ? `<span class="metric-note">삭제한 분석 기록 ${Number.isInteger(action.details.deleted_records) ? action.details.deleted_records : 0}건 · 관리 날짜 ${Number.isInteger(action.details.deleted_care_days) ? action.details.deleted_care_days : 0}일</span>` : ''}</li>`).join('') || '<li class="admin-audit-empty">아직 관리 작업 내역이 없어요.</li>'}</ol></section>`;
}
function ensureAdminLoaded() {
  if (isAdmin() && !state.authLoading && !state.authUnavailable && !adminState.loading && !adminState.loaded && !adminState.error) {
    queueMicrotask(() => { if (currentPage() === 'admin') loadAdminDashboard(); });
  }
}
async function loadAdminDashboard() {
  if (!isAdmin() || state.authLoading || adminState.loading || adminState.mutating) return;
  const epoch = state.accountEpoch, generation = adminState.generation;
  adminState.loading = true; adminState.error = ''; adminRender();
  try {
    const [overview, members, audit] = await Promise.all([
      accountRequest('/api/admin/overview'), accountRequest('/api/admin/users'), accountRequest('/api/admin/actions')
    ]);
    if (epoch !== state.accountEpoch || generation !== adminState.generation || !isAdmin()) return;
    if (!validAdminCounts(overview.counts) || !validAdminHealth(overview.health) || !Array.isArray(members.users) || !members.users.every(validAdminMember)
      || !Array.isArray(audit.actions) || !audit.actions.every(validAdminAction)) throw new Error('운영 정보의 형식을 확인하지 못했어요. 다시 불러와 주세요.');
    adminState.counts = overview.counts; adminState.health = overview.health; adminState.users = members.users; adminState.actions = audit.actions; adminState.loaded = true;
  } catch (error) {
    if (epoch === state.accountEpoch && generation === adminState.generation) adminState.error = error.message || '운영 정보를 불러오지 못했어요.';
  } finally {
    if (epoch === state.accountEpoch && generation === adminState.generation) { adminState.loading = false; adminRender(); }
  }
}
async function adminMemberAction(action, targetId) {
  if (!isAdmin() || adminState.loading || adminState.mutating || state.authLoading || accountInteractionBusy()) return;
  const user = adminState.users.find(member => member.id === targetId && member.role === 'user');
  if (!user) return;
  const target = `${user.nickname} #${user.id}`;
  const messages = {
    'reset-password': `${target}의 비밀번호를 임시 비밀번호로 초기화할까요? 기존 로그인은 모두 해제돼요.`,
    'clear-data': `${target}의 분석 기록 ${user.record_count}건과 관리 날짜 ${user.care_days}일을 초기화할까요? 지운 기록은 되돌릴 수 없어요. 계정은 유지돼요.`,
    'delete-user': `${target} 계정을 삭제할까요? 분석 기록 ${user.record_count}건, 관리 날짜 ${user.care_days}일과 로그인 정보가 함께 삭제돼요. 삭제한 계정은 되돌릴 수 없어요.`
  };
  if (!messages[action] || !confirm(messages[action])) return;
  const epoch = state.accountEpoch, generation = adminState.generation;
  adminState.mutating = true; adminState.error = ''; adminState.credentials = null; adminRender();
  let completed = false;
  try {
    const url = `/api/admin/users/${user.id}`;
    const data = await accountRequest(action === 'delete-user' ? url : `${url}/${action}`, {
      method: action === 'delete-user' ? 'DELETE' : 'POST',
      body: action === 'reset-password' ? {} : { confirm_user_id: user.id }
    });
    if (epoch !== state.accountEpoch || generation !== adminState.generation || !isAdmin()) return;
    if (action === 'reset-password') {
      if (data.user?.id !== user.id || data.user?.nickname !== user.nickname || data.user?.role !== 'user'
        || typeof data.temporary_password !== 'string' || !data.temporary_password || data.temporary_password.length > 128) throw new Error('발급한 비밀번호를 확인하지 못했어요. 다시 초기화해 주세요.');
      if (currentPage() === 'admin') adminState.credentials = { id: user.id, nickname: user.nickname, password: data.temporary_password };
    } else if ((action === 'clear-data' && data.user_id !== user.id) || (action === 'delete-user' && data.deleted_user_id !== user.id)) {
      throw new Error('처리한 계정을 확인하지 못했어요. 운영 정보를 다시 불러와 주세요.');
    }
    completed = true;
    toast(action === 'reset-password' ? '임시 비밀번호를 발급했어요.' : action === 'clear-data' ? '선택한 회원의 기록을 초기화했어요.' : '선택한 회원의 계정을 삭제했어요.');
  } catch (error) {
    if (epoch === state.accountEpoch && generation === adminState.generation) adminState.error = error.message || '관리 작업을 마치지 못했어요.';
  } finally {
    if (epoch === state.accountEpoch && generation === adminState.generation) {
      adminState.mutating = false; adminRender();
      if (completed) await loadAdminDashboard();
    }
  }
}
document.addEventListener('click', event => {
  const reload = event.target.closest('[data-admin-reload]');
  if (reload && !reload.disabled) { loadAdminDashboard(); return; }
  const dismiss = event.target.closest('[data-admin-dismiss-password]');
  if (dismiss) { adminState.credentials = null; adminRender(); return; }
  const action = event.target.closest('[data-admin-action]');
  if (action && !action.disabled) adminMemberAction(action.dataset.adminAction, Number(action.dataset.userId));
});
