from __future__ import annotations

from typing import Any

from .acceptance_db import get_status as local_get_status
from .acceptance_db import register_acceptance as local_register_acceptance
from .constants import ACCEPTANCE_SOURCE_DESKTOP, PRIVACY_VERSION, TERMS_VERSION


def _session_identity(session: Any) -> tuple[int, str, str]:
    user_id = int(getattr(session, "user_id", 0) or 0)
    email = str(getattr(session, "email", "") or "").strip()
    username = str(getattr(session, "username", "") or "").strip()
    return user_id, email, username


def get_acceptance_status(session: Any) -> tuple[dict, str]:
    user_id, _, _ = _session_identity(session)
    if user_id <= 0:
        return {
            "has_valid_acceptance": False,
            "accepted_terms": False,
            "accepted_privacy": False,
            "terms_version": "",
            "privacy_version": "",
            "accepted_at": "",
            "acceptance_source": ACCEPTANCE_SOURCE_DESKTOP,
        }, "Sesión inválida para validar aceptación legal."

    if getattr(session, "auth_source", "") == "backend":
        from auth.auth_service import backend_get_legal_acceptance_status

        data, err = backend_get_legal_acceptance_status(
            session,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            acceptance_source=ACCEPTANCE_SOURCE_DESKTOP,
        )
        return (data or {}), (err or "")

    status = local_get_status(
        user_id=user_id,
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
        acceptance_source=ACCEPTANCE_SOURCE_DESKTOP,
    )
    return {
        "has_valid_acceptance": bool(status.has_valid_acceptance),
        "accepted_terms": bool(status.accepted_terms),
        "accepted_privacy": bool(status.accepted_privacy),
        "terms_version": status.terms_version,
        "privacy_version": status.privacy_version,
        "accepted_at": status.accepted_at,
        "acceptance_source": status.acceptance_source,
    }, ""


def register_acceptance(session: Any) -> tuple[dict, str]:
    user_id, email, username = _session_identity(session)
    if user_id <= 0:
        return {}, "Sesión inválida para registrar aceptación legal."

    if getattr(session, "auth_source", "") == "backend":
        from auth.auth_service import backend_register_legal_acceptance

        data, err = backend_register_legal_acceptance(
            session,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            acceptance_source=ACCEPTANCE_SOURCE_DESKTOP,
        )
        return (data or {}), (err or "")

    status = local_register_acceptance(
        user_id=user_id,
        user_email=email,
        username=username,
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
        acceptance_source=ACCEPTANCE_SOURCE_DESKTOP,
    )
    return {
        "has_valid_acceptance": bool(status.has_valid_acceptance),
        "accepted_terms": bool(status.accepted_terms),
        "accepted_privacy": bool(status.accepted_privacy),
        "terms_version": status.terms_version,
        "privacy_version": status.privacy_version,
        "accepted_at": status.accepted_at,
        "acceptance_source": status.acceptance_source,
    }, ""


def requires_acceptance(session: Any) -> tuple[bool, str]:
    status, err = get_acceptance_status(session)
    if err:
        return True, err
    return not bool(status.get("has_valid_acceptance", False)), ""
