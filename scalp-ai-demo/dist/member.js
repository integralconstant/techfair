/* Account editing and explicit, optional personalization consent. */
const memberState = { busy: false, error: '', saved: false, discardDraft: false, nicknameSequence: 0 };
function genderFields(prefix, user = null, disabled = false) {
  const consent = user?.gender_consent === true;
  return `<fieldset class="gender-consent" ${disabled ? 'disabled' : ''}><legend>성별에 따른 관리 안내 <span>선택</span></legend><p>성별 정보는 성별에 따른 맞춤형 관리 방법을 제공하기 위해 수집해요. 원하지 않으면 성별을 반영하지 않은 포괄적인 관리 방법을 제공해요.</p><dl class="consent-details"><div><dt>수집 항목</dt><dd>성별</dd></div><div><dt>활용 목적</dt><dd>성별에 따른 맞춤형 관리 안내</dd></div><div><dt>보관 기간</dt><dd>동의 철회 또는 계정 삭제 시까지</dd></div></dl><label class="consent-choice" for="${prefix}-gender-consent"><input id="${prefix}-gender-consent" name="gender_consent" type="checkbox" data-gender-consent ${consent ? 'checked' : ''}><span>성별 정보의 수집·이용에 동의합니다. (선택)</span></label><label class="form-field" for="${prefix}-gender"><span>성별</span><select id="${prefix}-gender" name="gender" data-gender-select ${!consent || disabled ? 'disabled' : ''} ${consent ? 'required' : ''}><option value="">선택해 주세요</option><option value="male" ${user?.gender === 'male' ? 'selected' : ''}>남성</option><option value="female" ${user?.gender === 'female' ? 'selected' : ''}>여성</option></select></label><p class="form-hint">동의하지 않아도 회원가입과 사진 분석을 이용할 수 있어요. ‘내 계정’에서 언제든 변경하거나 동의를 철회할 수 있어요.</p></fieldset>`;
}
function nicknameCheckMarkup(prefix) {
  return `<div class="nickname-check"><button type="button" class="button secondary small" data-check-nickname="${prefix}">아이디 중복 확인</button><span id="${prefix}-nickname-status" class="form-hint" role="status" aria-live="polite"></span></div>`;
}
function memberDraft(page) {
  if (memberState.discardDraft) { memberState.discardDraft = false; return null; }
  if ($('#main').dataset.page !== page) return null;
  const form = $('[data-auth-form], [data-profile-form]');
  return form ? [...form.elements].filter(el => el.name && el.type !== 'file').map(el => ({ name: el.name, value: el.value, checked: el.checked, type: el.type })) : null;
}
function restoreMemberDraft(draft) {
  const form = $('[data-auth-form], [data-profile-form]');
  if (form && draft) for (const item of draft) {
    const field = form.elements.namedItem(item.name);
    if (field) { if (item.type === 'checkbox') field.checked = item.checked; else field.value = item.value; }
  }
  syncGenderField(form);
}
function syncGenderField(form) {
  if (!form) return;
  const consent = form.querySelector('[data-gender-consent]'), select = form.querySelector('[data-gender-select]');
  if (select && consent) { select.disabled = !consent.checked || memberState.busy || state.authBusy || state.authLoading; select.required = consent.checked; }
}
async function checkNickname(prefix) {
  const field = document.getElementById(`${prefix}-nickname`), output = document.getElementById(`${prefix}-nickname-status`);
  if (!field || !output || field.disabled) return;
  const value = field.value.trim(), sequence = ++memberState.nicknameSequence;
  if (!value) { output.textContent = '아이디를 먼저 입력해 주세요.'; field.focus(); return; }
  if (prefix === 'profile' && value === state.user?.nickname) { output.textContent = '현재 사용 중인 아이디예요.'; return; }
  output.textContent = '확인하고 있어요.';
  try {
    const data = await jsonRequest(`/api/auth/nickname?nickname=${encodeURIComponent(value)}`);
    if (sequence !== memberState.nicknameSequence || !output.isConnected || field.value.trim() !== value) return;
    output.textContent = data.available ? '사용할 수 있는 아이디예요.' : '이미 사용 중인 아이디예요. 다른 아이디를 입력해 주세요.';
    output.dataset.available = String(data.available === true);
  } catch (error) { if (output.isConnected && sequence === memberState.nicknameSequence) output.textContent = error.message; }
}
function profilePage() {
  const header = intro('내 계정', '나의 정보를 관리해요.', '아이디와 비밀번호, 맞춤 관리 정보 제공 여부를 변경할 수 있어요.');
  if (state.authLoading) return `${header}<section class="surface" role="status">계정 정보를 확인하고 있어요.</section>`;
  if (state.authUnavailable) return `${header}${accountDataError('account')}`;
  if (!state.user) return `${header}<section class="surface empty-state"><h2>로그인 후 계정 정보를 확인해 주세요</h2><a class="button" href="#login">로그인하기${icon('arrow')}</a></section>`;
  if (isAdmin()) return `${header}<section class="surface"><p>관리자 계정 정보는 운영 도구에서 변경해 주세요.</p><a class="button secondary" href="#admin">관리자 페이지로${icon('arrow')}</a></section>`;
  const busy = memberState.busy || accountInteractionBusy();
  return `${header}<section class="surface profile-card"><form data-profile-form aria-busy="${busy}"><h2>회원정보 수정</h2><label class="form-field" for="profile-nickname"><span>아이디 (닉네임)</span><input id="profile-nickname" name="nickname" maxlength="40" autocomplete="username" value="${escapeHTML(state.user.nickname)}" required ${busy ? 'disabled' : ''}></label>${nicknameCheckMarkup('profile')}<label class="form-field" for="profile-current-password"><span>현재 비밀번호</span><input id="profile-current-password" name="current_password" type="password" autocomplete="current-password" maxlength="128" required ${busy ? 'disabled' : ''}></label><p class="form-hint">회원정보를 안전하게 수정하기 위해 현재 비밀번호를 확인해요.</p><div class="profile-password-grid"><label class="form-field" for="profile-new-password"><span>새 비밀번호 <small>변경할 때만 입력</small></span><input id="profile-new-password" name="new_password" type="password" autocomplete="new-password" maxlength="128" ${busy ? 'disabled' : ''}></label><label class="form-field" for="profile-confirm-password"><span>새 비밀번호 확인</span><input id="profile-confirm-password" name="password_confirm" type="password" autocomplete="new-password" maxlength="128" ${busy ? 'disabled' : ''}></label></div><p class="form-hint">다른 서비스에서 사용하지 않는 새로운 비밀번호를 사용해 주세요.</p>${genderFields('profile', state.user, busy)}${memberState.error ? `<p class="inline-notice error" role="alert">${escapeHTML(memberState.error)}</p>` : ''}${memberState.saved ? '<p class="inline-notice" role="status">회원정보를 저장했어요. 기존 기록은 그대로 유지돼요.</p>' : ''}<button class="button" type="submit" ${busy ? 'disabled' : ''}>${memberState.busy ? '저장하고 있어요' : '변경사항 저장하기'}${icon('check')}</button></form></section>`;
}
async function submitProfile(form) {
  if (memberState.busy || accountInteractionBusy() || !state.user || isAdmin()) return;
  const body = { nickname: form.elements.nickname.value.trim(), current_password: form.elements.current_password.value,
    gender_consent: form.elements.gender_consent.checked, gender: form.elements.gender_consent.checked ? form.elements.gender.value : null };
  const password = form.elements.new_password.value, confirmation = form.elements.password_confirm.value;
  if (password !== confirmation) { memberState.error = '새 비밀번호와 확인 입력이 일치하지 않아요.'; render(); return; }
  if (password) body.new_password = password;
  memberState.busy = true; memberState.error = ''; memberState.saved = false; render();
  const epoch = state.accountEpoch;
  try {
    const data = await accountRequest('/api/auth/profile', { method: 'PATCH', body });
    if (epoch !== state.accountEpoch) return;
    if (!validUser(data.user)) throw new Error('변경한 계정 정보를 확인하지 못했어요. 다시 로그인해 주세요.');
    resetAccountScope(); state.user = data.user; memberState.discardDraft = true; memberState.saved = true;
    await Promise.all([loadAccountRecords(), loadCareChecks()]);
    toast('회원정보를 저장했어요.');
  } catch (error) { if (epoch === state.accountEpoch) memberState.error = error.message; }
  finally { memberState.busy = false; render(); }
}
document.addEventListener('click', event => { const button = event.target.closest('[data-check-nickname]'); if (button) checkNickname(button.dataset.checkNickname); });
document.addEventListener('input', event => { if (event.target.matches('#auth-nickname, #profile-nickname')) { memberState.nicknameSequence++; const output = document.getElementById(event.target.id.replace('-nickname', '-nickname-status')); if (output) output.textContent = ''; } });
document.addEventListener('change', event => { if (event.target.matches('[data-gender-consent]')) syncGenderField(event.target.form); });
document.addEventListener('submit', event => { if (event.target.matches('[data-profile-form]')) { event.preventDefault(); submitProfile(event.target); } });
