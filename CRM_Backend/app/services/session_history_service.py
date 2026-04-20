from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import extract
from sqlalchemy.orm import Session

from app.models.session_history import UserSessionHistory
from app.models.user import User


def register_session_login(
    db: Session,
    *,
    user: User,
    auth_source: str = "backend",
) -> UserSessionHistory:
    row = UserSessionHistory(
        user_id=int(user.id),
        email=str(user.email or ""),
        username=str(user.username or ""),
        role=str(user.role or ""),
        auth_source=str(auth_source or "backend"),
        login_at=datetime.now(),
        logout_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def close_session(
    db: Session,
    *,
    user: User,
    session_history_id: int | None = None,
) -> bool:
    q = db.query(UserSessionHistory).filter(UserSessionHistory.user_id == int(user.id), UserSessionHistory.logout_at.is_(None))

    if session_history_id:
        row = q.filter(UserSessionHistory.id == int(session_history_id)).first()
    else:
        row = q.order_by(UserSessionHistory.id.desc()).first()

    if not row:
        return False

    row.logout_at = datetime.now()
    db.add(row)
    db.commit()
    return True


def list_sessions_today(
    db: Session,
    *,
    role: str = "ejecutivo",
) -> list[UserSessionHistory]:
    today = date.today()
    return (
        db.query(UserSessionHistory)
        .filter(
            extract("year", UserSessionHistory.login_at) == today.year,
            extract("month", UserSessionHistory.login_at) == today.month,
            extract("day", UserSessionHistory.login_at) == today.day,
            UserSessionHistory.role == str(role),
        )
        .order_by(UserSessionHistory.login_at.desc(), UserSessionHistory.id.desc())
        .all()
    )


def list_sessions_month(
    db: Session,
    *,
    year: int,
    month: int,
    role: str = "ejecutivo",
) -> list[UserSessionHistory]:
    return (
        db.query(UserSessionHistory)
        .filter(
            extract("year", UserSessionHistory.login_at) == int(year),
            extract("month", UserSessionHistory.login_at) == int(month),
            UserSessionHistory.role == str(role),
        )
        .order_by(UserSessionHistory.login_at.desc(), UserSessionHistory.id.desc())
        .all()
    )
