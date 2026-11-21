# 주말 재생 테스트 (weekend replay tests)

실제 금요일 데이터 스냅샷을 **지금의** `frontend/public/main.js` 오늘 탭(`renderTodayHighlights`)에 그대로 흘려
"목·금 저녁에 이번 주말 계획" 화면이 망가지지 않았는지 보는 회귀 테스트(regression test)다.
Node 22 내장 기능만 쓴다(`node:test`, `node:assert`, `node:vm`) — npm 패키지 없음.

## 실행 / Run

```bash
TZ=Asia/Seoul node --test tests/js/            # 전부 (tests/js/index.js 가 *.test.mjs 를 불러온다)
TZ=Asia/Seoul node --test tests/js/*.test.mjs  # 같은 결과
MAIN_JS=/tmp/old-main.js TZ=Asia/Seoul node --test tests/js/   # 다른 main.js 재생 (예: 수정 전 버전)
REPLAY_INCLUDE_ONGOING=0 TZ=Asia/Seoul node --test tests/js/   # 진행 중 행사 파일 없이 (PR #79 이전 init)
```

- 시간대(TZ)는 `replay_lib.mjs` 가 첫 줄에서 `Asia/Seoul` 로 맞추고 확인하지만, 명령에도 붙이는 것을 권장한다.
- 수정 전 코드에서 실패하는지 보기: `git show b4aa9b8:frontend/public/main.js > /tmp/old-main.js` 후 위 `MAIN_JS=` 명령
  (PR #77/#78 이전 — Top 5·칩·예약 테스트가 실패해야 정상).
- 파이썬 테스트는 그대로: `.venv/bin/python -m unittest discover -s tests -t .`

## 무엇을 검사하나 / What is checked

정확한 순서 스냅샷이 아니라 **불변 조건(invariant)** 만 본다 — 랭킹·예약 상자 정렬을 고쳐도 통과해야 한다.

| 묶음 | 조건 |
|---|---|
| ⭐ Top 5 | 매주(재생 시각마다) Top 5 가 전부 대상 주말(토·일)에 열리는 행사 |
| ⭐ P@5 | 가족 라벨 적중 수가 주별 기준선(baseline) 이상, 합계 `min_total_p_at_5`(15/35) 이상 |
| 📋 칩 | 모든 `.chip`(그 외 행사·사전예약)과 Top 5 카드를 클릭하면 **같은 제목**의 상세가 열림 |
| 🚨 예약 | 실제 오늘 기준 D-0~D-7 예약 행사가 긴급 목록에서 빠지지 않음 · 긴급 상자 항목은 모두 `.urg-item` 버튼이고 자기 행사를 엶 · 11-19(목) 장수탕 선녀님 `D-1 마감` · 11-06 다시,봄 `오늘 마감` · 11-06 부산불꽃축제는 `오늘` 아님 |
| 🔁 중복 | Top 5 + 그 외 목록에 출처만 다른 같은 행사(`_sameEventLikely`)가 두 번 나오지 않음 · 11-21(토) 지스타 1건만 · 10-09 BIFF 1건만 (아래 "중복 행사") |

재생 시각은 fixture 의 `replay_hour_kst` — 목·금 fixture 는 20시, 11-21(토) fixture 는 오전 10시.
11-21 은 라벨이 없어 P@5 만 건너뛴다(기준선 합계 15/35 는 7주 그대로).

## 구성 / Layout

- `replay_lib.mjs` — main.js 에서 최상위 함수·상수를 **이름으로** 뽑아(문자열·템플릿·정규식을 건너뛰는 괄호 짝 맞추기)
  `node:vm` 에 넣고, 시계를 고정한 `Date` 와 작은 가짜 DOM 으로 진짜 `renderTodayHighlights` 를 실행한다.
  렌더된 버튼을 실제로 클릭해 `showDetail` 로 넘어가는 행사를 받아 온다. 필요한 함수(`REQUIRED_FUNCTIONS`)나
  캡처 지점(`$list.innerHTML =`)이 없어지면 이름을 밝히고 바로 실패한다 → 리팩터링 때 여기를 같이 고칠 것.
- `weekend_replay.test.mjs` — 위 표의 테스트.
- `build_replay_fixtures.mjs` — git 기록에서 fixture 생성. `tests/fixtures/weekend_replay/<날짜>.json`
- `tests/fixtures/weekend_replay/labels.json` — 주별 가족 라벨(제목 부분 문자열)과 P@5 기준선.
  **한 사람이 붙인 라벨(2026-11) — 주인이 다시 라벨링할 예정.** 라벨을 고치면 기준선도 다시 재서 갱신한다
  (`node --test --test-reporter=spec tests/js/` 출력의 `P@5=` 줄).

## 행사 풀 / Event pool

`buildPool()` 은 현재 main.js `init()`(PR #79 이후)과 똑같이 만든다:

1. `manifest.events_by_month` 의 n>0 달 중 오늘 −1~+6개월 shard 의 행사를 이어 붙이고,
2. 그 **뒤에** 진행 중 행사 파일(`events-ongoing.json`)의 행사 중 id 가 shard 에 없는 것을 붙인 뒤,
3. festival/exhibition/performance 만 남긴다.

진행 중 행사 파일은 fixture 에 `ongoing_file`(그 커밋의 실제 파일, PR #79 이후 커밋)이 있으면 그대로 쓰고
(앱처럼 manifest `counts.events_ongoing` > 0 일 때만), 없으면(PR #79 이전 커밋) fixture 의 모든 행사에
exporter 규칙(`select_ongoing_events`: 이번 달 1일 전 시작 + 오늘 이후 종료, `(start, id)` 정렬)을 재생일 기준으로
적용해 흉내 낸다. 이 흉내가 11-21 실제 파일과 id·순서까지 같은지 self-check 테스트가 확인한다.

- 진행 중 행사를 빼고(PR #79 이전 init) 돌리기: `REPLAY_INCLUDE_ONGOING=0 TZ=Asia/Seoul node --test tests/js/`
  (또는 `buildPool(fx, now, { includeOngoing: false })`).
- Default pool mirrors init: shard events first, then `events-ongoing.json` events whose id is not in the shards.

## 중복 행사 / Cross-source duplicates

🔁 묶음은 Top 5 + 그 외(`hero` + `tail`) 안의 어떤 두 항목도 main.js `_sameEventLikely`(긴급 상자와 같은 기준:
시작·종료일 동일 + 제목 핵심어 포함, 또는 같은 카테고리·다른 출처·장소명 포함)로 같은 행사가 아님을 확인한다.
11-21(토): Top 5 에 해운대 아마추어 인형극축제·장수탕 선녀님, "G-STAR 2026" 은 따로 안 나옴.
10-09: "2026 BIFF" 와 "부산국제영화제" 가 함께 나오지 않음.
수정 전 main.js(`git show 17c4524:frontend/public/main.js`)로 돌리면 이 묶음 11개가 실패해야 정상이다.

## 새 금요일 추가 / Adding a new Friday

1. 그 금요일 아침 자동 수집 커밋을 찾는다:
   `git log origin/main --format='%h %ad %s' --date=iso -- frontend/public/data/manifest.json | grep 2026-11-27`
2. fixture 생성: `node tests/js/build_replay_fixtures.mjs 2026-11-27=<sha>`
   (목요일 데이터를 목·금 두 시각으로 재생하려면 `2026-11-26=<sha>@2026-11-26,2026-11-27`,
   재생 시각을 바꾸려면 `--hour=10` — 예: `node tests/js/build_replay_fixtures.mjs --hour=10 2026-11-21=17c4524`)
   — 이후 인자 없이 돌리면 기존 fixture 전부를 각자 기록된 커밋·시각에서 다시 만든다(결과 동일).
   커밋에 `events-ongoing.json` 이 있으면 fixture 의 `ongoing_file` 로 함께 담긴다.
3. (선택) `labels.json` 의 `labels` 에 그 주 라벨을 넣고, 테스트를 돌려 나온 P@5 를 `baseline_p_at_5` 에 적는다.
   라벨이 없는 주는 P@5 만 건너뛰고 나머지 불변 조건은 그대로 검사한다.
4. 크기: 끝난 행사는 빼고 오늘 탭이 읽는 필드만 남겨 주당 약 50KB (전체 1MB 미만 유지).
