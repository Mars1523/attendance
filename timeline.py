from datetime import datetime, timedelta
from typing import List, NamedTuple


class DateSpan(NamedTuple):
    start: datetime
    end: datetime


class Timeline:
    dates: List[DateSpan]

    def __init__(self):
        self.dates = []

    def add(self, start: datetime, end: datetime):
        self.dates.append(DateSpan(start, end))
        self.dates.sort()

    def overlapping_with(self, left: datetime, right: datetime) -> List[DateSpan]:
        out = []
        for start, end in self.dates:
            # begins and ends before our window
            if start < left and end < left:
                continue
            # begins and ends after our window
            if start > right and end > right:
                continue
            # some part must be in our window
            out.append(DateSpan(start, end))
        return out

    def slice_between_cc(self, left: datetime, right: datetime) -> List[DateSpan]:
        return list(
            map(
                lambda s: DateSpan(max(left, s.start), min(s.end, right)),
                self.overlapping_with(left, right),
            )
        )

    def slice_between_co(self, left: datetime, right: datetime) -> List[DateSpan]:
        return list(
            map(
                lambda s: DateSpan(max(left, s.start), s.end),
                self.overlapping_with(left, right),
            )
        )

    def _round_to_day(self, dt: datetime) -> datetime:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    def _round_to_week(self, dt: datetime) -> datetime:
        return (dt - timedelta(days=dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def slice_day_cc(self, dt: datetime) -> List[DateSpan]:
        day = self._round_to_day(dt)

        return self.slice_between_cc(
            day, day + timedelta(days=1) - timedelta(microseconds=1)
        )

    def slice_week_cc(self, dt: datetime) -> List[DateSpan]:
        day = self._round_to_week(dt)

        return self.slice_between_cc(
            day, day + timedelta(days=7) - timedelta(microseconds=1)
        )

    def slice_day_co(self, dt: datetime) -> List[DateSpan]:
        """
        Slice timeline closed-open
        """
        day = self._round_to_day(dt)

        return self.slice_between_co(
            day, day + timedelta(days=1) - timedelta(microseconds=1)
        )

    def slice_week_co(self, dt: datetime) -> List[DateSpan]:
        day = self._round_to_week(dt)

        return self.slice_between_co(
            day, day + timedelta(days=7) - timedelta(microseconds=1)
        )
