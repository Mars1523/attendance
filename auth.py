
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
    async def authenticate(self, conn):
        db = next(get_session())

        auth = conn.session.get("auth")
        if auth is None:
            print("no auth in session, skipping")
            return

        if "sessionid" not in auth:
            print("no sessionid in session, skipping")
            conn.session.clear()
            return

        auth_user = db.exec(
            select(AuthUser)
            .join(AuthSession)
            .where(AuthSession.sessionid == auth["sessionid"])
        ).first()

        if auth_user is None:
            return

        return AuthCredentials(auth_user.scopes.split(",")), SimpleUser(auth_user.user)


def hash_password(password: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), b"salt", 100000)
    return binascii.hexlify(dk).decode()


def try_login(userid: str, password: str, session: SessionDep) -> Optional[Tuple[AuthUser,AuthSession]]:
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

def try_logout(sessionid: str, session:SessionDep) -> bool:
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.sessionid == sessionid)
    ).first()

    if auth_session is None:
        return False

    session.delete(auth_session)
    session.commit()
    return True