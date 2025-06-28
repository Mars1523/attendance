from collections import defaultdict
from contextlib import asynccontextmanager
import io
import csv
import itertools
from typing import Annotated, Dict, List, Optional
import typing
import os

from fastapi import Body, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel
import requests
from sqlalchemy import func, text
from sqlmodel import or_, select
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

from datetime import datetime, date, time, timedelta

from timeline import Timeline

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
        return RedirectResponse(next_url, 303)
    return RedirectResponse("/", 303)


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


@app.get("/admin/users", response_class=HTMLResponse)
@requires("admin", redirect="login")
def users(request: Request, session: SessionDep):
    users = session.exec(
        select(User, AuthUser)
        .outerjoin(AuthUser, User.user == AuthUser.user, full=True)
        .order_by(User.user)
    ).all()
    def merge(u):
        u,a=u
        user_info = (
            {
                "user": a.user,
                "name": "<No User Entry for AuthUser>",
            }
            if u is None
            else {
                "user": u.user,
                "name": u.name,
            }
        )
        auth_info = (
            {}
            if a is None
            else {
                "password": a.password,
                "scopes": a.scopes,
            }
        )

        return user_info | auth_info
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


@app.get("/admin/users/edit", response_class=HTMLResponse)
@requires("admin", redirect="login")
def users_edit(request: Request, session: SessionDep):
    users = users_raw_text(session)
    return templates.TemplateResponse(
        request=request, name="users_edit.html", context={"users": users}
    )


@app.post("/admin/users/edit/update", response_class=HTMLResponse)
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
    return RedirectResponse("/admin/users/edit", 303)

@app.get("/admin", response_class=HTMLResponse)
@requires("admin", redirect="login")
def admin(request: Request):
    return templates.TemplateResponse(
        request=request, name="admin.html"
    )

@app.get("/api/whois/{userid_s}", response_class=HTMLResponse)
def read_items(session: SessionDep, userid_s: str):
    try:
        userid = int(userid_s)
    except:
        return "Invalid UserId"
    user = session.exec(select(User).where(User.user == userid)).first()
    if user:
        return user.name
    return "Unknown"

# @app.get("/users/active", response_class=HTMLResponse)
# def read_items(session: SessionDep):
#     users = session.exec(select(Attendance).where(Attendance.endedAt.is_(None))).all()
#     if len(users) == 0:
#         return "No one"
#     return "\n".join(map(lambda u: f"<li>{u.user}</li>", users))


@app.get("/api/users")
@requires("authenticated")
def all_users(request: Request, session: SessionDep):
    users = session.exec(select(User)).all()
    return users


@app.post("/users/submit")
@requires("authenticated", redirect="login")
def submit_userid(
    userid: Annotated[str, Form()], session: SessionDep, request: Request
):
    userid = userid.strip()

    if userid == "+711":
        logout(request, session)
        return RedirectResponse("/", 303)

    try:
        userid = int(userid)
    except ValueError:
        flash(request, "Invalid UserID", "danger")
        return RedirectResponse("/", 303)

    if userid > 10_000:
        flash(request, f"NO!", "danger")
        return RedirectResponse("/", 303)

    user = session.exec(select(User).where(User.user == userid)).first()
    if user is None:
        flash(request, f"Unknown UserID `{userid}`", "danger")
        return RedirectResponse("/", 303)

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
        return RedirectResponse("/", 303)
    else:
        session.add(Attendance(user=userid))
        session.commit()
        flash(request, f"Hello {user.name}", "success")
        return RedirectResponse("/", 303)


@app.get("/admin/rawdata")
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


class EntryUpdate(BaseModel):
    id: int
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None


@app.post("/api/entries/update")
@requires("admin")
def update_entires(request: Request, update: EntryUpdate, session: SessionDep):
    # if update.startedAt is None:
    if update.endedAt is not None:
        endedAt = datetime.fromisoformat(update.endedAt).replace(tzinfo=None)
    else:
        endedAt = None

    startedAt = datetime.fromisoformat(update.startedAt).replace(tzinfo=None)

    entry = session.exec(select(Attendance).where(Attendance.id == update.id)).first()
    if entry is None:
        print(f"no entry found for id {update.id}")
        return
    
    entry.startedAt = startedAt
    entry.endedAt = endedAt

    session.add(entry)
    session.commit()

    return "ok"

class EntryCreate(BaseModel):
    userid: int
    startedAt: datetime
    endedAt: Optional[datetime] = None

@app.post("/api/entries/create")
@requires("admin")
def update_entires(request: Request, update: Annotated[EntryCreate, Form()], session: SessionDep):
    user = session.exec(select(User).where(User.user == update.userid)).first()

    entry = Attendance(user=update.userid, startedAt=update.startedAt,endedAt=update.endedAt)
    session.add(entry)
    session.commit()

    flash(request, f"Created time record for `{user.displayName()}`", "success")
    return RedirectResponse(request.headers.get("referer"), 303)


