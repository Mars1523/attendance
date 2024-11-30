
from datetime import datetime
from typing import Annotated
from fastapi import Depends
from sqlalchemy import create_engine
from sqlmodel import Field, SQLModel, Session


class User(SQLModel, table=True):
    user: int = Field(default=None, primary_key=True)
    name: str

class AuthUser(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user: int = Field(index=True)
    password: str
    scopes: str


class AuthSession(SQLModel, table=True):
    sessionid: str = Field(index=True, primary_key=True)
    user: int


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

SessionDep = Annotated[Session, Depends(get_session)]
