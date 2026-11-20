"""해외 행사 판정(sources/_overseas.py) + naver_blogs·art_busan 적용 테스트 — 네트워크 0.

Tests for is_overseas_event and where the collector applies it.
제목·본문은 2026-10~11 금요일 스냅샷(frontend/public/data/events-*.json)과 2026-11-21 의
실제 RSS(rss.blog.naver.com/bscf2009.xml)에서 그대로 가져왔다 (긴 본문은 앞부분만).
'(합성)' 표시가 있는 것만 실제 글이 아니라 규칙의 경계를 보려고 만든 예다.

    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from unittest import mock

import feedparser
from bs4 import BeautifulSoup

from sources import art_busan
from sources import naver_blogs as nb
from sources._overseas import is_overseas_event

LISHUI_TITLE = "[행사] 2026 청년예술가 국제교류 사업 「중국 리수이 국제 사진제」 참여"
LISHUI_DESC = (
    "2026 청년예술가 국제교류 사업 「중국 리수이 국제 사진제」 참여 청년예술가 국제교류 사업의 일환으로 "
    "부산의 세 청년 작가가 중국 리수이 국제 사진제에 참여합니다. 한국의 동시대 사진예술의 새로운 시선과 "
    "이야기를 담은 이번 전시에 김보은, 김예지, 이재균 작가가 함께합니다. 전 시 명: Open Questions – "
    "Emerging Voice from Korea 전시기간: 2026. 10. 23. ~ 11. 23. 전시장소: 중국 리수이 사진 박물관"
    "(Lishui Photography Culture Cneter) 참여작가: 김보은, 김예지, 이재균 예술감독: 석재현, Becky BAO "
    "부산 청년예술가들의 작품이 국제 무대에서 새로운 시선과 대화를 이어갑니다. 이번 전시에 많은 관심과 "
    "응원 부탁드립니다......."
)

# (출처, 제목, 본문) — 해외에서 열리는 행사 / held abroad
ABROAD = [
    ("snap 5507 bscf2009 festival — 전시장소: 중국 리수이", LISHUI_TITLE, LISHUI_DESC),
    ("snap 5228 art_busan exhibition — 시립미술관 해외전", "젊은 시각 새로운 시선 해외전",
     "부문: 해외 · 장소: 중국 금일미술관 · 작품수: 60"),
    ("rss bscf2009 공연/연극 — 영국 파견팀", "[공연] 2026년 청년 K-컬처 글로벌 프런티어 영국 글래스고",
     "2026 청년 K-컬처 글로벌 프런티어 영국 글래스고 | 2026.08.31 – 09.11 부산문화재단은 문화체육관광부 "
     "한국국제문화교류진흥원 청년 K-컬처 글로벌 프런티어 사업으로 부산 청년 문화예술인을 위한 해외 문화예술 "
     "활동 프로젝트 지원을 수행하였습니다. 부산의 청년들이 K-컬처를 품고 세계로 했습니다. 『청년 K-컬처 "
     "글로벌 프런티어』 참여자제안형 영국 파견팀 'ICONTACT'이 몸짓과 표현으로 K-컬처의 언어를 전했습니다. "
     "글래스고 최고의 피지컬시어터 'SURGE'와 협업하여 글래스고 중심지에서 야외공연 『Mask In Motion』을 "
     "진행했으며"),
    ("rss bscf2009 공연/연극 — 오스트리아 파견", "[공연] 2026년 청년 K-컬처 글로벌 프런티어 오스트리아 잘츠부르크",
     "2026년 청년 K-컬처 글로벌 프런티어 오스트리아 잘츠부르크 | 2026.08.31 – 09.10 부산문화재단은 "
     "문화체육관광부 한국국제문화교류진흥원 청년 K-컬처 글로벌 프런티어 사업으로 부산 청년 문화예술인을 위한 "
     "해외 문화예술 활동 프로젝트 지원을 수행하였습니다. 부산의 청년들이 K-컬처를 품고 세계로 향했습니다. "
     "『청년 K-컬처 글로벌 프런티어』 오스트리아 파견 댄스팀 '051 스트릿 아트 프로젝트'가 K-컬처 특유의 "
     "에너지와 감각이 담긴 무대를 선보였습니다."),
    ("rss bscf2009 공연/연극 — 타이베이 ○○공원에서 열린", "[공연] 2026년 청년 K-컬처 글로벌 프런티어 대만 타이베이",
     "2026년 청년 K-컬처 글로벌 프런티어 대만 타이베이 | 2026.09.03 – 09.10 | 부산문화재단은 "
     "문화체육관광부 한국국제문화교류진흥원 청년 K-컬처 글로벌 프런티어 사업으로 부산 청년 문화예술인을 위한 "
     "해외 문화예술 활동 프로젝트 지원을 수행하였습니다. 부산의 청년들이 K-컬처를 품고 세계로 향했습니다. "
     "『청년 K-컬처 글로벌 프런티어』 기관제안형 4개 팀(김대경 Sextet, 루티드 사운즈, 밴드 팁시, 오직목소리)이 "
     "대만 타이베이 송산문화창의공원에서 열린 Songyan Festival 무대에 올라 K-POP과 K-컬처의 감성과 에너지를 "
     "관객에게 전했습니다."),
    ("snap 5801 bscf2009 blog_post — 해외 답사기", "[교육] 오픈서킷 부산: 대만 사례조사 1편",
     "✨ 오픈서킷 부산: 대만 사례조사 1편 ✨ 오래된 건물에서 오늘의 예술을 만났습니다. 10월 15일 목요일, "
     "오픈서킷 부산 참여예술가 10명과 함께 타이베이에 도착했습니다.  첫 번째 건물, 타이베이 현대미술관"
     "(MoCA Taipei) 붉은 벽돌 건물의 높은 창과 긴 복도는 그대로 두고, 그 안을 동시대 작품으로 채웠습니다."),
    ("(합성) 일시/장소 한 줄에 해외 장소", "[전시] 부산 청년작가 교류전",
     "✅ 일시/장소: 2026. 12. 5.(토) ~ 12. 20.(일) / 일본 후쿠오카 아시아미술관 ✅ 참여작가: 5명"),
    ("(합성) 해외 순회 공연", "[공연] 부산시립무용단 해외 순회공연", "유럽 3개 도시를 돌며 공연합니다."),
]

# (출처, 제목, 본문) — 부산에서 열린다 (나라 이름·교류·초청·해외 가 있어도) / held in Busan
IN_BUSAN = [
    ("snap 1232 vb_festival_curated — '부산에서 만나는 중국'", "부산에서 만나는 중국의 흥! 부산차이나타운특구 문화축제",
     "[🗓 일정 예정] 10월 중순 부산역 앞 차이나타운특구. 중국 문화 공연·먹거리 3일 행사 (2025: 10/17~19, "
     "2026 제23회: 10/16~18). | 부산역 앞은 역사적, 지리적 배경을 바탕으로 왜관, 청관, 미군 주둔 기지, "
     "외항선 등과 관련된 다양한 문화들이 존재해 왔다."),
    ("snap 5308 bsdonggublog festival — 차이나타운 문화축제", "제23회 부산 차이나타운 문화축제 개최 알림",
     "[🎪 현장 행사] 10월 중순 부산역 앞 차이나타운특구. 중국 문화 공연·먹거리 3일 행사 (2025: 10/17~19, "
     "2026 제23회: 10/16~18). | 붉은 등불 아래 펼쳐지는 이색 축제! 볼거리 즐길거리 먹거리가 가~득한 부산 "
     "차이나타운 문화축제로 놀러오세요❤️ 제23회 부산 차이나타운 문화축제 개최 화려한 무대 행사부터 왕홍 체험 "
     "등 다채로운 체험 프로그램까지! ❤️부산 차이나타운 축제에 놀러오세요❤️ 축제기간 : 10. 16.(금) ~ 10. 18.(일)"),
    ("snap 211 busan_festival — 부산국제영화제(출품)", "영화로 물드는 부산의 9월, 부산국제영화제",
     "[🎪 예매 (인터파크/예스24)] 10월 초 개막. 9월 중순 예매 시작. | 9월이 되면 부산은 또 하나의 바다에 "
     "빠져들게 된다. 바로 영화의 바다, 아시아 최고의 국제영화제 부산국제영화제가 바로 그것이다.\n\n아시아를 "
     "대표하는 영화제로 자리 잡은 부산국제영화제는 센텀시티 영화의 전당과 남포동 BIFF광장을 중심으로 치러진다. "
     "센텀시티의 메인 행사는 전 세계에서 출품된 다양한 영화"),
    ("snap 5314 hudpr — 부산국제영화제(59개국)", "제31회 부산국제영화제 개최｜영화의전당 일대 차량통제 안내",
     "✨ 부산이 다시 영화로 물듭니다! ✨ 세계 각국의 다양한 영화를 한자리에서 만나는 제31회 부산국제영화제가 "
     "개최됩니다.  영화의전당과 센텀시티, 남포동 등 부산 전역에서 열흘간 영화의 축제를 즐겨보세요. ✅ 기간: "
     "2026. 10. 6.(화)~10. 15.(목) / 10일간 ✅ 장소: 영화의전당, 센텀시티 및 남포동 등 부산 전역"),
    ("snap 1233 vb_festival_curated — 조선통신사축제('일본으로 파견된')", "한‧일 양국에 피어나는 봄꽃, 조선통신사축제",
     "[🗓 일정 예정] 5월 초. 4월 중순 체험단 모집. | 추위가 가신 완연한 부산의 봄날, 용두산 공원은 조선통신사 "
     "축제 행렬재현으로 분주하다. 조선통신사는 조선시대 일본으로 파견된 대규모 평화사절단으로, 국서를 받들고 "
     "가는 관료 이외에도 일본은 의사나 화가, 기예단원 등의 파견을 요청했다고 한다."),
    ("snap 3408 bsjunggu — 조선통신사 행렬('일본 초청 공연단')",
     "부산 중구조선통신사 행렬✨[함께 이어갈, 부산에서 세계로] 광복로 행렬 안내",
     "부산 중구에서 알려드립니다. 조선통신사 행렬✨ [함께 이어갈, 부산에서 세계로] ※ 2026년 조선통신사축제 연계 "
     "✅기간 : 2026년 4월 ~6월 / 9월 ~11월 넷째 주 토요일 일몰 전 총 6회 ✅장소 : 광복로 일원 (시티스팟 ~ "
     "분수광장) ✅내용 : 조선통신사 행렬 재현 및 홍보관 운영 1회차 : 4월 25일 토요일 13:00~14:00 동선 : "
     "부산근현대역사관 마당 → 시티스팟 → 분수광장 구성 : 취타대, 풍물패, 일본 초청 공연단, 청년예술가 및 "
     "예비 예술가, 유학생 등 시민행렬 참여"),
    ("snap 4846 hudpr — 한국·대만 교류 음악회(영화의전당)", "2026 한국·대만 청소년 교류 음악회",
     "✨2026 한국·대만 청소년 교류 음악회✨  푸른 물결, 하나의 선율! 한국과 대만 청소년들이 함께 만들어가는 "
     "아름다운 음악의 무대로 여러분을 초대합니다 ✅ 일시: 2026. 8. 8.(토) 17:00 ✅ 장소: 영화의전당 하늘연극장 "
     "✅ 출연  해운대구립 청소년오케스트라  대만 신베이시 청소년오케스트라  대만 롱푸초등학교 현악단"),
    ("snap 5414 bscf2009 festival — 프랑스 작가 레지던시(홍티아트센터)",
     "[행사] 홍티아트센터 입주작가 Clare Poolman 오픈스튜디오&작은 전시 안내",
     "안녕하세요, 부산문화재단입니다 이번에는 재단의 시각예술 레지던시 홍티아트센터 소식을 전달드립니다 프랑스 "
     "칸시와 부산시의 협약 하에, 작가 교류 프로그램인 '빌라 한불'을 운영 중입니다. 이번 2026년에는 Clare "
     "Poolman 작가님이 선정되어 9월 중순부터 홍티아트센터에 입주해 있습니다. 6주간 '지역의 사투리'를 주제로 "
     "리서치 진행해왔으며, 그 과정을 오픈스튜디오 및 전시로 풀어낼 예정입니다. ■ 오픈스튜디오 • 일시: "
     "10/24(토) 10:00~17:00 (12:30~13:30 휴게시간) • 장소: 홍티아트센터 내 작가님 스튜디오 (스튜디"),
    ("snap 3246 bscf2009 festival — 한일 비교문화 전시",
     "✨2026년도 문화다양성 가치확산 프로젝트 1회차 <사이를 여는 바다> - 비교문화 전시 <어서오세요 한일탕>",
     "[글로벌문화팀] ✨2026년도 문화다양성 가치확산 프로젝트 1회차  - 비교문화 전시  해양도시 부산의 역사성과 "
     "정체성을 바탕으로 ‘개방’과 ‘교류’를 주제로 진행되는 문화다양성 가치확산 프로젝트에서 준비한 비교문화 전시 ! "
     "부산과 일본, 두 목욕 문화를 나란히 놓으며 우리가 공유해 온 '온기'가 오늘날 어떤 의미로 흐르는지 함께 "
     "나누고자 합니다."),
    ("snap 3247 bscf2009 festival — 부산·일본·대만 기획자 포럼",
     "✨2026년도 문화다양성 가치확산 프로젝트 1회차 <사이를 여는 바다> 해양도시 문화기획자 포럼    "
     "<얽힘의 바다: 해양도시 예술 네트워크>",
     "[글로벌문화팀] ✨2026년도 문화다양성 가치확산 프로젝트 1회차  - 해양도시 문화기획자 포럼  부산문화재단은 "
     "문화다양성의 가치를 확산하고 동아시아 해양도시 간 문화교류의 기반을 마련하기 위해 해양도시 문화기획자 "
     "포럼 를 개최합니다.✨ 부산, 일본, 대만의 문화기획자들이 모여 바다로 연결된 도시들 사이에서 형성되어 온 "
     "문화교류와 예술적 네트워크를 심층적으로 조명하는 포럼에 많은 관심 부탁드립니다"),
    ("snap 53 bscf2009 festival — 아시아 문화교류 심포지엄",
     "✨2026년도 문화다양성 가치확산 프로젝트 1회차 <사이를 여는 바다> - 아시아 문화교류 심포지엄 "
     "<바다는 경계가 아니라 통로였다>",
     "✨2026년도 문화다양성 가치확산 프로젝트 1회차  - 아시아 문화교류 심포지엄  부산문화재단은 부산항 개항 "
     "150주년을 맞이하여 조선통신사에서 부산항 개항, 현재까지 이어진 역사 속에서 문화를 통해 구축되어 온 평화와 "
     "교류의 의미를 조명합니다✨ 동아시아 해양도시 간 문화교류의 가치와 가능성, 그리고 평화의 역사를 "
     "만나보시기 바랍니다☺️"),
    ("snap 74 bscf2009 — 국제교류 워크숍(해외 전문가)", "장애 포용예술 국제교류 워크숍 안내",
     "다가오는 11월 장애예술인 창작공간 온그루에서 장애와 비장애, 예술가와 시민이 함께 만나 어우러지는 장애 "
     "포용예술 국제교류 워크숍이 열립니다! 기간은 11월 4일, 6일, 11일 총 3일간 다양한 워크숍이 진행됩니다. "
     "해외 전문가들과 함께 몸으로 느끼고 마음으로 나누는 따뜻한 예술의 시간을 경험해 보세요."),
    ("snap 5399 hudpr festival — 세계문화축제(우즈베키스탄 공연)", "제2회 해운대 세계문화축제 개최",
     "✨ 세계의 음식과 문화를 한자리에서 즐겨보세요! ✨ 다양한 나라의 음식과 문화체험, 공연이 한곳에 모이는 "
     "「제2회 해운대 세계문화축제」가 구남로 일원에서 열립니다. 가족·친구와 함께 세계 문화를 가까이에서 "
     "만나보세요. ✅ 일시: 2026. 10. 25.(일) 11:00~18:00 ✅ 장소: 구남로 일원 ✅ 주요 프로그램  글로벌도시"
     "관광로드쇼 부스  세계문화체험 부스  세계음식 부스  우즈베키스탄 도시 문화공연"),
    ("snap 3208 cooolbusan — 부산국제단편영화제(프랑스 주빈국)",
     "제43회 부산국제단편영화제 개막, 시네마와 빛의 향연 속으로 여러분을 초대합니다",
     "부산시는 오는 4월 23일부터 28일까지 6일간 영화의전당과 비엔케이(BNK) 부산은행 아트시네마 모퉁이극장에서 "
     "제43회 부산국제단편영화제를 개최합니다. 영화의 발상지인 프랑스를 주빈국으로 선정하여 단편 영화가 가진 "
     "고유의 매력과 예술적 가치를 심도 있게 조명하는 만큼"),
    ("snap 4656 bexco festival — 국제 아트페어", "제 25회 유라시아피스랠리와 함께하는 2026 부산국제아트페어",
     "벡스코 제2전시장 4(C-F)홀 · D-12"),
    ("snap 4436 bexco festival — 아시아콘텐츠&필름마켓", "2026 아시아콘텐츠&필름마켓", "벡스코 제2전시장 4홀 · 진행중"),
    ("snap 5724 bsdonggublog — '해외 진출 전략 설명회'(벡스코)", "[2026 부산 KFA 프랜차이즈 창업박람회] 개최",
     "예비창업자에게 다양한 창업정보를 제공하고, 지역 프랜차이즈산업의 경쟁력 강화를 위해 2026 부산 KFA"
     "(한국프랜차이즈산업협회) 프랜차이즈 창업박람회를 개최합니다. 특히, 올해는 국내 기업과 지역 소상공인의 "
     "글로벌 성장을 지원하고, 국가별 시장현황과 진출 노하우를 공유하는 '해외 진출 전략 설명회'가 있으니 참고 "
     "부탁드립니다! [2026 부산 KFA 프랜차이즈 창업박람회] ☑️ 기간/장소 : 2026. 11. 12.(목) ~ 11. 14.(토) / "
     "벡스코 제1전시장 3B홀"),
    ("rss bscf2009 공연/연극 — 해외 파견 성과공유회(제목에 해외 지명 없음)",
     "[공연] 2026년 청년 K-컬처 글로벌 프런티어 사업 성과공유회",
     "2026년 청년 K-컬처 글로벌 프런티어 사업 성과공유회 2026년 여름, 대만·오스트리아·영국 3개국 현지에서 직접 "
     "부딪히며 K-컬처의 매력을 알리고 돌아온 6팀의 청년 예술가들이 한자리에 모였습니다. 대만 타이베이 송옌 "
     "페스티벌 공식 초청 무대부터 영국 현지 아티스트와의 공동창작 레지던시"),
    ("live art_busan — 부문: 국제(미술관 안)", "Future Museology 퓨쳐뮤지올로지",
     "부문: 국제 · 장소: 미술관 3층 - 1전시실 · 작품수: 30"),
    ("snap 5347 bsdonggublog — 일본어(지명 아님)", "✏️신노년층 대상, 말하고 쓰고 노래하는 일본어 특강 수강생 모집",
     "55세~74세 신노년층을 위한 맞춤형 일본어 수업 수강생을 모집합니다. 「하하센터 동구 수정」에서 쉽고 친숙하게 "
     "참여할 수 있는 활동 중심의 일본어 수업을 소개합니다!"),
    ("snap 5753 bsdonggublog — '빈'용기(빈 아님)", "2027년 소매점 대상 빈용기 무인회수기 구매지원 사업 안내",
     "빈용기 무인회수기 구매지원으로 친환경 스마트 매장의 첫걸음을 시작하세요! ✅ 신청대상 : 소매점"),
    ("(합성) 부산 전시장의 일본 작가전 — 장소 항목 없음", "[전시] 일본 작가 5인전 <바다 건너온 시선>",
     "일본 작가 5명이 참여하는 전시입니다. 많은 관심 부탁드립니다."),
    # 해외 활동 표현('일본 순회', '유럽 투어')이 있어도 '내한'·'부산에서' 면 부산 공연
    ("(합성) 해외 공연단 내한", "[공연] 일본 후쿠오카 시립합창단 내한 공연",
     "일본 순회 공연을 마친 후쿠오카 시립합창단이 첫 내한 무대를 엽니다."),
    ("(합성) 해외 투어 뒤 부산 공연", "[공연] 유럽 투어 앙코르 콘서트",
     "유럽 투어를 마친 밴드가 부산에서 앙코르 무대를 엽니다."),
    # 장소 값에 해외 지명이 있어도 부산 지명이 같이 있으면 부산
    ("(합성) 장소 값에 부산 + 나라 이름", "중국 문화 체험 한마당", "✅ 장소: 부산역 앞 차이나타운 중국 문화의 거리"),
    ("빈 값 / empty", "", None),
]


def _case(cases, prefix):
    return next(c for c in cases if c[0].startswith(prefix))


class IsOverseasEvent(unittest.TestCase):
    def test_abroad(self):
        for label, title, desc in ABROAD:
            with self.subTest(label):
                self.assertTrue(is_overseas_event(title, desc))

    def test_held_in_busan(self):
        for label, title, desc in IN_BUSAN:
            with self.subTest(label):
                self.assertFalse(is_overseas_event(title, desc))

    def test_venue_field_decides(self):
        # 장소가 하나라도 부산이면 부산 행사 / any Busan venue keeps the event
        self.assertFalse(is_overseas_event(
            "[공연] 대만 타이베이 교류 공연", "장소: 대만 타이베이 국가음악청 ✅ 장소: 부산문화회관 대극장"))
        # 낱말 가운데 낀 나라 이름은 지명으로 세지 않는다 / country name inside a word is not a place
        self.assertFalse(is_overseas_event("특별전", "장소: 주부산일본국총영사관 홍보실"))
        self.assertFalse(is_overseas_event("[공연] 2026 단독일정 발표", "유럽 투어 일정을 공개합니다"))


class NaverBlogsApply(unittest.TestCase):
    """naver_blogs: 해외 행사는 blog_post 로 — 글은 남고(읽을거리) 주말 행사에서만 빠진다."""

    def test_abroad_to_post(self):
        for cat in ("festival", "performance", "exhibition"):
            with self.subTest(cat):
                self.assertEqual(nb._abroad_to_post(cat, LISHUI_TITLE, LISHUI_DESC), "blog_post")
        self.assertEqual(nb._abroad_to_post("blog_post", LISHUI_TITLE, LISHUI_DESC), "blog_post")
        _, t, d = _case(IN_BUSAN, "snap 1232")
        self.assertEqual(nb._abroad_to_post("festival", t, d), "festival")

    def test_fetch_keeps_record_as_blog_post(self):
        _, busan_title, busan_desc = _case(IN_BUSAN, "snap 4846")  # 한국·대만 교류 음악회(영화의전당)
        rss = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
<item><title><![CDATA[{LISHUI_TITLE}]]></title>
<link>https://blog.naver.com/bscf2009/224455089307?fromRss=true&amp;trackingCode=rss</link>
<category><![CDATA[행사/축제]]></category>
<description><![CDATA[{LISHUI_DESC}]]></description>
<pubDate>Tue, 27 Oct 2026 10:15:43 +0900</pubDate></item>
<item><title><![CDATA[{busan_title}]]></title>
<link>https://blog.naver.com/hudpr/1?fromRss=true</link>
<category><![CDATA[행사/축제]]></category>
<description><![CDATA[{busan_desc}]]></description>
<pubDate>Wed, 29 Jul 2026 10:00:00 +0900</pubDate></item>
</channel></rss>"""
        parsed = feedparser.parse(rss)
        with mock.patch.object(nb, "NAVER_OFFICIAL_BLOGS", [("bscf2009", "Busan Culture Fdn")]), \
                mock.patch.object(nb, "_parse_feed", return_value=parsed):
            events = nb.fetch()
        self.assertEqual([e.category for e in events], ["blog_post", "festival"])
        lishui = events[0]
        # 레코드·행사 기간은 그대로 / record and its event period are kept
        self.assertEqual((lishui.source, lishui.source_id), ("naver_blog:bscf2009", "224455089307"))
        self.assertEqual((lishui.start_date, lishui.end_date), ("2026-10-23", "2026-11-23"))


