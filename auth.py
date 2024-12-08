import binascii
import hashlib
from typing import Optional, Tuple
from uuid import uuid4
from sqlmodel import select
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    SimpleUser,
)

from db import *

class BasicAuthBackend(AuthenticationBackend):
    def _simple_auth(self, db: SessionDep, auth):
        user = auth["user"]
        password_hash = hash_password(auth["pass"])

        auth_user = db.exec(
            select(AuthUser)
            .where(AuthUser.user == user)
            .where(AuthUser.password == password_hash)
        ).first()

        if auth_user is None:
            return
        return AuthCredentials(auth_user.scopes.split(",")), SimpleUser(auth_user.user)
        

    async def authenticate(self, conn):
        with Session(engine) as db:
            auth = conn.session.get("auth")
            if auth is None:
                headers = conn.headers
                if "user" in headers and "pass" in headers:
                    return self._simple_auth(db, headers)
                print("no auth in session, skipping")
                return

            if "sessionid" not in auth:
                print("no sessionid in session, skipping")
                conn.session.clear()
                return

            auth_user = db.exec(
                select(AuthUser)
                .join(AuthSession, AuthUser.user == AuthSession.user)
                .where(AuthSession.sessionid == auth["sessionid"])
            ).first()

            if auth_user is None:
                print("user has sessionid but it's not valid")
                conn.session.clear()
                return

            return AuthCredentials(auth_user.scopes.split(",")), SimpleUser(auth_user.user)


def hash_password(password: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), b"salt", 100000)
    return binascii.hexlify(dk).decode()


def try_login(
    userid: str, password: str, session: SessionDep
) -> Optional[Tuple[AuthUser, AuthSession]]:
    password_hash = hash_password(password)
    db_user = session.exec(
        select(AuthUser)
        .where(AuthUser.user == userid)
        .where(AuthUser.password == password_hash)
    ).first()
    if db_user is None:
        return None, None

    old_sessions = session.exec(
        select(AuthSession).where(AuthSession.user == db_user.user)
    ).all()
    for sess in old_sessions:
        session.delete(sess)

    sessionid = uuid4().hex
    new_session = AuthSession(sessionid=sessionid, user=db_user.user)

    session.add(new_session)
    session.commit()
    return db_user, new_session


def try_logout(sessionid: str, session: SessionDep) -> bool:
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.sessionid == sessionid)
    ).first()

    if auth_session is None:
        return False

    session.delete(auth_session)
    session.commit()
    return True
