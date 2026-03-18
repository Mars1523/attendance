# Simple Attendance

Run with

    uv run fastapi run main.py




To insert attendance entries for all active users, run the following SQL statement:

    INSERT INTO attendance (user, "startedAt", "endedAt", info)
    SELECT user, 
           datetime('2026-01-11', 'start of day', '+X hours'),
           datetime('2026-01-11', 'start of day', '+(X+Y) hours'),
           'bulk-add'
    FROM user
    WHERE active = 1;
