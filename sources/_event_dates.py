"""블로그 글 본문에서 '행사가 실제로 열리는 날짜(기간)'를 뽑는 순수 함수.

Korean event-date-range extractor for official blog posts (pure, no I/O).

왜 필요한가 / Why:
  네이버 블로그 RSS 의 날짜는 **게시일**이다. 구청 블로그는 행사 1~3주 전에 안내글을 올리므로
  게시일을 행사 시작일로 쓰면 정작 행사가 열리는 주말 추천에서 빠진다.
  / RSS pubDate is the *post* date; district blogs announce events 1-3 weeks ahead.

규칙 / Rules (보수적 — 애매하면 None):
  1) 날짜 표기: '2026. 10. 24.(토)', '2026.10.24', '2026-10-24', '2026년 10월 24일',
     "'26. 6. 22.", '10. 24.(토)', '10.24.(토)', '10월 24일(토)', '9월 22일 화요일', 제목의 '6/20'.
     기간: '~ ∼ ～ - 부터' 로 이어진 두 날짜, 끝이 일(日)만 있는 '10.24.(토)~25.(일)' 도 인식.
  2) 날짜 바로 앞 항목명(label) 으로 판정:
     - 행사 항목 = 일시/기간/일정/날짜/일자 로 끝나는 항목 (행사일시·축제기간·운영기간·일 시 …)
     - 제외 항목 = 신청·접수·모집·공모·발표·교육·납부·휴관 … (행사 날짜가 아니다).
       맨 '기간:' 은 바로 위 소제목('사전예약', '신청안내')이 접수 쪽이면 제외.
     - '…까지', '~ 10. 2.' 처럼 끝만 있는 날짜는 마감일, '(1. 7. 발행)' 은 발행일이라 쓰지 않는다.
  3) 우선순위: 제목 속 날짜 → 본문 '행사 항목' 날짜 → 항목명 없는 날짜(basis='text').
     항목명 없는 날짜는 글에 모집·신청 신호나 제외 항목이 하나도 없을 때만 돌려준다.
     제목 속 날짜가 제외 항목이거나, 제목이 휴관·취소 공지거나, 본문에 '취소 되었습니다'가
     있으면 글 전체를 None.
  4) 연도 없는 날짜는 게시일로 추정: 요일이 맞는 해 → 게시일과 가까운 해(과거 쪽은 2배 멀게 계산,
     약 4개월 전까지만 과거로 본다) → 12월 글의 '1. 3.(토)' 는 다음 해 (Dec→Jan rollover).
     '지난 8월 11일' 처럼 과거 신호가 있으면 게시일 이전 해.
  5) 이미 끝난 날짜(끝 < 게시일: 후기·결과 글), 180일 넘는 기간, 게시일 300일 뒤는 버린다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple

__all__ = ["EventPeriod", "extract_event_period"]

_WEEKDAYS = "월화수목금토일"
MAX_SPAN_DAYS = 180       # 이보다 긴 기간은 사업·공고 기간일 확률이 높다 / longer = programme/admin period
MAX_AHEAD_DAYS = 300      # 게시일 기준 너무 먼 미래는 오인식 / too far ahead = misparse


class EventPeriod(NamedTuple):
    start: str   # ISO date
    end: str     # ISO date (하루 행사면 start 와 같다 / same as start for one-day events)
    basis: str   # 'title' | 'label' | 'text' — 어디서 찾았나 (신뢰도: title≈label > text)


# ─────────────────────────────────────────────────────────────────────
# 날짜 토큰 / date atoms — 순서가 곧 우선순위(긴 형식 먼저)
# ─────────────────────────────────────────────────────────────────────
_ATOM = re.compile(
    r"(?P<ymd>(?<!\d)(?P<y1>20\d{2})\s*[.\-/]\s*(?P<m1>\d{1,2})\s*[.\-/]\s*(?P<d1>\d{1,2})(?!\d)\.?)"
    r"|(?P<ymdk>(?<!\d)(?P<y2>20\d{2})\s*년\s*(?P<m2>\d{1,2})\s*월\s*(?P<d2>\d{1,2})\s*일)"
    # '26. 6. 22. / ’26년 6월 22일 / 26. 2.26. (앞 숫자가 월이 될 수 없는 24~29 만)
    r"|(?P<yy>(?:['’‘`]\s?|(?<![\d.]))(?P<y3>2[4-9])\s*[.년]\s*(?P<m3>\d{1,2})\s*[.월]\s*(?P<d3>\d{1,2})(?!\d)\s*[.일]?)"
    r"|(?P<mdk>(?<!\d)(?P<m4>\d{1,2})\s*월\s*(?P<d4>\d{1,2})\s*일)"
    # 10. 24. / 10.24.(토) / 8. 30 (일) — 소수(2.5m)와 구분하려고 끝 '.' 또는 요일 괄호 필수
    r"|(?P<md>(?<![\d.])(?P<m5>\d{1,2})\s*\.\s*(?P<d5>\d{1,2})(?:\s*\.(?!\d)|(?=\s*\(\s*[월화수목금토일])))"
    # 6/20 — 분수(1/2)·URL 과 헷갈려서 제목에서만, 본문은 요일이 붙을 때만 쓴다
    r"|(?P<sl>(?<![\d/.:])(?P<m6>\d{1,2})/(?P<d6>\d{1,2})(?![\d/]))"
)
# 요일: (토) (토요일) 토요일
_WD_AFTER = re.compile(r"\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*(?:[,)·/]|$)|([월화수목금토일])요일)")
# 날짜 뒤 시간 꼬리 / trailing time: ', 9:00' '오후 3시 30분' '14:00'
_TIME = r"(?:\s*,?\s*(?:(?:오전|오후)\s*)?\d{1,2}(?::\d{2}|\s*시(?:\s*\d{1,2}\s*분)?))?"
_RANGE_SEP = re.compile(_TIME + r"\s*(~|∼|～|〜|-|–|—|부터)\s*")
# 범위 끝이 '일'만 있을 때 / day-only range end: '~25.(일)' '~ 25일'
_DAY_ONLY = re.compile(r"(\d{1,2})\s*(?:일|\.(?!\d))")
_DAY_ONLY_SLASH = re.compile(r"(\d{1,2})(?=\s*[)\]]|\s*$)")      # 제목 '(4/3~5)'
_UNTIL_AFTER = re.compile(r"(?:\s*\([^)]{1,6}\))?" + _TIME + r"\s*(?:까지|마감)")
_OPEN_BEFORE = re.compile(r"[~∼～〜]\s*$")
# '(1. 7. 발행)' '(2026. 4. 8. 기준)' — 날짜 뒤에 붙는 비행사 꼬리 / non-event suffix
_REJECT_AFTER = re.compile(r"\s*(?:발행|기준|현재)")

# 항목명 / field labels
_SEP_CHARS = r"[✅☑✔✓▶▷►•■□◆◇○●◎❏❍※*\n\r|❤⭐✨\ufe0f\u200d]"  # \ufe0f·\u200d = 이모지 꼬리(variation selector, ZWJ)
_SEPARATORS = re.compile(_SEP_CHARS + r"|\s{2,}")
_TRAILING_SEPS = re.compile(r"(?:" + _SEP_CHARS + r"|\s)+$")
_EVENT_LABEL = re.compile(
    r"(?:일\s*시|기\s*간|일\s*정|날\s*짜|일\s*자)"
    r"(?:\s*[/및·,]\s*[가-힣]{1,4})?"          # '일시/장소 :' '일시 및 장소:'
    r"\s*(?:은|는)?\s*[:：│|∣\]】>)]?\s*$"
)
# 항목명 끝부분 = 바로 앞 한 낱말 + 일시/기간 … ('행사 일시:', '신청기간:', '접수 일시:')
_LABEL_TAIL = re.compile(r"[가-힣]*\s?" + _EVENT_LABEL.pattern)
_BARE_LABEL = re.compile(r"(?:일\s*시|기\s*간|일\s*정|날\s*짜|일\s*자)\s*[:：│|∣]?")
# 맨 '기간:' 위의 소제목이 '신청안내' '사전예약 (40명 선착순!)' 류면 그 기간은 접수 기간
_REJECT_HEADING = re.compile(r"(?:사전|온라인|참가|참여)?\s*(?:신청|접수|모집|예약|예매|공모)")
_REJECT_LABEL = re.compile(
    r"신청|접수|모집|공모|마감|발표|납부|조사|공고|추천|계약|공사|신고|지급|훈련|휴관|휴무|휴장|"
    r"휴업|휴실|휴강|점검|배부|시범|근로|시행|해제|선정|결과|사업|활동|적용|이의|예매|예약|티켓|입금|제출|등록|"
    r"당첨|교육|수업|연수|상담|참여\s*기간|참가\s*기간|이벤트|게시|작성|열람|단속|채용|면접|심사|"
    r"서류|정산|통보|기존|변경\s*전|제외|챌린지"
)
_CONTINUATION = re.compile(r"^[\s,/·및]*$")
_PAST_CUE = re.compile(r"(?:지난|지난해|작년)\s*$")
# 글 전체에 이런 말이 있으면 항목명 없는 날짜는 믿지 않는다 / distrust unlabelled dates
_RECRUIT_DOC = re.compile(r"모집|공모|신청|접수|선착순|채용|참가자|참여자")
_RECRUIT_TITLE = re.compile(r"모집|공모|접수|신청|채용|선정\s*결과|결과\s*발표|당첨")
# 휴관·취소 공지는 날짜가 있어도 '열리는 행사'가 아니다 / closure & cancellation notices
_NON_EVENT_TITLE = re.compile(r"휴관|휴무|휴업|휴실|휴장|휴강|취소")
# 본문 맨 앞에 덧붙는 '본 행사는 … 취소 되었습니다' 공지. '우천 시 취소' 같은 조건문은 안 걸린다.
_CANCELLED = re.compile(r"취소\s*(?:되었|됐|되어)|행사\s*취소\s*(?:알림|공지|안내)|전면\s*취소")


class _Mention(NamedTuple):
    start: date
    end: date
    kind: str      # 'single' | 'range' | 'until'(…까지 / ~X) | 'from'(…부터, 끝 없음)
    label: str     # 'event' | 'reject' | 'none'


def _to_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _resolve_year(m: int, d: int, wd: str | None, post: date, past: bool = False) -> date | None:
    """연도 없는 월·일 → 날짜.

    요일이 적혀 있으면 요일이 맞는 해만 후보. 그중 게시일과 가장 가까운 해를 고르되 과거 쪽 거리는
    2배로 친다(안내글은 보통 행사 전에 올라온다) → 약 4개월 전까지는 과거, 그보다 멀면 다음 해.
    '지난 8월 11일' 처럼 과거 신호가 있으면 게시일 이전 해 중 가장 가까운 것.
    """
    cands = [c for y in (post.year - 1, post.year, post.year + 1) if (c := _to_date(y, m, d))]
    if wd:
        cands = [c for c in cands if _WEEKDAYS[c.weekday()] == wd] or cands
    if not cands:
        return None
    if past:
        before = [c for c in cands if c <= post]
        if before:
            return before[-1]
    return min(cands, key=lambda c: (c - post).days if c >= post else 2 * (post - c).days)


def _month_day(m: re.Match) -> tuple[int, int] | None:
    """연도 없는 토큰의 (월, 일). 연도 있는 토큰이면 None."""
    g = m.groupdict()
    for mk, dk in (("m4", "d4"), ("m5", "d5"), ("m6", "d6")):
        if g[mk]:
            return int(g[mk]), int(g[dk])
    return None


def _atom_date(m: re.Match, wd: str | None, post: date, past: bool) -> date | None:
    g = m.groupdict()
    if g["ymd"]:
        return _to_date(int(g["y1"]), int(g["m1"]), int(g["d1"]))
    if g["ymdk"]:
        return _to_date(int(g["y2"]), int(g["m2"]), int(g["d2"]))
    if g["yy"]:
        y = 2000 + int(g["y3"])
        return _to_date(y, int(g["m3"]), int(g["d3"])) if abs(y - post.year) <= 1 else None
    md = _month_day(m)
    return _resolve_year(md[0], md[1], wd, post, past) if md else None


def _weekday_at(text: str, pos: int) -> tuple[str | None, int]:
    w = _WD_AFTER.match(text, pos)
    if not w:
        return None, pos
    return (w.group(1) or w.group(2)), w.end()


def _end_from(start: date, m: int, d: int) -> date | None:
    """범위 끝(연도 없음) → 시작일 연도 기준, 시작보다 앞이면 다음 해 (12/26~1/4)."""
    e = _to_date(start.year, m, d)
    if e and e < start:
        e = _to_date(start.year + 1, m, d)
    return e


def _last_segment(s: str) -> tuple[str, int]:
    """구분자(✅, 두 칸 공백 …) 뒤 마지막 조각과 그 시작 위치."""
    trimmed = s.rstrip()
    cut = 0
    for sm in _SEPARATORS.finditer(trimmed):
        cut = sm.end()
    return trimmed[cut:].strip(), cut


def _label_of(text: str, lo: int, s: int, prev_label: str | None) -> str:
    """날짜 바로 앞 항목명 판정 → 'event' | 'reject' | 'none'."""
    pre = text[max(lo, s - 24):s]
    if prev_label and lo > 0 and _CONTINUATION.match(pre):
        return prev_label  # '9. 2.(수), 9. 4.(금)' — 앞 항목에 이어지는 날짜
    seg, _ = _last_segment(pre)
    tail = _LABEL_TAIL.search(seg)
    if not tail:
        return "reject" if _REJECT_LABEL.search(seg) else "none"
    # 항목명 자체(바로 앞 낱말 + 일시/기간 …)만 본다: '참가 신청 및 행사 일시:' 는 행사 일시,
    # '신청 기간:' '접수 일시:' 는 접수 쪽. / judge the label word itself, not words before it
    if _REJECT_LABEL.search(tail.group(0)):
        return "reject"
    if _BARE_LABEL.fullmatch(seg):
        # 맨 '기간:' 은 바로 위 소제목을 본다: '✅ 사전예약 ✔️ 기간: 7. 13.' 은 예약 기간
        # / a bare '기간:' inherits the heading above it ('사전예약', '신청안내' …)
        wide = text[max(lo, s - 64):s].rstrip()
        _, cut = _last_segment(wide)
        above, _ = _last_segment(_TRAILING_SEPS.sub("", wide[:cut]))
        if len(above) <= 20 and _REJECT_HEADING.match(above):
            return "reject"
    return "event"


def _scan(text: str, post: date, *, slash_ok: bool) -> list[_Mention]:
    out: list[_Mention] = []
    pos = 0
    prev_end, prev_label = 0, None
    while (m := _ATOM.search(text, pos)):
        s = m.start()
        wd, after = _weekday_at(text, m.end())
        if m.group("sl") and not (slash_ok or wd):
            pos = m.end()
            continue
        past = bool(_PAST_CUE.search(text[max(0, s - 6):s]))
        start = _atom_date(m, wd, post, past)
        if start is None:
            pos = m.end()
            continue
        end, kind = start, "single"
        sep = _RANGE_SEP.match(text, after)
        if sep:
            q = sep.end()
            nm = _ATOM.match(text, q)
            if nm and not (nm.group("sl") and not slash_ok):
                ewd, eafter = _weekday_at(text, nm.end())
                md = _month_day(nm)
                e = _end_from(start, *md) if md else _atom_date(nm, ewd, post, past)
                if e and e >= start:
                    end, kind, after = e, "range", eafter
                # else: 거꾸로 된 범위 → 끝 날짜는 다음 반복에서 따로 본다 / reversed: scan separately
            elif (dm := (_DAY_ONLY_SLASH if m.group("sl") else _DAY_ONLY).match(text, q)):
                e = _to_date(start.year, start.month, int(dm.group(1)))
                if e and e > start:
                    _, eafter = _weekday_at(text, dm.end())
                    end, kind, after = e, "range", eafter
            elif sep.group(1) == "부터":
                kind = "from"
        if kind == "single" and (
            _UNTIL_AFTER.match(text, after) or _OPEN_BEFORE.search(text[max(0, s - 3):s])
        ):
            kind = "until"
        label = _label_of(text, prev_end, s, prev_label)
        if _REJECT_AFTER.match(text, after):
            label = "reject"
        out.append(_Mention(start, end, kind, label))
        prev_end, prev_label = after, label
        pos = max(after, m.end())
    return out


def _usable(mn: _Mention, post: date) -> bool:
    if mn.kind not in ("single", "range"):
        return False
    if mn.end < post:                                   # 이미 끝난 행사 (후기·결과 글)
        return False
    if (mn.end - mn.start).days > MAX_SPAN_DAYS:
        return False
    return (mn.start - post).days <= MAX_AHEAD_DAYS


def _as_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def extract_event_period(
    title: str | None,
    description: str | None,
    post_date: date | str | None,
) -> EventPeriod | None:
    """제목+본문에서 행사 기간을 찾는다. 못 찾거나 애매하면 None.

    Find the event date/period in a blog post → EventPeriod(start, end, basis) or None.
    post_date(게시일)는 연도 추정·지난 행사 판정의 기준이라 필수 — 없으면 None.
    """
    post = _as_date(post_date)
    if post is None:
        return None
    title = title or ""
    desc = description or ""
    if _NON_EVENT_TITLE.search(title) or _CANCELLED.search(desc):
        return None

    def pick(mn: _Mention, basis: str) -> EventPeriod:
        return EventPeriod(mn.start.isoformat(), mn.end.isoformat(), basis)

    # 1) 제목 속 날짜. 제목 날짜가 제외 항목(휴관·접수 …)이면 글 자체가 행사 안내가 아니다.
    title_mentions = _scan(title, post, slash_ok=True)
    if any(mn.label == "reject" for mn in title_mentions):
        return None
    if not _RECRUIT_TITLE.search(title):
        for mn in title_mentions:
            if _usable(mn, post):
                return pick(mn, "title")

    desc_mentions = _scan(desc, post, slash_ok=False)
    # 2) 본문 '행사 항목'(일시·기간·일정 …) 날짜 중 첫 번째로 유효한 것
    for mn in desc_mentions:
        if mn.label == "event" and _usable(mn, post):
            return pick(mn, "label")

    # 3) 항목명 없는 날짜 — 글에 모집·신청 신호도, 제외 항목도 없을 때만.
    if _RECRUIT_DOC.search(title) or _RECRUIT_DOC.search(desc):
        return None
    if any(mn.label == "reject" for mn in desc_mentions):
        return None
    for mn in desc_mentions:
        if mn.label == "none" and _usable(mn, post):
            return pick(mn, "text")
    return None
