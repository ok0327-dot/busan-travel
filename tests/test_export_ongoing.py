"""events-ongoing.json 선택 규칙 회귀 테스트 — DB·네트워크 0.

Pins scripts/export_json.select_ongoing_events: events that started before the current month and are
still running must be exported to the small events-ongoing.json, because the frontend only loads
start-month shards from (today-1mo)..(today+6mo). 2026-10: 부산비엔날레 (8/29~11/1) was missing on
every October weekend.

    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from datetime import date

from scripts.export_json import select_ongoing_events


def _ev(i, start, end, category="festival"):
    return {"id": i, "category": category, "title": f"e{i}", "start": start, "end": end}


class SelectOngoingEventsTest(unittest.TestCase):
    TODAY = date(2026, 10, 9)

    def ids(self, events):
        return [e["id"] for e in select_ongoing_events(events, self.TODAY)]

    def test_long_running_from_older_month_is_kept(self):
        # 부산비엔날레: 8월 시작(프론트 로드 범위 9월~ 밖), 11/1 종료
        self.assertEqual(self.ids([_ev(1, "2026-08-29", "2026-11-01")]), [1])

    def test_previous_month_overlap_is_kept_for_month_rollover(self):
        # 지난달 시작분도 포함 — 월이 바뀐 직후 다음 export 전까지 빠지지 않게 (프론트가 id 로 중복 제거)
        self.assertEqual(self.ids([_ev(2, "2026-09-22", "2026-11-22")]), [2])

    def test_current_month_start_is_left_to_shard(self):
        self.assertEqual(self.ids([_ev(3, "2026-10-01", "2026-12-31")]), [])

    def test_ended_or_open_ended_is_dropped(self):
        events = [
            _ev(4, "2026-08-01", "2026-10-08"),   # 어제 종료
            _ev(5, "2026-08-01", None),           # 종료일 없음 = 단일일 행사 → 이미 지남
            _ev(6, "2026-08-01", "2026-10-09"),   # 오늘 종료 → 포함
        ]
        self.assertEqual(self.ids(events), [6])

    def test_only_event_categories(self):
        events = [
            _ev(7, "2026-08-01", "2026-12-31", "blog_post"),
            _ev(8, "2026-08-01", "2026-12-31", "exhibition"),
            _ev(9, "2026-08-01", "2026-12-31", "performance"),
        ]
        self.assertEqual(self.ids(events), [8, 9])

    def test_sorted_by_start_then_id(self):
        events = [_ev(12, "2026-08-02", "2026-12-31"), _ev(11, "2026-08-02", "2026-12-31"),
                  _ev(10, "2023-01-01", "2099-12-31")]
        self.assertEqual(self.ids(events), [10, 11, 12])


if __name__ == "__main__":
    unittest.main()
