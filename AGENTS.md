# AGENTS.md

## Commands
- Dev server: `uv run fastapi dev main.py`
- Run server: `uv run fastapi run main.py`
- Hash password (CLI): `uv run python cli.py <password>`
- No test suite configured

## Architecture
- **FastAPI** web app with **SQLModel** (SQLite: `database.db`)
- `main.py` - Routes, middleware, scheduler (auto-clockout at midnight)
- `db.py` - Models: `User`, `AuthUser`, `AuthSession`, `Attendance`
- `auth.py` - Session-based auth with PBKDF2 password hashing
- `timeline.py` - Time span utilities for attendance calculations
- `templates/` - Jinja2 HTML templates (Bootstrap-based)
- Environment: `SECRET`, `HA_TOKEN`, `HA_URL` via `.env`

## Code Style
- Python 3.14+, use `uv` as package manager
- Type hints with `Annotated[]` for FastAPI dependencies
- SQLModel for DB models (hybrid SQLAlchemy + Pydantic)
- Pydantic `BaseModel` for form/request data validation
- Use `SessionDep` type alias for database session injection
- Starlette `@requires()` decorator for route auth (`"authenticated"`, `"admin"`)
- Star imports from local modules (`from db import *`)