@app.post("/api/entries/delete")
@requires("admin")
def update_entires(request: Request, id: Annotated[int, Body(embed=True)], session: SessionDep):
    entry = session.exec(select(Attendance).where(Attendance.id == id)).first()
    print(entry)
    if entry is None:
        print(f"no entry found for id {id}")
        return
    
    session.delete(entry)
    session.commit()
    
    return "ok"


@app.get("/admin/entries")
@requires("admin", redirect="login")
def data(request: Request, session: SessionDep):
    attendance = session.exec(
        select(Attendance, User)
        .join(User, User.user == Attendance.user)
        .order_by(Attendance.startedAt.desc())
    ).all()

    datetimeToHtml = lambda dt: dt.strftime("%Y-%m-%d %H:%M")

    table = ""

    dayFormat = lambda dt: dt.strftime("%A, %Y-%-m-%d")
    groups_by_day = itertools.groupby(attendance, lambda v: dayFormat(v[0].startedAt))

    for day, day_items in groups_by_day:
        table += '<th colspan="6">' + day + "</th>"
        for atnd, user in day_items:
            table += '<tr data-id="' + str(atnd.id) + '">'
            table += "<td>"
            table += user.displayName()
            table += "</td>"
            table += "<td>"
            if atnd.startedAt is not None:
                table += (
                    '<input name="startedAt" type="datetime-local" value="'
                    + datetimeToHtml(atnd.startedAt)
                    + '">'
                )
            else:
                table += "None"
            table += "</td>"
            table += "<td>"
            if atnd.endedAt is not None:
                table += (
                    '<input name="endedAt" type="datetime-local" value="'
                    + datetimeToHtml(atnd.endedAt)
                    + '">'
                )
            else:
                table += "None"
            table += f"<td>{atnd.info or ""}</td>"
            table += "</td>"
            table += "<td>"
            table += '<button type="button" class="btn btn-outline-primary" onclick="updateEntry(this)">Update</button>'
            table += "</td>"
            table += "<td>"
            table += '<button type="button" class="btn btn-outline-danger" onclick="deleteEntry(this)">Delete</button>'
            table += "</td>"
            table += "</tr>"

    return templates.TemplateResponse(
        request, "entries.html", context={"tableBody": table}
    )


def round_down_to_week_start(dt):
    # Get the start of the week (Monday)
    start_of_week = dt - timedelta(days=dt.weekday())
    # Set time to midnight
    return start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)


def make_week_time_table(session: SessionDep, fmt: str) -> str:
    csv = fmt == "csv"
    attendance = session.exec(
        select(Attendance, User)
        .join(User, User.user == Attendance.user)
        .where(Attendance.endedAt.isnot(None))
        .order_by(Attendance.startedAt.desc())
    ).all()
    users = session.exec(
        select(User)
        .join(AuthUser, AuthUser.user == User.user, isouter=True, full=True)
        .where(AuthUser.user == None)
        .order_by(User.user)
    ).all()

    table = ""

    def timeFormat(td: timedelta):
        if td.total_seconds() == 0:
            return ""
        else:
            return str(round(td.total_seconds() / 60 / 60, 1))

    weekFormat = lambda dt: dt.strftime("%Y-%-m-%d")
    weeks = itertools.groupby(
        attendance, lambda v: round_down_to_week_start(v[0].startedAt)
    )

    user_timelines = defaultdict(lambda: Timeline())
    for atnd, user in attendance:
        user_timelines[user.displayName()].add(
            atnd.startedAt, atnd.endedAt or datetime.now()
        )

    if csv:
        table += "week"
    else:
        table += "<tr>"
        table += '<th scope="col">Week</th>'
    for user in users:
        if csv:
            table += f',"{user.name.replace('"', '""')}"'
        else:
            table += '<th scope="col">' + user.name + "</th>"
    table += "\n" if csv else "</tr>\n"
    for week, week_items in weeks:
        user_attendance = {}
        for user, tl in sorted(user_timelines.items(), key=lambda v: v[0]):
            week_total = sum(
                map(lambda s: s.end - s.start, tl.slice_week_cc(week)),
                start=timedelta(),
            )

            user_attendance[user] = week_total

        if csv:
            table += weekFormat(week)
        else:
            table += "<tr>"
            # week column
            table += '<th scope="row">' + weekFormat(week) + "</th>"
        for user in users:
            table += "," if csv else "<td>"
            if user.displayName() not in user_attendance:
                table += "" if csv else "</td>"
                continue
            table += timeFormat(user_attendance[user.displayName()])
            table += "" if csv else "</td>"
        table += "\n" if csv else "</tr>"
    return table


