// 케어 추천 + 루틴 미션 데이터. 조사 결과가 나오면 이 파일만 교체하면 됩니다.
// 성분·루틴은 리서치 결과 기준입니다. 제품은 2026-11-02 올리브영 상품정보 제공고시의 전성분을 직접 확인한 조사 결과이고,
// 이름에서 용량·수량은 뺐습니다. functional/fragrance/alcohol은 조사 비고에 적힌 경우만 true입니다(미언급은 false).
// 이미지는 올리브영 서버 주소를 그대로 씁니다. 로컬에 저장하면 image를 assets 상대경로로 바꾸면 됩니다.
// 출처 URL을 모르는 항목은 출처명만 표시합니다.
const CARE = {
  dandruff: {
    name: "각질",
    summary: "비듬은 가벼운 지루피부염의 한 형태로, 두피 곰팡이(말라세지아)와 관련이 있어요.",
    ingredients: [
      { tier: 1, ko: "징크피리치온", inci: "Zinc Pyrithione", effect: "두피 곰팡이를 줄이는 데 도움을 줄 수 있어요", caution: "가렵거나 따끔하면 사용을 멈추세요", sources: ["AAD", "Mayo Clinic"] },
      { tier: 1, ko: "살리실릭애씨드", inci: "Salicylic Acid", effect: "각질을 부드럽게 해서 떨어지게 도와요", caution: "항진균 성분과 함께 쓰는 게 일반적이에요. 모발이 건조해질 수 있어 두피에만", conflictWith: ["erythema"], sources: ["Mayo Clinic", "PubMed 12060502"] },
      { tier: 1, ko: "피록톤올아민", inci: "Piroctone Olamine", effect: "두피 곰팡이를 줄이는 데 도움을 줄 수 있어요", caution: "국내에선 배합 한도가 정해진 성분이에요", sources: ["PubMed 18503415", "대한화장품협회 성분사전"] },
      { tier: 2, ko: "케토코나졸 샴푸", inci: "Ketoconazole", effect: "다른 비듬 샴푸로 나아지지 않을 때 고려하는 항진균 샴푸", sources: ["Mayo Clinic"] },   // TODO 국내 의약품 분류 확인
      { tier: 3, ko: "처방 샴푸·스테로이드 로션", inci: "", effect: "몇 주 써도 나아지지 않을 때 진료 후 처방", sources: ["Mayo Clinic"] }
    ],
    routine: {
      morning: [ { text: "외출할 땐 모자나 두피용 선크림으로 자외선을 막아요", source: "AAD" } ],
      evening: [
        { text: "비듬 샴푸 거품을 두피에 5~10분 두었다가 헹궈요 (제품 설명 우선)", source: "AAD" },
        { text: "두피를 부드럽게 마사지하며 꼼꼼히 헹궈요", source: "Mayo Clinic", softenIf: ["erythema"], softenText: "마사지는 문지르지 말고 아주 부드럽게만 해요" }
      ],
      weekly: [
        { text: "비듬 샴푸는 주 2회 (곱슬·굵은 모발은 주 1회)", source: "AAD, Mayo Clinic" },
        { text: "효과가 줄면 성분이 다른 샴푸로 바꿔 써요", source: "Mayo Clinic" }
      ],
      lifestyle: [
        { text: "젤·스프레이 같은 스타일링 제품을 줄여요", source: "Mayo Clinic" },
        { text: "아연·비타민 B군이 있는 균형 잡힌 식단", source: "Mayo Clinic" }
      ]
    },
    tips: ["비듬이 위생 때문이라는 건 오해예요 (AAD)"],
    products: [
      { name: "댄드러프클리닉 샴푸", brand: "라보에이치", ingredients: ["살리실릭애씨드", "피록톤올아민"], reason: "각질 연화 성분과 항진균 성분이 함께 들어 있어 비듬·각질 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000210966", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0021/A00000021096612ko.jpg?l=ko", functional: true, fragrance: false, alcohol: false, seller: "올리브영" },
      { name: "콜츠푸트 안티-댄드러프 샴푸", brand: "라우쉬", ingredients: ["살리실릭애씨드", "피록톤올아민"], reason: "두 성분이 같이 들어 있어 각질이 쌓이는 두피 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000236700", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0023/A00000023670016ko.jpg?l=ko", functional: false, fragrance: true, alcohol: true, seller: "올리브영" },
      { name: "에어로 퓨리파잉 안티댄드러프 샴푸", brand: "닥터포헤어", ingredients: ["살리실릭애씨드", "피록톤올아민"], reason: "각질 연화 성분과 항진균 성분이 함께 있어 비듬 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000163237", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016323712ko.png?l=ko", functional: true, fragrance: true, alcohol: true, seller: "올리브영" },
      { name: "안티 댄드러프 샴푸", brand: "로레알 프로페셔널", ingredients: ["피록톤올아민", "살리실릭애씨드"], reason: "항진균 성분이 들어 있어 비듬이 신경 쓰이는 두피 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000227544", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0022/A00000022754401ko.jpg?l=ko", functional: false, fragrance: true, alcohol: false, seller: "올리브영" },
      { name: "스칼프턴 시카 PDRN 딥클린 샴푸", brand: "릴리이브", ingredients: ["살리실릭애씨드", "피록톤올아민"], reason: "두 성분이 함께 들어 있어 각질 케어 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000235186", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0023/A00000023518628ko.jpg?l=ko", functional: true, fragrance: true, alcohol: false, seller: "올리브영" }
    ]
  },

  sebum: {
    name: "피지",
    summary: "지성 두피는 자주 감고, 샴푸를 두피에 잠시 두었다 헹구는 게 기본이에요.",
    ingredients: [
      { tier: 1, ko: "나이아신아마이드", inci: "Niacinamide", effect: "피지 분비를 줄이는 데 도움을 줄 수 있어요 (얼굴 피부 연구 기준)", caution: "두피 효과는 아직 확인되지 않았어요", sources: ["PubMed 16766489"] },
      { tier: 1, ko: "살리실릭애씨드", inci: "Salicylic Acid", effect: "각질과 쌓인 기름을 녹여 떨어지게 도와요", caution: "건조·자극이 생길 수 있어요", conflictWith: ["erythema"], sources: ["PMC11705510"] },
      { tier: 1, ko: "피록톤올아민", inci: "Piroctone Olamine", effect: "두피 기름짐과 비듬 관리에 도움을 줄 수 있어요", caution: "소규모 연구 결과예요", sources: ["PubMed 39778065"] }
    ],
    routine: {
      morning: [ { text: "두피가 많이 기름지면 매일 감아도 괜찮아요", source: "AAD", softenIf: ["erythema"], softenText: "횟수보다 순한 무향 샴푸로 부드럽게 감는 게 우선이에요" } ],
      evening: [
        { text: "샴푸를 두피에 5분 정도 두었다가 헹궈요", source: "MedlinePlus" },
        { text: "샴푸는 두피 위주로, 컨디셔너는 모발 끝에만", source: "AAD" },
        { text: "빗질을 너무 자주·세게 하지 않아요", source: "MedlinePlus" }
      ],
      weekly: [],
      lifestyle: [ { text: "스트레스가 두피 기름에도 영향을 줄 수 있어요", source: "MedlinePlus" } ]
    },
    tips: [],
    products: [
      { name: "티트리 퓨리파잉 샴푸", brand: "아로마티카", ingredients: ["나이아신아마이드", "살리실릭애씨드"], reason: "나이아신아마이드와 살리실릭애씨드가 들어 있어 기름진 두피 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000205722", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0020/A00000020572226ko.jpg?l=ko", functional: true, fragrance: false, alcohol: true, seller: "올리브영" },
      { name: "에어로 퓨리파잉 안티댄드러프 샴푸", brand: "닥터포헤어", ingredients: ["나이아신아마이드", "살리실릭애씨드", "피록톤올아민"], reason: "피지 관련 성분 세 가지가 모두 들어 있어 유분이 많은 두피 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000163237", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016323712ko.png?l=ko", functional: true, fragrance: true, alcohol: true, seller: "올리브영" },
      { name: "프로페셔널 디펜스 샴푸", brand: "비욘드", ingredients: ["나이아신아마이드", "살리실릭애씨드"], reason: "두 성분이 함께 들어 있어 두피 유분 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000245645", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0024/A00000024564503ko.jpg?l=ko", functional: true, fragrance: true, alcohol: false, seller: "올리브영" },
      { name: "프로페셔널 오일컨트롤 샴푸", brand: "헤드앤숄더", ingredients: ["피록톤올아민"], reason: "피록톤올아민이 들어 있어 기름지고 비듬이 생기는 두피 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000182643", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0018/A00000018264321ko.jpg?l=ko", functional: false, fragrance: true, alcohol: false, seller: "올리브영" },
      { name: "스칼프턴 시카 PDRN 딥클린 샴푸", brand: "릴리이브", ingredients: ["나이아신아마이드", "살리실릭애씨드", "피록톤올아민"], reason: "피지 관련 성분 세 가지가 모두 들어 있어 유분 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000235186", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0023/A00000023518628ko.jpg?l=ko", functional: true, fragrance: true, alcohol: false, seller: "올리브영" }
    ]
  },

  hairloss: {
    name: "탈모",
    summary: "화장품은 탈모 증상 완화에 도움을 주는 수준이에요. 원인 확인을 위해 피부과 진료를 먼저 권해요.",
    ingredients: [
      { tier: 1, ko: "덱스판테놀", inci: "Dexpanthenol", effect: "식약처 고시 탈모 증상 완화 기능성 성분이에요", sources: ["식약처 고시(보도 인용)"] },
      { tier: 1, ko: "비오틴", inci: "Biotin", effect: "식약처 고시 탈모 증상 완화 기능성 성분이에요", caution: "먹는 보충제는 혈액검사로 부족한지 먼저 확인해요", sources: ["식약처 고시(보도 인용)", "AAD"] },
      { tier: 1, ko: "엘-멘톨", inci: "Menthol", effect: "식약처 고시 탈모 증상 완화 기능성 성분이에요", sources: ["식약처 고시(보도 인용)"] },
      { tier: 1, ko: "징크피리치온", inci: "Zinc Pyrithione", effect: "식약처 고시 탈모 증상 완화 기능성 성분이에요", sources: ["대한화장품협회 성분사전"] },
      { tier: 1, ko: "카페인", inci: "Caffeine", effect: "바르는 카페인 연구가 있지만 더 많은 연구가 필요해요", caution: "국내 탈모 기능성 성분은 아니에요", sources: ["PMC11855793"] },
      { tier: 2, ko: "미녹시딜 외용제", inci: "Minoxidil", effect: "바르는 약. 효과 판단에 최소 6개월, 끊으면 다시 빠질 수 있어요", caution: "두피 자극이 생길 수 있어요", sources: ["Mayo Clinic"] },   // TODO 국내 의약품 분류 확인
      { tier: 3, ko: "피나스테리드", inci: "Finasteride", effect: "남성형 탈모에 쓰는 먹는 처방약", caution: "임신 중이거나 가능성이 있는 여성은 부서진 알약을 만지면 안 돼요", sources: ["Mayo Clinic"] }
    ],
    routine: {
      morning: [
        { text: "순한 샴푸로 감고, 매번 컨디셔너를 써요", source: "AAD" },
        { text: "드라이어는 가장 낮은 온도로, 가능하면 자연 건조", source: "AAD" },
        { text: "젖은 머리는 당기지 말고 빗살 넓은 빗으로", source: "AAD, Mayo Clinic" },
        { text: "머리를 세게 묶는 스타일은 피해요", source: "AAD" }
      ],
      evening: [
        { text: "머리카락을 꼬거나 잡아당기는 습관을 줄여요", source: "AAD" }
      ],
      weekly: [
        { text: "고데기·매직기는 특별한 날에만", source: "AAD" },
        { text: "핫오일 트리트먼트는 하지 않아요", source: "AAD" }
      ],
      lifestyle: [
        { text: "금연", source: "AAD, Mayo Clinic" },
        { text: "철분·단백질을 충분히, 너무 적게 먹는 다이어트는 피해요", source: "AAD" },
        { text: "갑자기 많이 빠지면 진료를 받아요", source: "Mayo Clinic" }
      ]
    },
    tips: ["셀레늄·비타민 A·E 보충제를 과하게 먹는 것도 탈모와 관련이 있어요 (AAD)"],
    products: [
      { name: "NEW 두피강화샴푸", brand: "라보에이치", ingredients: ["비오틴", "카페인"], reason: "고시 성분 비오틴과 카페인 성분이 들어 있어 탈모 증상 완화에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000149501", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0014/A00000014950195ko.jpg?l=ko", functional: true, fragrance: false, alcohol: false, seller: "올리브영" },
      { name: "닥터란 탈모증상완화 샴푸", brand: "하아르", ingredients: ["덱스판테놀", "비오틴"], reason: "고시 성분 덱스판테놀과 비오틴이 들어 있어 탈모 증상 완화에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000208492", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0020/A00000020849215ko.jpg?l=ko", functional: true, fragrance: true, alcohol: true, seller: "올리브영" },
      { name: "로즈마리 스칼프 스케일링 샴푸", brand: "아로마티카", ingredients: ["덱스판테놀", "비오틴", "카페인"], reason: "고시 성분 두 가지와 카페인 성분이 함께 들어 있어 탈모 증상 완화에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000222695", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0022/A00000022269533ko.jpg?l=ko", functional: true, fragrance: false, alcohol: true, seller: "올리브영" },
      { name: "프레쉬 앰플 샴푸", brand: "헤드스파7", ingredients: ["덱스판테놀"], reason: "고시 성분 덱스판테놀이 들어 있어 탈모 증상 완화에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000184764", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0018/A00000018476411ko.jpg?l=ko", functional: true, fragrance: true, alcohol: false, seller: "올리브영" },
      // 기능성 심사필이지만 '탈모 증상 완화' 문구는 페이지 글자로 확인하지 못해 reason에서 해당 표현을 뺐습니다.
      { name: "폴리젠 씨크닝 샴푸", brand: "닥터포헤어", ingredients: ["덱스판테놀", "비오틴", "카페인"], reason: "덱스판테놀·비오틴과 카페인 성분이 들어 있어 두피 관리에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000186037", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0018/A000000186037102ko.jpg?l=ko", functional: true, fragrance: true, alcohol: false, seller: "올리브영" }
    ]
  },

  erythema: {
    name: "모낭사이홍반",
    summary: "염증이 있는 두피는 쉽게 자극받아요. '덜 자극하기'가 관리의 핵심이에요.",
    ingredients: [
      { tier: 1, ko: "징크피리치온", inci: "Zinc Pyrithione", effect: "두피 세정에 권장되는 항균·항진균 성분이에요", caution: "가렵거나 따끔하면 사용을 멈추세요", sources: ["AAD"] },
      { tier: 1, ko: "피록톤올아민", inci: "Piroctone Olamine", effect: "붉은 기·가려움 관리에 도움을 줄 수 있어요", caution: "소규모 연구 결과예요", sources: ["PMC11705510"] },
      { tier: 2, ko: "케토코나졸 2% 샴푸", inci: "Ketoconazole", effect: "지루피부염에 쓰는 항진균 샴푸", sources: ["NHS Scotland"] },   // TODO 국내 의약품 분류 확인
      { tier: 3, ko: "국소 스테로이드", inci: "", effect: "진료 후 단기간 쓰는 처방약", sources: ["AAFP"] }
    ],
    avoid: ["향료가 든 제품", "알코올이 든 스킨·헤어 제품", "강한 세정제·화학물질"],
    routine: {
      morning: [
        { text: "무향·무알코올 제품을 써요", source: "AAD" },
        { text: "외출할 땐 모자, 선크림은 징크옥사이드·티타늄디옥사이드 성분으로", source: "AAD" }
      ],
      evening: [
        { text: "뜨거운 물 대신 미지근한 물로 감아요", source: "AAD" },
        { text: "샴푸가 남지 않게 꼼꼼히 헹궈요", source: "AAD" },
        { text: "세게 빗질하지 않아요", source: "NHS Scotland" }
      ],
      weekly: [ { text: "붉어진 날과 그 전에 한 일을 기록해 악화 요인을 찾아요", source: "AAD" } ],
      lifestyle: [
        { text: "스트레스 관리, 충분한 휴식", source: "AAD, BAD" },
        { text: "땀, 춥고 건조한 날씨, 강한 화학물질 냄새도 악화 요인이에요", source: "AAD" }
      ]
    },
    tips: ["붉은 기가 계속되면 다른 두피 질환일 수 있어 진료로 구분하는 게 좋아요 (AAD)"],
    // 징크피리치온 또는 피록톤올아민이 있고 살리실릭애씨드가 없는 제품만 넣었습니다. 향료 없는 제품은 찾지 못했습니다.
    products: [
      { name: "가려운두피케어 샴푸", brand: "헤드앤숄더", ingredients: ["피록톤올아민"], reason: "살리실릭애씨드 없이 피록톤올아민이 들어 있어 두피 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000216112", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0021/A00000021611258ko.jpg?l=ko", functional: false, fragrance: true, alcohol: false, seller: "올리브영" },
      { name: "에어로 퓨리파잉 샴푸", brand: "닥터포헤어", ingredients: ["피록톤올아민"], reason: "살리실릭애씨드 없이 피록톤올아민이 들어 있어 두피 세정에 도움을 줄 수 있어요.", url: "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000161890", image: "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016189035ko.png?l=ko", functional: false, fragrance: true, alcohol: true, seller: "올리브영" }
    ]
  }
};

const CONFLICTS = [
  { when: ["dandruff", "erythema"], item: "각질 제거 스크럽", action: "보류", reason: "붉은 두피는 자극에 쉽게 악화돼요" },
  { when: ["hairloss", "erythema"], item: "두피 마사지", action: "아주 약하게", reason: "문지르는 자극을 줄여야 해요" },
  { when: ["sebum", "erythema"], item: "매일 감기", action: "순한 무향 샴푸·미지근한 물·꼼꼼한 헹굼 우선", reason: "약용이 아닌 샴푸로 너무 자주 감는 건 피하는 게 좋아요" },
  { when: ["dandruff", "hairloss"], item: "비듬 샴푸", action: "두피에만, 모발 끝엔 컨디셔너", reason: "비듬 성분은 약한 모발을 건조하게 할 수 있어요" }
];

const DAILY_MISSIONS = [
  // 공통 (항상 2개 표시)
  { id: "c_rinse", symptoms: [], text: "샴푸가 남지 않게 꼼꼼히 헹궜어요" },
  { id: "c_dry",   symptoms: [], text: "머리를 잘 말리고 잤어요" },
  { id: "c_sleep", symptoms: [], text: "잠을 충분히 잤어요" },
  { id: "c_water", symptoms: [], text: "미지근한 물로 감았어요" },
  // 증상별 (증상당 1개)
  { id: "d_lather",  symptoms: ["dandruff"], text: "샴푸 거품을 두피에 몇 분 두었다 헹궜어요" },
  { id: "s_cond",    symptoms: ["sebum"],    text: "컨디셔너는 모발 끝에만 발랐어요" },
  { id: "h_loose",   symptoms: ["hairloss"], gender: "female", text: "머리를 세게 묶지 않았어요" },
  { id: "m_towel",   symptoms: ["hairloss"], gender: "male",   text: "머리를 말릴 때 수건으로 세게 문지르지 않았어요" },
  { id: "e_nofrag",  symptoms: ["erythema"], text: "무향 제품을 썼어요" }
];
// 공통 2개는 고정 (c_rinse, c_dry 우선)

// gender가 있는 미션은 그 성별에만 떠요. 같은 자리의 미션 짝 [여성, 남성]
const GENDER_PAIRS = [["h_loose", "m_towel"], ["w_no_heat", "w_gentle_wash"]];

const WEEKLY_MISSIONS = [
  { id: "w_rescan",           type: "once",  goal: 1, symptoms: [],           text: "같은 부위 다시 촬영하기", link: "#analysis" },
  { id: "w_dandruff_shampoo", type: "count", goal: 2, symptoms: ["dandruff"], text: "비듬 샴푸 쓰기" },
  { id: "w_no_styling",       type: "count", goal: 3, symptoms: ["dandruff", "erythema"], text: "스타일링 제품 안 쓴 날" },
  { id: "w_no_heat",          type: "count", goal: 5, symptoms: ["hairloss"], gender: "female", text: "고데기·매직기 안 쓴 날" },
  { id: "w_gentle_wash",      type: "count", goal: 5, symptoms: ["hairloss"], gender: "male",   text: "손톱 대신 손끝으로 감은 날" },
  { id: "w_flare_review",     type: "once",  goal: 1, symptoms: ["erythema"], text: "이번 주 붉어진 날 돌아보기" }
  // 각질 제거 스크럽 등 excludeIf: ["erythema"] 항목은 홍반 감지 시 제외
];
