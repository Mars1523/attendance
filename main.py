from contextlib import asynccontextmanager
import io
import csv
from typing import Annotated, Dict, List, Optional
import typing
import os

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import select
from fastapi.templating import Jinja2Templates
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    requires,
)
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from db import *
from auth import *

from datetime import datetime, date, time

load_dotenv()

SECRET_KEY = os.getenv("SECRET")
if SECRET_KEY is None:
    raise Exception("SECRET env var must be set. use .env file")


def flash(request: Request, message: typing.Any, category: typing.Any):
    if "_message" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append({"message": message, "category": category})


def get_flashed_messages(request: Request):
    return request.session.pop("_messages") if "_messages" in request.session else []


templates = Jinja2Templates(directory="templates")
templates.env.globals["get_flashed_messages"] = get_flashed_messages

middleware = [
    Middleware(SessionMiddleware, secret_key=SECRET_KEY),
    Middleware(AuthenticationMiddleware, backend=BasicAuthBackend()),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan, middleware=middleware)

@app.exception_handler(Exception)
async def http_exception_handler(request, exc):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"error": str(exc), "code": 500},
        status_code=500,
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"error": str(exc.detail), "code": exc.status_code},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"error": str(exc), "code": 400},
        status_code=400,
    )


class LoginFormData(BaseModel):
    userid: Optional[str] = None
    password: Optional[str] = None


@app.get("/login")
def login(request: Request):
    if request.session.get("auth") is not None:
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
def login(
    request: Request, data: Annotated[LoginFormData, Form()], session: SessionDep
):
    user, session = try_login(data.userid, data.password, session)
    if user is None:
        flash(request, "invalid user/pass", "danger")
        return RedirectResponse("/login", 303)

    request.session["auth"] = {"sessionid": session.sessionid}

    # Now that the user is authenticated,
    # we can send them to their original request destination
    next_url = request.query_params.get("next")
    if next_url:
        return RedirectResponse(next_url)
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request, session: SessionDep):
    auth = request.session.pop("auth", None)
    if auth is None:
        return RedirectResponse("/")

    if "sessionid" not in auth:
        return RedirectResponse("/")

    try_logout(auth["sessionid"], session)

    return RedirectResponse("/")


@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
@requires("authenticated", redirect="login")
def index(request: Request, session: SessionDep):
    users = session.exec(
        select(Attendance, User)
        .join(User, User.user == Attendance.user)
        .where(Attendance.endedAt.is_(None))
        .order_by(Attendance.startedAt.desc())
    ).all()
    return templates.TemplateResponse(
        request=request, name="index.html", context={"attendance": users}
    )


@app.get("/users", response_class=HTMLResponse)
@requires("admin", redirect="login")
def users(request: Request, session: SessionDep):
    users = session.exec(
        select(User, AuthUser)
        .outerjoin(AuthUser, User.user == AuthUser.user)
        .order_by(User.user)
    ).all()
    def merge(u):
        u,a=u
        return {
            "user": u.user,
            "name": u.name,
        } | (
            {
                "password": a.password,
                "scopes": a.scopes,
            }
            if a is not None
            else {}
        )
    users = list(map(merge, users))
    return templates.TemplateResponse(
        request=request, name="users.html", context={"users": users}
    )

def users_raw_text(session: SessionDep):
    users = session.exec(
        select(User, AuthUser)
        .outerjoin(AuthUser, User.user == AuthUser.user)
        .order_by(User.user)
    ).all()
    def merge(u):
        u,a=u
        return [
             u.user,
             u.name,
             *([a.scopes] if a else []),
        ]
    users = list(map(merge, users))

    out = io.StringIO()
    writer = csv.writer(out, delimiter="|")

    writer.writerow(["#userid", "name", "permissions"])
    for user in users:
        writer.writerow(user)

    return out.getvalue()

@app.get("/users/edit", response_class=HTMLResponse)
@app.post("/users/edit", response_class=HTMLResponse)
@requires("admin", redirect="login")
def users_edit(request: Request, session: SessionDep):
    users = users_raw_text(session)
    return templates.TemplateResponse(
        request=request, name="users_edit.html", context={"users": users}
    )