@app.get("/admin/time/weeks")
@requires("admin", redirect="login")
def time_table_week(request: Request, session: SessionDep):
    table = make_week_time_table(session, "html")

    return templates.TemplateResponse(
        request,
        "time_table.html",
        context={
            "tableBody": table,
            "bodyHeader": '<a type="button" class="btn btn-outline-primary" href="/admin/time/weeks/csv">Download as CSV</a>',
        },
    )


@app.get("/admin/time/weeks/csv")
@requires("admin", redirect="login")
def time_table_week_csv(request: Request, session: SessionDep):
    table = make_week_time_table(session, "csv")

    export_media_type = "text/csv"
    export_headers = {
        "Content-Disposition": "attachment; filename=mars-attendance-weekly.csv"
    }
    return StreamingResponse(
        table, headers=export_headers, media_type=export_media_type
    )


@app.get("/admin/time")
@requires("admin", redirect="login")
def time_table(request: Request, session: SessionDep):
    attendance = session.exec(
        select(Attendance, User)
        .join(User, User.user == Attendance.user)
        # .where(Attendance.endedAt.isnot(None))
        .order_by(Attendance.startedAt.desc())
    ).all()

    table = ""

    def timeFormat(td: timedelta):
        if td.total_seconds() == 0:
            return ""
        else:
            return str(round(td.total_seconds() / 60 / 60, 1))

    dayFormat = lambda dt: dt.strftime("%a %m/%d")
    weekFormat = lambda dt: dt.strftime("%Y-%-m-%d")
    weeks = itertools.groupby(
        attendance, lambda v: round_down_to_week_start(v[0].startedAt)
    )

    user_timelines = defaultdict(lambda: Timeline())
    for atnd, user in attendance:
        user_timelines[user.displayName()].add(atnd.startedAt, atnd.endedAt or datetime.now())
    
    year = datetime(year=datetime.now().year, month=1, day=1)
    end_of_year = datetime(year=datetime.now().year + 1, month=1, day=1) - timedelta(
        microseconds=1
    )

    for week, week_items in weeks:
        end_of_week = week + timedelta(days=7) - timedelta(microseconds=1)
        user_attendance = {}
        for user, tl in sorted(user_timelines.items(), key=lambda v:v[0]):
            days = []
            for day in range(7):
                slices = tl.slice_day_cc(week + timedelta(days=day))
                days.append(
                    sum(map(lambda s: s.end - s.start, slices), start=timedelta())
                )

            week_total = sum(
                map(lambda s: s.end - s.start, tl.slice_week_cc(week)),
                start=timedelta(),
            )
            year_total = sum(
                map(lambda s: s.end - s.start, tl.slice_between_cc(year, end_of_week)),
                start=timedelta(),
            )

            user_attendance[user] = [*days, week_total, year_total]

        table += "<tr>"
        table += '<th scope="col">' + weekFormat(week) + "</th>"
        for dayi in range(0, 7):
            table += (
                '<th scope="col">' + dayFormat(week + timedelta(days=dayi)) + "</th>"
            )
        table += '<th scope="col">Week Total</th>'
        table += '<th scope="col">Year Total</th>'
        table += "</tr>"
        for user, atnd in user_attendance.items():
            table += "<tr>"
            table += '<th scope="row">'
            table += str(user)
            table += "</th>"
            for a in atnd:
                table += "<td>"
                table += timeFormat(a)
                table += "</td>"
            table += "</tr>"

    return templates.TemplateResponse(
        request, "time_table.html", context={"tableBody": table}
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
    return RedirectResponse("/admin", 303)


@app.post("/api/fans/on")
@requires("authenticated")
def fans_on(request: Request):
    print("fans on")
    # programming
    requests.post("http://shellyplugus-a0dd6c4a6344.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":True}})
    requests.post("http://shellyplugus-a0dd6c27dc58.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":True}})

    # construction
    requests.post("http://shellyplugus-3c8a1fece8f8.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":True}})
    requests.post("http://shellyplugus-d8132ad47a40.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":True}})
    return RedirectResponse(request.headers.get("referer"), 303)

@app.post("/api/fans/off")
@requires("authenticated")
def fans_on(request: Request):
    print("fans off")
    # programming
    requests.post("http://shellyplugus-a0dd6c4a6344.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":False}})
    requests.post("http://shellyplugus-a0dd6c27dc58.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":False}})

    # construction
    requests.post("http://shellyplugus-3c8a1fece8f8.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":False}})
    requests.post("http://shellyplugus-d8132ad47a40.local/rpc", json={"id":0,"method":"Switch.Set","params":{"id":0,"on":False}})
    return RedirectResponse(request.headers.get("referer"), 303)