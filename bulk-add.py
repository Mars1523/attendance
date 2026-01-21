from datetime import datetime

from sqlmodel import select
import db
from db import Attendance, User

# START = datetime(year=2026, month=1, day=10, hour=9, minute=30)
# END = datetime(year=2026, month=1, day=10, hour=5 + 12)
INFO = "bulk"

session = next(db.get_session())

active_users = session.exec(select(User).where(User.active == True)).all()

for user in active_users:
    entry = Attendance(user=user.user, startedAt=START, endedAt=END, info=INFO)
    print(entry)
    session.add(entry)

# session.commit()
print(f"Added {len(active_users)} entries")
