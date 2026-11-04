/* Source-based lifestyle guidance. Sex-specific notes never change model grades. */
function buildCarePlan(result, profile = null) {
  const urls = {
    healthy: 'https://www.aad.org/public/everyday-care/hair-scalp-care/hair/healthy-hair-tips',
    hair: 'https://www.aad.org/public/diseases/hair-loss/treatment/tips/',
    flakes: 'https://www.nhs.uk/conditions/dandruff/',
    irritation: 'https://www.aad.org/public/everyday-care/itchy-skin/rash/itchy-rash-contact-dermatitis',
    patterns: 'https://www.aad.org/public/diseases/hair-loss/causes/18-causes/',
    female: 'https://www.aad.org/public/diseases/hair-loss/types/female-pattern'
  };
  const note = '사진 분석 등급과 피지 유무에 맞춘 생활 관리 안내예요. 진단이나 치료를 대신하지 않아요. 붉어짐·부기·심한 가려움이 계속되면 피부과에서 확인해 주세요.';
  const sources = [
    { title: '미국피부과학회 · 건강한 모발 관리', url: urls.healthy },
    { title: '미국피부과학회 · 탈모 시 모발 관리', url: urls.hair },
    { title: '영국 NHS · 비듬과 두피 증상', url: urls.flakes },
    { title: '미국피부과학회 · 제품 자극과 접촉 피부염', url: urls.irritation }
  ];
  const genderApplied = profile?.gender_consent === true && ['male', 'female'].includes(profile?.gender)
    ? profile.gender : null;
  const tailoringTitle = genderApplied ? '분석 결과와 회원정보를 반영한 관리 안내' : '분석 결과에 맞춘 관리 안내';
  const profileNote = genderApplied
    ? `동의하신 ${genderApplied === 'male' ? '남성' : '여성'} 성별 정보를 보조 안내에 반영했어요. 제품은 성별보다 실제 두피 상태와 모발 특성에 맞춰 골라요.`
    : '성별 정보를 제공하지 않아 성별을 구분하지 않는 포괄적인 관리 방법을 안내해요. 사진 분석 결과는 반영하며, 회원정보에서 성별 정보 제공 여부를 선택할 수 있어요.';
  const profileTips = [];
  if (genderApplied === 'male') {
    sources.push({ title: '미국피부과학회 · 유전성 탈모의 관찰 부위', url: urls.patterns });
    profileTips.push({ id: 'male-observation', title: '헤어라인과 정수리를 함께 기록해 보세요',
      text: '남성형 탈모에서는 앞머리선과 정수리 변화가 관찰될 수 있어요. 같은 각도와 조명으로 두 부위를 남기고, 변화가 이어지면 피부과에 기록을 보여 주세요. 사진 등급만으로 남성형 탈모를 판단할 수는 없어요.', source_url: urls.patterns });
  } else if (genderApplied === 'female') {
    sources.push({ title: '미국피부과학회 · 여성형 탈모의 관찰과 상담', url: urls.female });
    profileTips.push({ id: 'female-observation', title: '가르마 폭과 전체 숱의 변화를 기록해 보세요',
      text: '여성형 탈모에서는 가르마가 넓어지거나 전체적으로 숱이 줄어 보일 수 있어요. 같은 가르마와 각도로 기록해 보세요. 여러 원인이 비슷하게 보이므로 변화가 이어지면 원인을 진료로 확인해요.', source_url: urls.female });
    profileTips.push({ id: 'female-product-check', title: '탈모 치료 제품은 개인 상태를 확인한 뒤 선택해요',
      text: '약 성분이 든 탈모 제품을 고려한다면 임신 계획·임신·수유 여부 등 해당되는 개인 상태를 의료진에게 알려 주세요. 회원정보의 성별만으로 이런 상태를 추정하거나 약을 추천하지 않아요.', source_url: urls.female });
  }
  const empty = { items: [], products: [], sources, note, profileNote, profileTips, tailoringTitle, genderApplied };
  if (!result || !Array.isArray(result.metrics)) return empty;
  const observed = result.metrics.filter(metric => {
    const expected = { flakes: 4, sebum: 3, hair_loss: 3, erythema: 3 }[metric?.id];
    return expected && Array.isArray(metric.probabilities) && metric.probabilities.length === expected
      && metricGrade(metric) !== null;
  });
  if (!observed.length) return empty;
  const gradeFor = id => {
    const matching = observed.filter(metric => metric.id === id);
    return matching.length ? Math.max(...matching.map(metric => metricGrade(metric))) : null;
  };
  const flakesGrade = gradeFor('flakes');
  const rednessGrade = gradeFor('erythema');
  const oily = gradeFor('sebum') > 0;
  const hairConcern = gradeFor('hair_loss') > 0;
  const irritated = rednessGrade > 0;
  const items = [
    { id: 'gentle-wash', metric_id: null, title: '두피 위주로 부드럽게 씻기', text: '샴푸는 두피 위주로 사용해요. 씻는 간격은 기름짐과 오염 정도에 맞춰 조절하고, 성별만으로 횟수를 정하지 않아요.', reason: '매일 살펴볼 기본 관리 습관이에요.' },
    { id: 'low-heat', metric_id: null, title: '수건과 드라이어는 부드럽게', text: '수건으로 문지르기보다 물기를 흡수하고, 드라이어는 낮은 온도로 사용해요.', reason: '모발에 가해지는 마찰과 열을 줄여요.' },
    { id: 'observe', metric_id: null, title: '같은 조건으로 다음 기록 남기기', text: '같은 부위·각도·조명에서 촬영하고 실제 가려움이나 붉어짐도 살펴봐 주세요.', reason: '사진의 분석 등급만으로 상태 변화를 단정하지 않아요.' }
  ];
  const guidance = {
    flakes: { id: 'flakes-care', title: '각질이 반복되는지 확인하기', text: '비듬용 샴푸를 고르기 전 실제 각질·가려움과 사용 제품을 확인해요. 각질이 심하거나 붉어짐·부기가 함께 있으면 진료로 원인을 확인해요.' },
    sebum: { id: 'sebum-care', title: '기름지는 정도에 맞춰 씻기', text: '기름짐이 눈에 띄는 날에는 두피 세정에 신경 써 주세요. 과도한 세정이나 강한 문지르기 대신 실제 기름짐에 맞춰 세정 간격을 조절해요.' },
    hair_loss: { id: 'hair-care', title: '당김·열·모발 끊어짐 줄이기', text: '꽉 묶는 머리나 거친 빗질을 줄이고 모발용 컨디셔너로 엉킴을 풀어요. 샴푸만으로 모발이 다시 자라거나 탈모가 치료된다고 기대하지 않아요.' },
    erythema: { id: 'redness-care', title: '붉어짐과 제품 자극 확인하기', text: '새로 쓴 염색약·샴푸 등과 불편감이 함께 시작됐는지 살펴봐 주세요. 실제 붉어짐이나 따가움이 있으면 의심 제품 사용을 멈추고, 지속되거나 붓고 심하게 가려우면 진료를 받아요.' }
  };
  const elevated = observed.filter(metric => metricGrade(metric) > 0)
    .sort((a, b) => metricGrade(b) - metricGrade(a));
  const used = new Set();
  for (const metric of elevated) {
    if (used.has(metric.id)) continue;
    used.add(metric.id);
    const guide = guidance[metric.id];
    items.push({ ...guide, metric_id: metric.id,
      reason: isBinarySebum(metric) ? '피지 유무 항목에서 유로 분류되어 추가한 안내예요.' : `${metricName(metric)} 항목이 ${metricLabel(metric)} 등급으로 분류되어 추가한 안내예요.` });
  }
  const products = [
    {
      id: 'gentle-shampoo', type: '샴푸',
      title: irritated ? '자극이 적은 무향 샴푸부터 살펴보세요' : oily ? '두피 세정용 순한 샴푸를 골라보세요' : '현재 모발 특성에 맞는 순한 샴푸를 유지해요',
      ingredients: irritated ? '제품 표시: fragrance-free(향료 무첨가) · 전성분의 기존 알레르기 유발 성분 확인' : '제품 표시: 본인의 모발 유형용 · 사용 후 당김이나 따가움이 적은 제품',
      text: oily ? '샴푸는 두피에 사용하고 충분히 헹궈요. 피지가 있다고 강한 세정 제품을 여러 번 사용하기보다 실제 기름짐에 맞춰 간격을 조절해요.' : '두피 위주로 세정하고 헹궈요. 성별 전용 표시보다 사용 후 실제 편안함과 모발 유형을 기준으로 선택해요.',
      caution: irritated ? '무향 표시도 모든 알레르기를 막지는 못해요. 실제 붉어짐·부기·심한 가려움이 있으면 제품을 추가하기보다 진료로 확인해요.' : '자극이 생기면 사용을 멈추고 확인해요. 성분 하나만으로 제품 전체의 적합성을 판단하지 않아요.',
      reason: irritated ? '붉은 기가 분류되어 새 제품의 자극을 먼저 살피도록 안내해요.' : oily ? '피지가 있는 것으로 분류되어 세정 방법을 먼저 안내해요.' : '현재 상태를 유지할 기본 세정 제품 기준이에요.',
      source_url: irritated ? urls.irritation : urls.healthy
    },
    {
      id: 'conditioner', type: '컨디셔너·트리트먼트', title: '엉킴을 줄이는 모발용 컨디셔너',
      ingredients: '제품 표시: rinse-out conditioner(헹구는 컨디셔너) · 모발 유형용',
      text: '샴푸 후 모발에 사용해요. 가늘거나 곧은 모발은 끝부분 위주로, 건조하거나 곱슬인 모발은 모발 길이에 맞춰 사용해요. 본인에게 해당하는 방법을 골라 주세요.',
      caution: '모발 관리용 제품을 두피 치료제처럼 바르지 않아요. 제품의 사용 부위와 헹굼 방법을 따르고, 두피 자극이 생기면 중단해요.',
      reason: hairConcern ? '탈모 항목의 변화와 별개로 모발 끊어짐과 엉킴을 줄이는 관리예요.' : '모발 마찰과 엉킴을 줄일 때 살펴볼 제품이에요.', source_url: urls.healthy
    }
  ];
  if (hairConcern) {
    products.push({
      id: 'detangler', type: '리브인 컨디셔너·디탱글러', title: '빗질 때 당김을 줄이는 모발용 제품',
      ingredients: '제품 표시: leave-in conditioner / detangler · 모발용',
      text: '쉽게 엉키거나 끊어지는 모발이라면 사용법에 맞춰 모발에 바른 뒤 부드럽게 빗어 주세요. 뜨거운 오일 관리나 꽉 잡아당기는 스타일은 피하는 편이 좋아요.',
      caution: '이 제품은 모발 끊어짐 관리용이며 탈모의 원인 치료나 발모 제품이 아니에요. 실제 숱 감소가 걱정되면 피부과에 상담해요.',
      reason: '탈모 항목이 정상 이외 등급으로 분류되어 모발을 부드럽게 다루는 제품 기준을 추가했어요.', source_url: urls.hair
    });
  }
  if (flakesGrade > 0 && flakesGrade < 2 && rednessGrade === 0) {
    products.push({
      id: 'dandruff-shampoo', type: '비듬용 샴푸 상담', title: '반복되는 각질은 성분과 용도를 확인해요',
      ingredients: '약사에게 확인할 성분 예: 살리실산(salicylic acid), 케토코나졸(ketoconazole)',
      text: '실제 비듬이나 가려움이 반복될 때 약사와 제품을 골라보세요. 국내 제품의 용도·대상 연령·사용법을 확인하고, 여러 유효 성분 제품을 임의로 겹쳐 쓰지 않아요.',
      caution: '사진의 각질 등급만으로 비듬의 원인을 알 수 없어요. 붉어짐·부기·심한 가려움이 있거나 증상이 지속되면 진료를 먼저 받아요.',
      reason: '각질이 정상 이외 등급이고 붉은 기는 정상으로 분류된 경우에만 제공하는 제품 선택 참고예요.', source_url: urls.flakes
    });
  }
  if (flakesGrade >= 2 || irritated) {
    products.push({
      id: 'scalp-consultation', type: '제품 추가 전 확인', title: '강한 각질 제거보다 두피 상태 확인이 먼저예요',
      ingredients: '당분간 새 각질 제거제·강한 스크럽을 추가하지 않기',
      text: '사진에서 각질이 높게 분류되거나 붉은 기가 보이면 실제 두피의 불편감을 함께 확인해요. 심한 각질·붉어짐·부기·가려움이 있으면 피부과에 사용 제품과 기록을 보여 주세요.',
      caution: '성분을 더해 상태를 가리기보다 원인을 확인해요. 사진만으로 피부염이나 알레르기를 진단할 수는 없어요.',
      reason: '자극 가능성이 있는 성분을 먼저 권하지 않고 상태 확인을 우선하도록 안내해요.', source_url: urls.flakes
    });
  }
  return { items, products, sources, note, profileNote, profileTips, tailoringTitle, genderApplied };
}