class ArtBusanApply(unittest.TestCase):
    """art_busan: 미술관이 해외에서 여는 전시는 부산시립미술관 좌표로 싣지 않는다."""

    def test_skips_exhibition_held_abroad(self):
        html = ('<a href="/tblTsite07Display/viewNowClient.nm?id=A1">젊은 시각 새로운 시선 해외전</a>'
                '<a href="/tblTsite07Display/viewNowClient.nm?id=B2">Future Museology 퓨쳐뮤지올로지</a>')
        details = {
            "A1": {"start": "2026-08-23", "end": "2026-10-07", "place": "중국 금일미술관",
                   "section": "해외", "works": "60"},
            "B2": {"start": "2026-09-17", "end": "2027-03-14", "place": "미술관 3층 - 1전시실",
                   "section": "국제", "works": "30"},
        }
        with mock.patch.object(art_busan.session, "soup", return_value=BeautifulSoup(html, "html.parser")), \
                mock.patch.object(art_busan, "_parse_detail", side_effect=lambda u: details[u.rsplit("=", 1)[1]]), \
                mock.patch("sys.stderr"):
            events = art_busan._fetch_list("https://example.invalid/list", "viewNowClient")
        self.assertEqual([e.source_id for e in events], ["B2"])


if __name__ == "__main__":
    unittest.main()
