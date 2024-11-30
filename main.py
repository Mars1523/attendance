from contextlib import asynccontextmanager
import io
import csv
from typing import Annotated, Optional
import typing
import os

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel
from sqlmodel import Field, Session, select
from fastapi.templating import Jinja2Templates
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    requires,
)
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from db import *
from auth import *

from datetime import datetime

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
        select(Attendance)
        .where(Attendance.endedAt.is_(None))
        .order_by(Attendance.startedAt.desc())
    ).all()
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
@requires("authenticated", redirect="login")
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
@requires("admin")
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
