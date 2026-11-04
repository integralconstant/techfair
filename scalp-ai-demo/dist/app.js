const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const paths = {
  scan: '<path d="M8 3H4a1 1 0 0 0-1 1v4m13-5h4a1 1 0 0 1 1 1v4M3 16v4a1 1 0 0 0 1 1h4m8 0h4a1 1 0 0 0 1-1v-4M7 12h10M12 7v10"/>',
  report: '<path d="M7 3h7l4 4v14H6V3zM14 3v5h5M9 12h6m-6 4h6"/>',
  chart: '<path d="M4 3v17h17M7 14l4-5 4 3 5-7"/>',
  leaf: '<path d="M20 3C8 2 1 9 6 17c6 5 14-1 14-14zM5 21l10-12"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  back: '<path d="M20 12H5m6-6-6 6 6 6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
  photo: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
  camera: '<path d="m8 5 2-2h4l2 2h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><circle cx="12" cy="13" r="4"/>',
  drop: '<path d="M12 3C10 7 5 12 5 16a7 7 0 0 0 14 0c0-4-5-9-7-13z"/>',
  flakes: '<path d="m5 6 3-2 2 3-3 2zM14 7l3-3 3 3-3 3zM8 17l4-4 3 4-4 3z"/>',
  hair: '<path d="M6 21C12 12 2 9 9 3m3 18C18 13 8 9 15 3m3 18c5-6-1-10 3-14"/>',
  redness: '<circle cx="12" cy="12" r="8"/><path d="M8 10h.01M15 9h.01M11 15h.01M16 15h.01M7 14h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
  save: '<path d="M5 3h14v18l-7-4-7 4z"/>',
  bottle: '<path d="M9 3h6v4H9zM8 7h8l2 4v10H6V11zM9 13h6m-6 4h6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-13 5h1m6 0h1"/>'
};
function icon(name, cls = '') { return `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.leaf}</svg>`; }
$$('[data-icon]').forEach(el => el.outerHTML = icon(el.dataset.icon));
const METRICS = [
  {name:'각질량',en:'SCALP FLAKES',icon:'flakes',grade:1,color:'#c4a467'},
  {name:'피지량',en:'SEBUM',icon:'drop',grade:0,color:'#69967a'},
  {name:'모공 밀도',en:'FOLLICLE DENSITY',icon:'hair',grade:1,color:'#7d929f'},
  {name:'모발사이홍반',en:'INTERFOLLICULAR REDNESS',icon:'redness',grade:0,color:'#b2b98d'}
];
const GRADES = ['정상','경증','중증'];
const EXAMPLES = [
 {id:'example-09',date:'2026-10-09',grades:[2,1,1,1],sample:true},
 {id:'example-13',date:'2026-10-13',grades:[1,1,1,0],sample:true},
 {id:'example-18',date:'2026-10-18',grades:[1,0,1,0],sample:true},
 {id:'example-23',date:'2026-10-23',grades:[1,0,1,0],sample:true}
];
const STORAGE_KEY = 'monitering-demo-records-v1';
const state = {photos:[null,null,null], working:false, reportDate:'2026-10-23', range:'month', month:9, year:2026, selectedDate:'2026-10-23', savedId:null, checks:new Set(), fileToken:[0,0,0]};
function validRecord(r) { return r && typeof r.id === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(r.date) && Array.isArray(r.grades) && r.grades.length===4 && r.grades.every(v=>Number.isInteger(v)&&v>=0&&v<=2); }
function readRecords() { try { const a = JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]'); return Array.isArray(a)?a.filter(validRecord):[]; } catch { return []; } }
function allRecords() { return [...EXAMPLES,...readRecords()].sort((a,b)=>a.date.localeCompare(b.date)); }
function today() { return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
function toast(message) { const el=$('#toast'); el.textContent=message; el.classList.add('visible'); clearTimeout(toast.timeout); toast.timeout=setTimeout(()=>el.classList.remove('visible'),3500); }
function button(text, action, secondary=false, name='arrow') { return `<button class="button ${secondary?'secondary':''}" data-action="${action}">${text}${icon(name)}</button>`; }
function heading(eyebrow,title,description,right='') { return `<div class="page-header"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div>${right||'<div class="date">DAELIM TECH-FAIR 2026</div>'}</div>`; }
function sampleUrl(n) { return `assets/scalp-sample-${n+1}.svg`; }
function scalpArtwork() { return `<svg viewBox="0 0 250 250" aria-hidden="true"><circle cx="125" cy="125" r="114" fill="none" stroke="#cfdfd0" stroke-dasharray="3 7"/><circle cx="125" cy="125" r="94" fill="#f8fbf3" stroke="#dbe7d7"/><circle cx="125" cy="125" r="78" fill="#eaf0df"/><path d="M62 161Q120 124 189 163L185 183H64Z" fill="#d5dfc3"/><path d="M82 162C106 125 70 105 99 66M124 150C149 116 113 90 142 52M163 159C181 133 158 109 181 87" fill="none" stroke="#7b9871" stroke-width="6" stroke-linecap="round"/><ellipse cx="82" cy="164" rx="9" ry="4" fill="#a9bf99"/><ellipse cx="123" cy="154" rx="9" ry="4" fill="#a9bf99"/><ellipse cx="162" cy="162" rx="9" ry="4" fill="#a9bf99"/><circle cx="203" cy="73" r="16" fill="#377951"/><path d="m197 73 4 4 8-8" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`; }
function slots() { return state.photos.map((photo,i)=>`<div class="upload-slot" data-slot="${i}"><label for="photo-${i}" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer">${photo?`<img src="${photo.url}" alt="선택한 두피 이미지 ${i+1}"><span class="slot-caption">${photo.sample?'샘플 일러스트':'선택한 사진'} ${String(i+1).padStart(2,'0')}</span>`:`${icon('upload')}<span>사진 ${i+1} 선택</span>`}</label><input type="file" id="photo-${i}" data-file="${i}" accept="image/jpeg,image/png,image/webp" aria-label="두피 사진 ${i+1} 선택">${photo?`<button class="slot-remove" data-remove="${i}" aria-label="사진 ${i+1} 제거">×</button>`:''}</div>`).join(''); }
function analysis() { return `${heading('KNOW YOUR SCALP','나의 두피를 알아가는 시간','사진 세 장으로 시작하는, 나에게 맞는 두피 관리.')}
 <section class="hero"><div><div class="eyebrow">SMALL RECORDS, BETTER CARE</div><h2>오늘의 두피,<br>조금 더 자세히.</h2><p>눈으로 놓치기 쉬운 두피의 변화를 살펴보고<br>나에게 필요한 관리의 시작점을 찾아보세요.</p>${button('샘플로 먼저 체험하기','sample',false)}</div><div class="hero-art">${scalpArtwork()}<div class="float-label one">관찰 지표 <b>4가지</b></div><div class="float-label two">사진 <b>3장으로 확인</b></div></div></section>
 <div class="step-strip" aria-label="이용 순서"><span class="step current"><b>1</b>사진 3장 선택</span><span>—</span><span class="step"><b>2</b>지표별 결과 확인</span><span>—</span><span class="step"><b>3</b>맞춤 관리·기록</span></div>
 <div class="two-cols"><section class="card"><div class="card-title"><h2>두피 사진 업로드</h2><span>같은 부위 · 3장</span></div><div class="upload-grid">${slots()}</div><p class="help-text">JPG, PNG, WEBP · 사진당 최대 10MB<br>선택한 사진은 이 브라우저에서만 표시되며 서버로 전송되지 않습니다.</p><div class="upload-footer"><span class="upload-count"><b>${state.photos.filter(Boolean).length}</b> / 3장 선택</span><div class="row"><button class="button ghost small" data-action="fill-samples">샘플 사진 사용</button><button class="button" data-action="analyze" ${state.photos.some(x=>!x)||state.working?'disabled':''}>${state.working?'예시 리포트 준비 중…':'예시 리포트 보기'}${icon('arrow')}</button></div></div><p class="error" id="upload-error" role="alert"></p></section>
 <section class="card"><div class="card-title"><h2>촬영 전, 이렇게 준비해요</h2><span>PHOTO GUIDE</span></div><div class="guide-item"><b>01</b><div><strong>같은 부위를 촬영해 주세요</strong><p>비교할 두피 부위를 정하고 세 장을 준비해요.</p></div></div><div class="guide-item"><b>02</b><div><strong>두피가 잘 보이는 사진으로</strong><p>가르마를 나눠 모발 사이 두피를 보여 주세요.</p></div></div><div class="guide-item"><b>03</b><div><strong>밝기와 초점을 확인해 주세요</strong><p>흐릿하거나 빛이 반사된 사진은 다시 확인해요.</p></div></div><div class="notice"><strong>지금은 시연용 화면입니다.</strong><br>사진과 관계없이 미리 설정된 예시 결과를 보여줘요. 실제 AI 모델은 추후 연결됩니다.</div></section></div>`; }
function metricCards(grades=METRICS.map(x=>x.grade)) { return METRICS.map((m,i)=>`<article class="metric"><div class="metric-header"><b>${m.name}</b><span class="metric-icon">${icon(m.icon)}</span></div><div class="metric-value ${grades[i]>0?'amber':''}">${GRADES[grades[i]]}</div><div class="metric-subtitle">${m.en}</div><div class="grade-scale ${grades[i]>0?'amber':''}">${[0,1,2].map(n=>`<i class="${n<=grades[i]?'on':''}"></i>`).join('')}</div><div class="scale-labels"><span>정상</span><span>경증</span><span>중증</span></div></article>`).join(''); }
function lineChart(range='month') {
 const records = range==='week' ? EXAMPLES.slice(-2) : EXAMPLES;
 const pts=records.map((r,i)=>({x:72+i*405/(records.length-1),r}));
 const lines=METRICS.map((m,j)=>{const coords=pts.map(({x,r})=>`${x},${137-r.grades[j]*48+j*2}`);return `<polyline points="${coords.join(' ')}" stroke="${m.color}" stroke-width="2" fill="none"/>${pts.map(({x,r})=>`<circle cx="${x}" cy="${137-r.grades[j]*48+j*2}" r="3.4" fill="white" stroke="${m.color}" stroke-width="1.8"/>`).join('')}`;}).join('');
 return `<svg class="chart" viewBox="0 0 520 180" role="img" aria-label="예시 두피 지표 변화: 각질량 중증에서 경증, 피지량 경증에서 정상, 모공 밀도 경증 유지, 홍반 경증에서 정상"><path d="M56 41H495M56 89H495M56 137H495" stroke="#e8ede1" stroke-dasharray="3 4" fill="none"/><text x="15" y="44">중증</text><text x="15" y="92">경증</text><text x="15" y="140">정상</text>${lines}${pts.map(({x,r})=>`<text x="${x}" y="169" text-anchor="middle">${r.date.slice(5).replace('-','.')}</text>`).join('')}</svg>`;
}
function legend() { return `<div class="chart-legend">${METRICS.map(m=>`<span><i style="background:${m.color}"></i>${m.name}</span>`).join('')}</div>`; }
function report() { return `${heading('YOUR SCALP REPORT','두피 분석 리포트','사진 3장의 지표별 결과를 한눈에 확인해 보세요.',button('새로 분석하기','new',true,'scan'))}
 <section class="summary-banner"><div class="summary-icon">${icon('leaf')}</div><div><h2>각질과 모공 밀도를 중심으로 살펴보세요</h2><p>${state.reportDate.replaceAll('-','.')} 측정 예시 · 3장 결과 종합 · 4개 지표</p></div><span class="summary-badge">예시 리포트</span></section>
 <section class="metrics" aria-label="4대 두피 지표">${metricCards()}</section>
 <div class="report-grid"><section class="card"><div class="card-title"><h2>차곡차곡, 두피의 변화</h2><a class="button ghost small" href="#history">전체 기록 보기 ↗</a></div>${legend()}${lineChart()}<div class="chart-footnote">그래프는 화면 설명을 위한 예시 기록입니다. 등급은 정상 / 경증 / 중증(경중증 포함)입니다.</div></section>
 <section class="card"><div class="card-title"><h2>나에게 맞는 관리 살펴보기</h2><span>CARE GUIDE</span></div><div class="care-list"><a class="care-mini" href="#care"><span class="tile-icon">${icon('bottle')}</span><div><b>각질 관리 제품 살펴보기</b><p>각질량 예시 결과에 연결한 제품 유형</p></div><span class="arrow">↗</span></a><a class="care-mini" href="#care"><span class="tile-icon">${icon('scan')}</span><div><b>같은 부위, 같은 조건으로 기록</b><p>지표를 비교하기 위한 관찰 습관</p></div><span class="arrow">↗</span></a><a class="care-mini" href="#care"><span class="tile-icon">${icon('calendar')}</span><div><b>나만의 관리 루틴 만들기</b><p>관리 체크리스트와 변화 기록</p></div><span class="arrow">↗</span></a></div></section></div>
 <div class="card" style="margin-top:22px;padding-top:18px;padding-bottom:18px"><div class="row space-between"><div class="photo-row" style="margin-top:0">${[0,1,2].map(i=>`<img src="${state.photos[i]?.url||sampleUrl(i)}" alt="시연용 두피 이미지 ${i+1}">`).join('')}<div class="meta"><b>사진 3장 · 지표별 결과 종합</b>3장 판정의 중앙값을 사용하는 기획 방식</div></div><span class="tag">시연 데이터</span></div></div>
 <div class="bottom-actions">${button('리포트 인쇄','print',true,'report')}${button(state.savedId?'저장 완료':'이 브라우저에 기록 저장','save',false,'save')}</div><div class="save-note">저장되는 정보: 날짜와 예시 지표 · 사진은 저장하지 않아요.</div>`; }
function calendar() {
 const first=new Date(state.year,state.month,1).getDay(),days=new Date(state.year,state.month+1,0).getDate();
 const dates=new Set(allRecords().map(r=>r.date));
 return `<div class="calendar-header"><b>${state.year}년 ${state.month+1}월</b><div class="row"><button data-action="prev-month" aria-label="이전 달">‹</button><button data-action="next-month" aria-label="다음 달">›</button></div></div><div class="calendar">${['일','월','화','수','목','금','토'].map(x=>`<div class="day-label">${x}</div>`).join('')}${'<div class="blank"></div>'.repeat(first)}${Array.from({length:days},(_,i)=>{let date=`${state.year}-${String(state.month+1).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`;return `<button ${dates.has(date)?`data-date="${date}"`:'disabled'} class="${dates.has(date)?'record':''} ${date===state.selectedDate?'chosen':''}" aria-label="${date} ${dates.has(date)?'기록 보기':'기록 없음'}" ${date===state.selectedDate?'aria-pressed="true"':'aria-pressed="false"'}>${i+1}</button>`;}).join('')}</div><div class="calendar-note">● 색이 표시된 날짜를 눌러 기록을 확인하세요.</div>`;
}
function history() {
 const records=allRecords(), own=readRecords(), selected=records.filter(r=>r.date===state.selectedDate);
 return `${heading('MY SCALP JOURNAL','기록으로 발견하는 변화','작은 기록을 쌓아, 나만의 두피 관리 패턴을 살펴보세요.')}
 <section class="stat-row"><div class="card"><label>시연용 예시 기록</label><b>4<small>회</small></b></div><div class="card"><label>내 브라우저에 저장한 기록</label><b>${own.length}<small>회</small></b></div><div class="card"><label>최근 저장일</label><b style="font-size:22px">${own.length?own.at(-1).date.slice(5).replace('-','.'): '—'}<small>${own.length?'':'저장 전'}</small></b></div></section>
 <div class="history-grid"><section class="card"><div class="card-title"><h2>지표별 변화 추이</h2><div class="tabs" aria-label="그래프 기간"><button data-range="week" class="${state.range==='week'?'selected':''}" aria-pressed="${state.range==='week'}">최근 1주</button><button data-range="month" class="${state.range==='month'?'selected':''}" aria-pressed="${state.range==='month'}">월간</button></div></div>${legend()}${lineChart(state.range)}<div class="chart-footnote">예시 4회 기록을 기준으로 표시한 그래프입니다. 실제 분석 성능이나 관리 효과를 뜻하지 않습니다.</div></section><section class="card">${calendar()}</section></div>
 <section class="card history-table"><div class="card-title"><h2>${state.selectedDate.replaceAll('-','.')} 기록</h2><span>${selected.length}개 기록</span></div><div class="table-scroll"><table><thead><tr><th>측정일</th>${METRICS.map(m=>`<th>${m.name}</th>`).join('')}<th>구분</th></tr></thead><tbody>${selected.map(r=>`<tr><td>${r.date.replaceAll('-','.')}</td>${r.grades.map(g=>`<td><span class="tag ${g>0?'amber':''}">${GRADES[g]}</span></td>`).join('')}<td>${r.sample?'기본 예시':'내가 저장한 예시'}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">선택한 날짜에 저장된 기록이 없어요.</td></tr>'}</tbody></table></div><div class="row space-between" style="margin-top:17px"><span class="table-note">개인 저장 기록은 현재 브라우저에만 남습니다.</span><button class="button ghost small" data-action="clear-records" ${own.length?'':'disabled'}>내 저장 기록 삭제</button></div></section>`;
}
const CARE = [
 {icon:'bottle',tag:'제품 유형 예시',title:'각질 케어 샴푸',body:'예시 각질량 등급에 연결된 제품 유형입니다. 실제 상품 선정과 추천 기준은 추후 검증해 반영합니다.',reason:'각질량 · 경증 예시'},
 {icon:'scan',tag:'관찰 가이드',title:'같은 부위, 같은 조건',body:'촬영 부위와 조명 조건을 일정하게 맞추고, 사진에서 두피가 충분히 보이는지 확인해 보세요.',reason:'모공 밀도 · 경증 예시'},
 {icon:'calendar',tag:'기록 가이드',title:'작은 변화를 기록하기',body:'측정일별 지표를 모아 보고, 사용한 제품이나 관리 습관의 변화를 함께 돌아보는 경험을 제안합니다.',reason:'4개 지표 · 변화 관찰'}
];
function care() { return `${heading('A ROUTINE FOR YOU','나에게 맞는 관리의 시작','리포트에서 확인한 지표를 관리 행동으로 연결해 보세요.')}
 <div class="summary-banner"><div class="summary-icon">${icon('spark')}</div><div><h2>확인하고, 실천하고, 다시 기록하기</h2><p>예시 결과에 연결된 관리 콘텐츠입니다. 실제 상품이나 치료 효과를 보증하지 않습니다.</p></div></div>
 <div class="care-cards">${CARE.map(c=>`<article class="card care-card"><div class="care-top">${icon(c.icon)}</div><div class="eyebrow" style="font-size:8px">${c.tag}</div><h2>${c.title}</h2><p>${c.body}</p><div class="reason"><b>이 콘텐츠가 표시된 이유</b>${c.reason}</div></article>`).join('')}</div>
 <section class="card care-checklist"><div class="card-title"><h2>오늘의 관리 체크리스트</h2><span class="check-count">${state.checks.size} / 3 완료</span></div>${['두피 사진의 촬영 부위와 밝기 확인하기','오늘의 예시 리포트 확인하기','관리 기록을 남기고 지난 결과 살펴보기'].map((x,i)=>`<label class="task"><input type="checkbox" data-check="${i}" ${state.checks.has(i)?'checked':''}>${x}</label>`).join('')}<p class="table-note">체크 상태는 현재 화면 체험 중에만 유지됩니다.</p></section>`; }
function about() { return `${heading('ABOUT THE SERVICE','두피를 관찰하는 새로운 습관','대림 Tech-Fair 2026 · 창의융합 전공동아리 지공모')}
 <section class="about-hero"><div class="eyebrow">딥러닝 기반 ai 두피 관리 서비스</div><h2>사진 속 두피에서,<br>일상 속 관리까지.</h2><p>두피 사진의 4대 지표를 분석하고 결과를 관리 행동과 연결하는 웹 서비스를 기획했습니다. 지금 보이는 화면은 실제 AI 연결 전, 서비스의 경험과 흐름을 확인하는 프로토타입입니다.</p><div class="about-credits"><span>동아리<b>지공모</b></span><span>팀원<b>연일 · 이승철 · 김진형</b></span><span>지도교수<b>김영실 · 박상윤</b></span></div></section>
 <div class="about-grid"><article class="card"><div class="eyebrow">01 / OBSERVE</div><h3>네 가지 관점으로</h3><p>각질량, 피지량, 모공 밀도, 모발사이홍반을 지표별로 살펴보는 구조를 설계했습니다.</p></article><article class="card"><div class="eyebrow">02 / UNDERSTAND</div><h3>사진 세 장의 결과를 종합</h3><p>정상·경증·중증의 3단계 결과에서 지표별 중앙값을 선택하는 방식입니다. 경중증은 중증에 통합합니다.</p></article><article class="card"><div class="eyebrow">03 / KEEP TRACK</div><h3>꾸준한 기록으로</h3><p>결과에 따른 추천과 날짜별 기록을 연결합니다. 실제 서비스에서는 회원 계정과 서버 저장을 연동할 예정입니다.</p></article></div>
 <div class="notice">현재 구현: 이미지 미리보기 · 예시 리포트 · 브라우저 기록 저장 · 캘린더 조회 · 체크리스트<br>추후 연결: AI 모델 · 회원 인증 · 서버 데이터베이스 · 검증된 추천 데이터</div>`; }
function render() {
 const route=location.hash.slice(1)||'analysis', page=['analysis','report','history','care','about'].includes(route)?route:'analysis';
 $$('[data-nav]').forEach(a=>{a.classList.toggle('active',a.dataset.nav===page);if(a.dataset.nav===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('#main').innerHTML = ({analysis,report,history,care,about})[page]();
 document.title = `${{analysis:'두피 분석',report:'분석 리포트',history:'관리 기록',care:'맞춤 관리',about:'서비스 소개'}[page]} | 딥러닝 기반 ai 두피 관리 서비스`;
}
function go(page) { if(location.hash===`#${page}`)render();else location.hash=page; }
function releasePhoto(i) { if(state.photos[i]?.url?.startsWith('blob:'))URL.revokeObjectURL(state.photos[i].url);state.photos[i]=null;state.fileToken[i]++; }
function fillSamples() { state.photos.forEach((_,i)=>{releasePhoto(i);state.photos[i]={url:sampleUrl(i),sample:true};});state.savedId=null; }
async function readPhoto(file,index) {
 if(!file)return;
 const error = message=>{const el=$('#upload-error');if(el)el.textContent=message;toast(message);};
 if(!['image/jpeg','image/png','image/webp'].includes(file.type)){error('JPG, PNG, WEBP 이미지 파일만 선택해 주세요.');return;}
 if(file.size>10*1024*1024){error('사진 한 장은 10MB 이하로 선택해 주세요.');return;}
 const token=++state.fileToken[index], url=URL.createObjectURL(file), img=new Image();
 try { await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url;});
   if(state.fileToken[index]!==token){URL.revokeObjectURL(url);return;}
   releasePhoto(index);state.photos[index]={url,sample:false};state.savedId=null;render();
 } catch {URL.revokeObjectURL(url);error('이미지 내용을 읽을 수 없어요. 다른 파일을 선택해 주세요.');}
}
document.addEventListener('change',e=>{
 if(e.target.matches('[data-file]'))readPhoto(e.target.files[0],Number(e.target.dataset.file));
 if(e.target.matches('[data-check]')){let i=Number(e.target.dataset.check);if(e.target.checked)state.checks.add(i);else state.checks.delete(i);$('.check-count').textContent=`${state.checks.size} / 3 완료`;}
});
document.addEventListener('click',e=>{
 const rm=e.target.closest('[data-remove]');if(rm){releasePhoto(Number(rm.dataset.remove));state.savedId=null;render();return;}
 const range=e.target.closest('[data-range]');if(range){state.range=range.dataset.range;render();return;}
 const date=e.target.closest('[data-date]');if(date){state.selectedDate=date.dataset.date;render();return;}
 const el=e.target.closest('[data-action]');if(!el||el.disabled)return;
 switch(el.dataset.action){
  case 'sample':fillSamples();state.reportDate='2026-10-23';go('report');break;
  case 'fill-samples':fillSamples();render();toast('시연용 두피 일러스트 3장을 불러왔어요.');break;
  case 'analyze':if(state.photos.some(x=>!x)||state.working)return;state.working=true;render();setTimeout(()=>{state.working=false;state.reportDate=today();state.savedId=null;go('report');toast('예시 리포트입니다. 실제 사진 분석은 수행하지 않았어요.');},700);break;
  case 'new':go('analysis');break;
  case 'print':window.print();break;
  case 'save':{
    if(state.savedId){toast('이 리포트는 이미 저장했어요.');break;}
    const records=readRecords(), record={id:`demo-${Date.now()}`,date:state.reportDate,grades:METRICS.map(x=>x.grade),sample:false};
    try {localStorage.setItem(STORAGE_KEY,JSON.stringify([...records,record]));state.savedId=record.id;state.selectedDate=record.date;state.year=Number(record.date.slice(0,4));state.month=Number(record.date.slice(5,7))-1;render();toast('예시 결과를 이 브라우저에 저장했어요. 사진은 저장하지 않아요.');}catch{toast('현재 브라우저에서 저장할 수 없어요. 저장 공간 설정을 확인해 주세요.');}break;
  }
  case 'prev-month':state.month--;if(state.month<0){state.month=11;state.year--;}render();break;
  case 'next-month':state.month++;if(state.month>11){state.month=0;state.year++;}render();break;
  case 'clear-records':if(confirm('이 브라우저에 저장한 시연 기록을 삭제할까요? 기본 예시 4개는 유지됩니다.')){try{localStorage.removeItem(STORAGE_KEY);state.savedId=null;render();toast('내가 저장한 시연 기록을 삭제했어요.');}catch{toast('기록을 삭제하지 못했어요.');}}break;
 }
});
window.addEventListener('hashchange',()=>{render();window.scrollTo(0,0);});
render();
