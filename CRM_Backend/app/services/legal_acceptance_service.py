from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.legal_acceptance import LegalAcceptanceCurrent, LegalAcceptanceEvent
from app.models.user import User
from app.schemas.auth import LegalAcceptanceStatusResponse


def _norm_text(value: str) -> str:
    return str(value or "").strip()


def _fmt_dt(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def get_legal_acceptance_status(
    db: Session,
    *,
    user: User,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str,
) -> LegalAcceptanceStatusResponse:
    source = _norm_text(acceptance_source) or "desktop_app"

    row = (
        db.query(LegalAcceptanceCurrent)
        .filter(
            LegalAcceptanceCurrent.user_id == int(user.id),
            LegalAcceptanceCurrent.acceptance_source == source,
        )
        .order_by(LegalAcceptanceCurrent.id.desc())
        .first()
    )

    if not row:
        return LegalAcceptanceStatusResponse(
            has_valid_acceptance=False,
            accepted_terms=False,
            accepted_privacy=False,
            terms_version="",
            privacy_version="",
            accepted_at="",
            acceptance_source=source,
        )

    valid = (
        bool(row.accepted_terms)
        and bool(row.accepted_privacy)
        and _norm_text(row.terms_version) == _norm_text(terms_version)
        and _norm_text(row.privacy_version) == _norm_text(privacy_version)
    )

    return LegalAcceptanceStatusResponse(
        has_valid_acceptance=bool(valid),
        accepted_terms=bool(row.accepted_terms),
        accepted_privacy=bool(row.accepted_privacy),
        terms_version=_norm_text(row.terms_version),
        privacy_version=_norm_text(row.privacy_version),
        accepted_at=_fmt_dt(row.accepted_at),
        acceptance_source=_norm_text(row.acceptance_source) or source,
    )


def register_legal_acceptance(
    db: Session,
    *,
    user: User,
    accepted_terms: bool,
    accepted_privacy: bool,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str,
    client_version: str = "",
) -> LegalAcceptanceStatusResponse:
    source = _norm_text(acceptance_source) or "desktop_app"
    now = datetime.now()

    event = LegalAcceptanceEvent(
        user_id=int(user.id),
        user_email=_norm_text(user.email),
        username=_norm_text(user.username),
        accepted_terms=bool(accepted_terms),
        accepted_privacy=bool(accepted_privacy),
        terms_version=_norm_text(terms_version),
        privacy_version=_norm_text(privacy_version),
        accepted_at=now,
        acceptance_source=source,
        client_version=_norm_text(client_version),
    )
    db.add(event)

    current = (
        db.query(LegalAcceptanceCurrent)
        .filter(
            LegalAcceptanceCurrent.user_id == int(user.id),
            LegalAcceptanceCurrent.acceptance_source == source,
        )
        .order_by(LegalAcceptanceCurrent.id.desc())
        .first()
    )

    if not current:
        current = LegalAcceptanceCurrent(
            user_id=int(user.id),
            user_email=_norm_text(user.email),
            username=_norm_text(user.username),
            accepted_terms=bool(accepted_terms),
            accepted_privacy=bool(accepted_privacy),
            terms_version=_norm_text(terms_version),
            privacy_version=_norm_text(privacy_version),
            accepted_at=now,
            acceptance_source=source,
            client_version=_norm_text(client_version),
        )
        db.add(current)
    else:
        current.user_email = _norm_text(user.email)
        current.username = _norm_text(user.username)
        current.accepted_terms = bool(accepted_terms)
        current.accepted_privacy = bool(accepted_privacy)
        current.terms_version = _norm_text(terms_version)
        current.privacy_version = _norm_text(privacy_version)
        current.accepted_at = now
        current.client_version = _norm_text(client_version)
        db.add(current)

    db.commit()

    return get_legal_acceptance_status(
        db,
        user=user,
        terms_version=terms_version,
        privacy_version=privacy_version,
        acceptance_source=source,
    )
