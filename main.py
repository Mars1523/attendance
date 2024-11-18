from contextlib import asynccontextmanager
import io
import csv
from typing import Annotated
import typing

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlmodel import Field, Session, SQLModel, create_engine, select
from fastapi.templating import Jinja2Templates
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from datetime import datetime


class Attendance(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user: int = Field(index=True)
    startedAt: datetime = Field(default_factory=datetime.now)
    endedAt: datetime | None = Field(index=True)


sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def flash(request: Request, message: typing.Any, category: typing.Any):
    if "_message" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append({"message": message, "category": category})


def get_flashed_messages(request: Request):
    return request.session.pop("_messages") if "_messages" in request.session else []


templates = Jinja2Templates(directory="templates")
templates.env.globals["get_flashed_messages"] = get_flashed_messages

middleware = [Middleware(SessionMiddleware, secret_key="marsbot1523")]
SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan, middleware=middleware)


@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
def index(request: Request, session: SessionDep):
    users = session.exec(select(Attendance).where(Attendance.endedAt.is_(None))).all()
    return templates.TemplateResponse(
        request=request, name="index.html", context={"users": users}
    )


# @app.get("/users/active", response_class=HTMLResponse)
# def read_items(session: SessionDep):
#     users = session.exec(select(Attendance).where(Attendance.endedAt.is_(None))).all()
#     if len(users) == 0:
#         return "No one"
#     return "\n".join(map(lambda u: f"<li>{u.user}</li>", users))


@app.post("/users/submit")
def submit_userid(
    userid: Annotated[str, Form()], session: SessionDep, request: Request
):
    try:
        userid = int(userid)
    except ValueError:
        flash(request, "Invalid UserID", "danger")
        return RedirectResponse(url="/")

    open_session = session.exec(
        select(Attendance)
        .where(Attendance.user == userid)
        .where(Attendance.endedAt.is_(None))
    ).first()

    if open_session:
        open_session.endedAt = datetime.now()
        session.add(open_session)
        session.commit()
        flash(request, f"Goodbye {userid}", "info")
        return RedirectResponse(url="/")
    else:
        session.add(Attendance(user=userid))
        session.commit()
        flash(request, f"Hello {userid}", "success")
        return RedirectResponse(url="/")


@app.get("/rawdata")
def data(session: SessionDep):
    data = session.exec(select(Attendance)).all()

    out = io.StringIO()

    writer = csv.writer(out)
    writer.writerow(["user", "start", "end"])
    for v in data:
        writer.writerow([v.user, v.startedAt, v.endedAt])

    export_media_type = "text/csv"
    export_headers = {"Content-Disposition": "attachment; filename=mars-attendance.csv"}
    return StreamingResponse(
        out.getvalue(), headers=export_headers, media_type=export_media_type
    )
