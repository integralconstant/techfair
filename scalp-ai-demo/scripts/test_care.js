/* Verify care selection/consent rules; grade calculation is covered by model tests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({
  metricGrade: metric => Number.isInteger(metric.grade_index) ? metric.grade_index : null,
  metricName: metric => ({ flakes: '각질', sebum: '피지 유무', hair_loss: '탈모', erythema: '홍반' })[metric.id],
  metricLabel: metric => ['정상', '경증', '중증'][metric.grade_index],
  isBinarySebum: metric => metric.id === 'sebum' && metric.grade_labels?.length === 2
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'dist', 'care.js'), 'utf8'), context);
const build = (result, profile) => JSON.parse(JSON.stringify(context.buildCarePlan(result, profile)));
const metric = (id, grade) => ({ id, grade_index: grade, probabilities: id === 'flakes' ? [0.1, 0.2, 0.3, 0.4] : [0.2, 0.3, 0.5], ...(id === 'sebum' ? { grade_labels: ['무', '유'] } : {}) });
const result = (grades = {}) => ({ metrics: ['flakes', 'sebum', 'hair_loss', 'erythema'].map(id => metric(id, grades[id] || 0)) });
const ids = plan => plan.products.map(product => product.id);
let checks = 0;
function check(name, fn) { fn(); checks++; process.stdout.write(`PASS ${name}\n`); }

check('no report never yields products or daily tasks', () => {
  for (const value of [null, {}, { metrics: [] }, { metrics: [metric('unknown', 2)] }]) {
    const plan = build(value);
    assert.equal(plan.items.length, 0);
    assert.equal(plan.products.length, 0);
  }
});
check('normal grades keep three stable daily tasks and two basic product types', () => {
  const plan = build(result());
  assert.deepEqual(plan.items.map(item => item.id), ['gentle-wash', 'low-heat', 'observe']);
  assert.deepEqual(ids(plan), ['gentle-shampoo', 'conditioner']);
});
check('elevated results keep all seven permitted checklist IDs without duplicates', () => {
  const value = result({ flakes: 1, sebum: 1, hair_loss: 2, erythema: 1 });
  value.metrics.push(metric('flakes', 1));
  const tasks = build(value).items.map(item => item.id);
  assert.equal(tasks.length, 7);
  assert.equal(new Set(tasks).size, 7);
  assert.deepEqual([...tasks].sort(), ['gentle-wash', 'low-heat', 'observe', 'flakes-care', 'sebum-care', 'hair-care', 'redness-care'].sort());
});
check('sebum-present selects scalp cleansing without assuming sex-specific oiliness', () => {
  const plan = build(result({ sebum: 1 }));
  assert.match(plan.products[0].title, /두피 세정/);
  assert.ok(plan.items.some(item => item.id === 'sebum-care'));
});
check('flakes without redness can show pharmacist ingredient consultation', () => {
  const plan = build(result({ flakes: 1 }));
  assert.ok(ids(plan).includes('dandruff-shampoo'));
  assert.match(plan.products.find(product => product.id === 'dandruff-shampoo').ingredients, /살리실산/);
});
check('redness and severe flakes suppress active ingredient suggestions', () => {
  for (const grades of [{ flakes: 1, erythema: 1 }, { flakes: 1, erythema: 2 }, { flakes: 2 }]) {
    const plan = build(result(grades));
    assert.ok(!ids(plan).includes('dandruff-shampoo'));
    assert.ok(ids(plan).includes('scalp-consultation'));
  }
});
check('missing redness classification is never presumed to be normal', () => {
  const value = result({ flakes: 1 });
  value.metrics = value.metrics.filter(item => item.id !== 'erythema');
  assert.ok(!ids(build(value)).includes('dandruff-shampoo'));
});
check('hair concern adds detangling care without a regrowth promise', () => {
  const plan = build(result({ hair_loss: 1 }));
  assert.ok(ids(plan).includes('detangler'));
  assert.match(plan.products.find(product => product.id === 'detangler').caution, /발모 제품이 아니/);
});
check('gender is applied only with explicit boolean consent', () => {
  for (const profile of [null, { gender: 'male' }, { gender: 'female', gender_consent: false }, { gender: 'male', gender_consent: 1 }, { gender: 'invalid', gender_consent: true }]) {
    const plan = build(result(), profile);
    assert.equal(plan.genderApplied, null);
    assert.equal(plan.profileTips.length, 0);
  }
});
check('consented profiles select distinct supported observation notes', () => {
  const male = build(result(), { gender: 'male', gender_consent: true });
  const female = build(result(), { gender: 'female', gender_consent: true });
  assert.equal(male.genderApplied, 'male');
  assert.equal(female.genderApplied, 'female');
  assert.match(male.profileTips[0].text, /앞머리선과 정수리/);
  assert.match(female.profileTips[0].text, /가르마/);
  assert.ok(female.profileTips.some(tip => /임신/.test(tip.text)));
  assert.deepEqual(male.products, female.products);
});
check('every product supplies concrete selection criteria, caution, reason and primary source', () => {
  const plans = [build(result()), build(result({ flakes: 1 })), build(result({ hair_loss: 1, erythema: 2 }))];
  for (const plan of plans) for (const product of plan.products) {
    for (const field of ['id', 'title', 'type', 'ingredients', 'text', 'caution', 'reason', 'source_url']) assert.ok(product[field], field);
    assert.match(product.source_url, /^https:\/\/(www\.aad\.org|www\.nhs\.uk)\//);
  }
});
check('report and profile data are not mutated', () => {
  const value = result({ flakes: 1, hair_loss: 2 });
  const profile = { gender: 'female', gender_consent: true };
  const before = JSON.stringify({ value, profile });
  build(value, profile);
  assert.equal(JSON.stringify({ value, profile }), before);
});
process.stdout.write(`${checks} care guidance checks passed.\n`);
