"""해외에서 열리는 행사(부산 예술가의 해외 파견·출품·참여 소식)를 가려내는 순수 함수.

Detects "held abroad" posts — e.g. Busan artists taking part in a festival in China — so they
are not shown as weekend events the family can go to (pure, no I/O).

왜 필요한가 / Why:
  부산문화재단 블로그의 '[행사] 청년예술가 국제교류 사업 「중국 리수이 국제 사진제」 참여'
  (전시장소: 중국 리수이 사진 박물관) 가 festival 로 잡혀 토요일 추천 9위에 올랐다.
  나라 이름만으로 거르면 '부산에서 만나는 중국의 흥! 차이나타운 문화축제', 한·대만 교류 음악회
  (영화의전당) 같은 부산 행사까지 빠지므로, **열리는 곳이 해외**라는 신호만 본다.
  / Country names alone are not enough — Busan hosts many Chinese/Japanese/international events.

규칙 / Rules (보수적 — 애매하면 False, 즉 행사로 남긴다):
  1) 본문에 '장소:' 항목이 있으면 그것으로 판정한다(가장 확실한 신호).
     모든 장소 값이 해외 지명으로 **시작**하고('중국 리수이 사진 박물관', 앞의 날짜는 건너뜀)
     부산·국내 지명(서울·대구·경주 …)이나 국내 기관 꼴(시립·국립 … 미술관, 예술의전당)이 없을 때만 True.
     장소가 하나라도 부산·국내·미상이면 False ('서울시립미술관 중국현대미술 특별전', '대구미술관 일본관').
  2) '장소:' 항목이 없으면 제목에 해외 지명(나라·도시·'해외')이 있고,
     제목이나 본문에 '해외로 가서 하는' 표현이 있을 때만 True:
       - 해외 지명 + 조사 + 동사: '리수이 국제 사진제에 참여', '타이베이 ○○공원에서 열린', '타이베이에 도착'
       - 해외 지명 + 파견/진출/원정, 바로 뒤 투어/순회: '영국 파견팀', '일본 투어', '해외 순회'
       - 제목의 '해외전', '해외 공연', '해외 전시'
     단 '부산에서', '내한', '방한' 이 있으면 부산에서 열리는 행사로 보고 False.
  나라 이름 뒤 '어/인/식/계/산'(일본어·중국인·일본식…)은 지명이 아니라서 세지 않는다.
  '인도(보도)', '빈(빈 점포)', '칸', '파리', '상해(다침)', '선전' 처럼 흔한 우리말과 겹치는 이름은 뺐다.
"""
from __future__ import annotations

import re

__all__ = ["is_overseas_event"]

# 해외 지명 / foreign place names (단어 첫머리에서만 — '단독일정' 의 '독일', '경영국' 의 '영국' 방지)
_COUNTRIES = (
    "중국|일본|미국|프랑스|독일|영국|대만|타이완|베트남|태국|싱가포르|홍콩|마카오|몽골|러시아|"
    "호주|뉴질랜드|캐나다|이탈리아|스페인|포르투갈|네덜란드|벨기에|스위스|오스트리아|체코|폴란드|"
    "헝가리|그리스|튀르키예|덴마크|스웨덴|노르웨이|핀란드|아일랜드|인도네시아|필리핀|말레이시아|"
    "캄보디아|라오스|미얀마|우즈베키스탄|카자흐스탄|멕시코|브라질|아르헨티나|이집트|이스라엘|유럽|"
    "해외|국외"
)
_CITIES = (
    "도쿄|오사카|후쿠오카|교토|나고야|요코하마|삿포로|나가사키|기타큐슈|시모노세키|쓰시마|대마도|"
    "오키나와|상하이|베이징|리수이|칭다오|광저우|항저우|하얼빈|다롄|충칭|톈진|타이베이|가오슝|"
    "타이중|하노이|호찌민|호치민|다낭|방콕|치앙마이|마닐라|자카르타|쿠알라룸푸르|울란바토르|"
    "블라디보스토크|모스크바|런던|글래스고|에든버러|리옹|아비뇽|베를린|뮌헨|함부르크|잘츠부르크|"
    "프라하|부다페스트|밀라노|베네치아|피렌체|바르셀로나|마드리드|리스본|암스테르담|로테르담|"
    "브뤼셀|코펜하겐|스톡홀름|헬싱키|뉴욕|로스앤젤레스|샌프란시스코|시애틀|시카고|보스턴|토론토|"
    "밴쿠버|시드니|멜버른|두바이"
)
_FOREIGN = rf"(?<![가-힣A-Za-z0-9])(?:{_COUNTRIES}|{_CITIES})(?![어인식계산도])"
_FOREIGN_RE = re.compile(_FOREIGN)

