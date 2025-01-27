from collections import defaultdict
from datetime import datetime, timedelta

from sqlmodel import select
import db
from db import Attendance, User
from timeline import Timeline

# BEGIN_AT = datetime(year=2025, month=1, day=25, hour=5 + 12)
# END_AT = datetime(year=2025, month=1, day=25, hour=8 + 12)

session = next(db.get_session())

attendance = session.exec(
    select(Attendance, User)
    .join(User, User.user == Attendance.user)
    .where(Attendance.endedAt.isnot(None))
    .order_by(Attendance.startedAt.desc())
).all()

user_timelines = defaultdict(lambda: Timeline())
for atnd, user in attendance:
    user_timelines[user.user].add(
        atnd.startedAt, atnd.endedAt or datetime.now()
    )

for u, tl in user_timelines.items():
    time_sum = sum(
        map(
            lambda s: s.end - s.start,
            tl.slice_between_co(
                BEGIN_AT,
                END_AT,
            ),
        ),
        start=timedelta(),
    )
    if time_sum < timedelta(minutes=1):
        continue
    begin = min(
        map(
            lambda tl: tl.start,
            tl.slice_between_co(
                BEGIN_AT,
                END_AT,
            ),
        )
    )
    end = max(
        map(
            lambda tl: tl.end,
            tl.slice_between_co(
                BEGIN_AT,
                END_AT,
            ),
        )
    )

    print(Attendance(user=u, startedAt = begin, endedAt=end,info="doubletime"))
    session.add(Attendance(user=u, startedAt = begin, endedAt=end,info="doubletime"))
session.commit()