@app.post("/users/edit/update", response_class=HTMLResponse)
@requires("admin", redirect="login")
def users_edit_update(data: Annotated[str, Form()], request: Request, session: SessionDep):
    data = filter(lambda l:not l.startswith("#"),data.splitlines())
    users_reader = csv.reader(data,delimiter="|")
    users = []
    for user in users_reader:
        id = user[0]
        name = user[1]
        # scopes = user[2] if len(user) > 2 else ""
        users.append(User(user=id,name=name))
    
    for user in users:
        print(session.merge(user))
    session.commit()

    flash(request, f"Updated", "success")
    return RedirectResponse(url="/users/edit")

@app.get("/admin", response_class=HTMLResponse)
@requires("admin", redirect="login")
def admin(request: Request):
    return templates.TemplateResponse(
        request=request, name="admin.html"
    )


# @app.get("/users/active", response_class=HTMLResponse)
# def read_items(session: SessionDep):
#     users = session.exec(select(Attendance).where(Attendance.endedAt.is_(None))).all()
#     if len(users) == 0:
#         return "No one"
#     return "\n".join(map(lambda u: f"<li>{u.user}</li>", users))


@app.post("/users/submit")
@requires("authenticated", redirect="login")
def submit_userid(
    userid: Annotated[str, Form()], session: SessionDep, request: Request
):
    try:
        userid = int(userid)
    except ValueError:
        flash(request, "Invalid UserID", "danger")
        return RedirectResponse(url="/")

    if userid > 10_000:
        flash(request, f"NO!", "danger")
        return RedirectResponse(url="/")


    user = session.exec(select(User).where(User.user == userid)).first()
    if user is None:
        flash(request, f"Unknown UserID `{userid}`", "danger")
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
        flash(request, f"Goodbye {user.name}", "info")
        return RedirectResponse(url="/")
    else:
        session.add(Attendance(user=userid))
        session.commit()
        flash(request, f"Hello {user.name}", "success")
        return RedirectResponse(url="/")


@app.get("/rawdata")
@requires("admin", redirect="login")
def data(request: Request, session: SessionDep):
    data = session.exec(
        select(Attendance, User).join(User, Attendance.user == User.user, isouter=True)
    ).all()

    out = io.StringIO()

    writer = csv.writer(out)
    writer.writerow(["user", "start", "end"])
    for [att, user] in data:
        writer.writerow([user.name if user else att.user, att.startedAt, att.endedAt])

    export_media_type = "text/csv"
    export_headers = {"Content-Disposition": "attachment; filename=mars-attendance.csv"}
    return StreamingResponse(
        out.getvalue(), headers=export_headers, media_type=export_media_type
    )


@app.get("/data")
@requires("admin", redirect="login")
def data(request: Request, session: SessionDep):
    attendance = session.exec(
        text(
            r"""
select 
strftime("%G Week %W", startedAt) week,
strftime("%u", startedAt) day,
ifnull(name, attendance.user),
sum(cast((julianday(endedAt)-julianday(startedAt))*24 as real)) as hours
from attendance
left full outer join user on attendance.user = user.user
where endedAt is not null
group by week, day, attendance.user
order by week desc, user.user
"""
        )
    )

    weeks: Dict[str, List[any]] = {}

    days = [
        "None",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    for item in attendance:
        if not item[0] in weeks:
            weeks[item[0]] = []
        weeks[item[0]].append((days[int(item[1])], item[2], item[3]))

    return templates.TemplateResponse(
        request, "simple-log.html", context={"weeks": weeks}
    )


class ClockoutAllFormData(BaseModel):
    date: date
    time: time


@app.post("/api/clockout-all")
@requires("admin", redirect="login")
def clockout_all(
    request: Request, session: SessionDep, data: Annotated[ClockoutAllFormData, Form()]
):
    sessions = session.exec(
        select(Attendance)
        .where(Attendance.endedAt.is_(None))
        .order_by(Attendance.startedAt.desc())
    ).all()

    for ses in sessions:
        ses.endedAt = datetime.combine(data.date, data.time)
        session.add(ses)
    session.commit()
    flash(request, f"Clocked out {len(sessions)} users", "success")
    return RedirectResponse("/admin")