# 부산 지명·대표 장소 — 장소 값에 하나라도 있으면 부산 행사 / Busan place words in a venue value
_BUSAN_RE = re.compile(
    r"부산|해운대|광안|벡스코|BEXCO|영화의\s*전당|차이나타운|서면|남포|센텀|기장|송정|다대포|용두산|"
    r"광복|영도|동래|금정|사하|사상|수영|연제|을숙도|감천|태종대|초량|부전|전포|민락|구남로|"
    r"홍티|감만|온그루|F1963|한성1918|블루포트|시민공원|시민회관|문화회관|이우환",
    re.IGNORECASE,
)

# '장소:' 항목 (전시장소·공연장소·행사장소·기간/장소·장 소 …) 과 그 값 / venue field and its value
_VENUE_LABEL_RE = re.compile(r"(?:장\s*소|개최지)\s*(?:[:：]|[-–](?=\s))\s*")
_VALUE_STOP_RE = re.compile(
    r"[✅☑✔•■□◆◇▶▷►※|\n\r]|\s{2,}|\s·\s|\s[가-힣]{1,6}\s*[:：]"   # 다음 기호·다음 항목명에서 끊는다
)
_VALUE_MAX = 40
# 장소 값 앞의 날짜·시간 ('기간/장소 : 2026. 12. 5.(토) ~ 12. 20.(일) / 일본 …') — 요일은 괄호 안만
_LEADING_DATE_RE = re.compile(r"^(?:[\d\s.,:~∼～\-–/]|\([월화수목금토일](?:요일)?\))*")
# 장소 값이 해외 지명으로 **시작**할 때만 해외 ('중국 리수이 사진 박물관', '영국 글래스고 …')
_FOREIGN_FIRST_RE = re.compile(r"^[\s(\[「『<]*" + _FOREIGN)
# 국내(부산 밖) 지명·국내 기관 꼴 — 있으면 해외로 보지 않는다 / domestic signals
# 지명은 낱말 첫머리에서만 ('초대전' 의 '대전', '방청도장' 의 '청도' 방지)
_DOMESTIC_RE = re.compile(
    r"(?<![가-힣])(?:서울|경기도|인천|대구|대전|광주|울산|세종|강원|충북|충남|충청|전북|전남|전라|경북|"
    r"경남|경상|제주|서귀포|김해|창원|양산|거제|통영|진주|경주|포항|수원|성남|고양|용인|부천|안산|안양|"
    r"청주|천안|전주|군산|여수|순천|목포|춘천|원주|강릉|속초|구미|안동|밀양|사천)"
    r"|예술의\s*전당|(?:시립|도립|국립|구립|군립)\s*[가-힣]{0,8}(?:미술관|박물관|도서관|극장|공연장|아트센터|회관)"
)

# 해외로 가서 하는 일 / "doing it abroad"
_GAP = r"[^.!?。\n]{0,20}?"   # 같은 문장 안 20자 이내 / same sentence, ≤20 chars
_ABROAD_ACT_RE = re.compile(
    rf"{_FOREIGN}{_GAP}(?:에서|에|으로|로)\s*"
    r"(?:참여|참가|출품|진출|파견|초청|초대|공연|전시|열리|열린|열려|개최|진행|선보|도착|입성|무대)"
    rf"|{_FOREIGN}(?:\s?[가-힣]{{1,4}})?\s?(?:파견|진출|원정)"
    rf"|{_FOREIGN}\s?(?:투어|순회)"
)
_ABROAD_TITLE_RE = re.compile(r"해외\s?(?:전(?![문략통])|전시|공연|순회|투어|파견|진출|원정)")
# 부산에서 열린다는 말 / says it happens in Busan
_HERE_RE = re.compile(r"부산에서|내한|방한")


def _venue_values(text: str) -> list[str]:
    values = []
    for m in _VENUE_LABEL_RE.finditer(text):
        v = text[m.end():m.end() + _VALUE_MAX]
        stop = _VALUE_STOP_RE.search(v)
        v = (v[:stop.start()] if stop else v).strip()
        if v:
            values.append(v)
    return values


def _abroad_venue(value: str) -> bool:
    """장소 값이 해외인가: 해외 지명으로 시작하고, 부산·국내 지명이나 국내 기관 꼴이 없을 때만.
    / A venue is abroad only if it starts with a foreign place and has no Busan/domestic signal."""
    place = _LEADING_DATE_RE.sub("", value)
    return bool(_FOREIGN_FIRST_RE.search(place)) and not _BUSAN_RE.search(value) \
        and not _DOMESTIC_RE.search(value)


def is_overseas_event(title: str | None, description: str | None) -> bool:
    """행사가 해외에서 열리면 True (장소 항목 → 제목의 해외 지명 + 해외 활동 표현 순).
    / True when the post is about something held abroad (venue field first, then title signals)."""
    title = title or ""
    text = description or ""

    values = _venue_values(text)
    if values:
        return all(_abroad_venue(v) for v in values)

    if not _FOREIGN_RE.search(title):
        return False
    if _HERE_RE.search(title) or _HERE_RE.search(text):
        return False
    return bool(
        _ABROAD_TITLE_RE.search(title)
        or _ABROAD_ACT_RE.search(title)
        or _ABROAD_ACT_RE.search(text)
    )
