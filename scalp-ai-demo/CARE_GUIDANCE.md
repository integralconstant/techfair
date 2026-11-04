# 맞춤 관리 문구와 제품 선택 기준

2026-11-03 확인. `dist/care.js`의 `buildCarePlan(result, profile)`은 사진의 표시 등급을 우선 사용한다. 성별은 `gender_consent === true`이고 `gender`가 `male` 또는 `female`인 계정의 보조 관찰·상담 안내에만 반영한다. 같은 두피 상태와 모발 특성에는 같은 제품 선택 기준을 제공하며, 성별로 피지량·머리 길이·임신·호르몬 상태를 추정하지 않는다.

## 반환값

기존 `items`, `sources`, `note`를 유지한다. 추가 필드는 `products`(제품 유형·선택 기준), `profileNote`, `profileTips`(성별 관련 관찰·상담 안내), `tailoringTitle`, `genderApplied`다. `products` 항목은 `id`, `title`, `type`, `ingredients`, `text`, `caution`, `reason`, `source_url` 문자열을 포함한다. `profileTips` 항목은 `id`, `title`, `text`, `source_url` 문자열을 포함한다.

실천 체크 ID 7개는 DB와 호환되도록 유지한다. 제품 카드는 구매 링크나 유료 제휴 없이 유형·제품 표시·주의사항을 안내한다. 사진이나 성별만으로 의약품·복용량을 선택하지 않는다.

## 선택 규칙

- 모든 유효 결과: 순한 두피 세정용 샴푸와 모발용 컨디셔너의 선택·사용 기준.
- 피지 유: 실제 기름짐에 따른 세정 간격 안내. 성별만으로 매일 세정을 강제하지 않는다.
- 탈모 항목 정상 이외: 모발 끊어짐·당김을 줄이는 디탱글러 안내. 발모 효과를 약속하지 않는다.
- 각질 경중등도이고 홍반 정상: 실제 비듬이 반복될 때 약사와 확인할 샴푸 성분 예를 제시한다. 국내 용도·연령·사용법은 제품 표시·약사에게 확인한다.
- 각질 중증 또는 홍반 정상 이외: 새 각질 제거 성분을 먼저 권하지 않고 실제 증상 확인과 진료를 우선 안내한다.
- 동의한 남성: 헤어라인·정수리 변화 관찰. 동의한 여성: 가르마·전체 숱 변화 관찰과 해당되는 임신·수유 상황의 치료 제품 상담 안내. 분석 모델의 판정에는 영향을 주지 않는다.

## 공식 근거

| 공식 자료 | 반영 범위 |
|---|---|
| [AAD 건강한 모발 관리](https://www.aad.org/public/everyday-care/hair-scalp-care/hair/healthy-hair-tips) | 실제 기름짐·모발 유형에 맞춘 세정, 두피 위주 샴푸, 모발 유형에 따른 컨디셔너 사용, 열·마찰 줄이기 |
| [AAD 탈모 시 관리](https://www.aad.org/public/diseases/hair-loss/treatment/tips/) | 순한 샴푸, 컨디셔너·디탱글러, 당김·고온 오일 관리 줄이기, 원인 진료 |
| [NHS 비듬 안내](https://www.nhs.uk/conditions/dandruff/) | 비듬 샴푸 성분 예와 약사 상담, 심한 각질·붉어짐·부기·가려움의 진료 안내 |
| [AAD 접촉 피부염·제품 자극](https://www.aad.org/public/everyday-care/itchy-skin/rash/itchy-rash-contact-dermatitis) | 향료 자극 가능성, 향료 무첨가 제품 확인, 의심 제품 중단 |
| [AAD 탈모 원인과 관찰 부위](https://www.aad.org/public/diseases/hair-loss/causes/18-causes/) | 남성의 헤어라인·정수리와 여성의 가르마·숱 변화 관찰 |
| [AAD 여성형 탈모](https://www.aad.org/public/diseases/hair-loss/types/female-pattern) | 여성의 관찰·원인 진료, 임신 계획·임신·수유 시 치료 제품 상담 |

문구는 위 자료의 생활 관리 정보를 서비스의 등급 표시와 연결한 것이다. 모델의 임상 정확도나 특정 제품의 사용자별 효과를 검증한 결과는 아니다.

검사: `node scripts/test_care.js` — 선택·성별 동의·성분 제안 제한·기존 체크 ID·입력 불변성 등 12개.
