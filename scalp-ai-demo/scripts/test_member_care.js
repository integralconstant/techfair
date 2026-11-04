/* Calendar write/read ordering and guest storage boundaries, without a server. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dist/member-care.js'), 'utf8');
const date = '2026-11-03';
function fixture() {
  const storage = new Map();
  const state = { user: { id: 1 }, accountEpoch: 0, careDate: date, selectedDate: date, year: 2026, month: 10,
    careChecks: new Set(), careDays: {}, careMonth: '', careLoading: false, careSaving: false, careError: '',
    careLoadToken: 0, careMonthToken: 0, careMonthLoading: false, careMonthError: '' };
  const context = vm.createContext({ state, console, Set, today: () => date, render: () => {},
    validDate: value => /^\d{4}-\d{2}-\d{2}$/.test(value),
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) } });
  vm.runInContext(source, context);
  return { context, state, storage };
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
async function main() {
  {
    const { context, state } = fixture(), delayed = deferred();
    context.accountRequest = (url, options) => options?.method === 'PUT' ? Promise.resolve({ date, checks: ['gentle-wash'] }) : delayed.promise;
    const monthly = context.loadCareMonth();
    await context.toggleCareCheck({ dataset: { careCheck: 'gentle-wash' }, checked: true });
    delayed.resolve({ month: '2026-11', days: [] }); await monthly;
    assert.equal(JSON.stringify(state.careDays[date]), '["gentle-wash"]');
    assert.equal(state.careMonthLoading, false);
    console.log('PASS late monthly read cannot erase a newly saved care mark');
  }
  {
    const { context, state } = fixture(), first = deferred(), second = deferred();
    context.accountRequest = url => url.includes('2026-11-01') ? first.promise : second.promise;
    const old = context.loadCareChecks('2026-11-01');
    const current = context.loadCareChecks('2026-11-02');
    second.resolve({ date: '2026-11-02', checks: ['low-heat'] }); await current;
    first.resolve({ date: '2026-11-01', checks: ['gentle-wash'] }); await old;
    assert.equal(state.careDate, '2026-11-02'); assert.deepEqual([...state.careChecks], ['low-heat']);
    console.log('PASS changing dates ignores a delayed response for the old day');
  }
  {
    const { context, state } = fixture(), delayed = deferred();
    context.accountRequest = () => delayed.promise;
    const loading = context.loadCareChecks(date);
    state.accountEpoch++; state.careChecks = new Set(); state.careLoading = false;
    delayed.resolve({ date, checks: ['gentle-wash'] }); await loading;
    assert.equal(state.careChecks.size, 0);
    console.log('PASS late account response cannot cross into a different account scope');
  }
  {
    const { context, state, storage } = fixture(); state.user = null;
    await context.toggleCareCheck({ dataset: { careCheck: 'gentle-wash' }, checked: true });
    assert.equal(storage.size, 1); assert.equal(JSON.stringify(context.readGuestCareDays()[date]), '["gentle-wash"]');
    state.careChecks.clear(); await context.loadCareChecks(date);
    assert.deepEqual([...state.careChecks], ['gentle-wash']);
    console.log('PASS guest daily checks persist in their own browser key');
  }
  {
    const { context, state } = fixture(); state.user = null;
    context.localStorage.setItem = () => { const error = new Error('disk quota'); error.name = 'QuotaExceededError'; throw error; };
    await context.toggleCareCheck({ dataset: { careCheck: 'gentle-wash' }, checked: true });
    assert.equal(state.careChecks.size, 0); assert.match(state.careError, /저장 공간/);
    console.log('PASS browser storage failure rolls back the checkbox with a readable message');
  }
  console.log('5 member calendar checks passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
