from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LegalAcceptanceRequest,
    LegalAcceptanceStatusResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    MessageResponse,
    LoginRequest,
    TokenResponse,
    UserMeResponse,
)
from app.services.auth_service import (
    authenticate_user,
    change_current_user_password,
    create_assisted_recovery_request,
    get_user_by_id,
    user_to_me,
)
from app.services.legal_acceptance_service import (
    get_legal_acceptance_status,
    register_legal_acceptance,
)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado.",
        )

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado.",
        )

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido.",
        )

    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido.",
        ) from exc

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta cuenta esta desactivada. Contacta al administrador.",
        )

    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        return authenticate_user(db, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("/me", response_model=UserMeResponse)
def me(current_user: User = Depends(get_current_user)):
    return user_to_me(current_user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        change_current_user_password(
            db=db,
            user=current_user,
            new_password=payload.new_password,
            confirm_password=payload.confirm_password,
        )
        return MessageResponse(message="Contrasena actualizada correctamente.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/request-assisted-recovery", response_model=MessageResponse)
def request_assisted_recovery(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    try:
        msg = create_assisted_recovery_request(db=db, email=payload.email)
        return MessageResponse(message=msg)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/request-password-reset", response_model=MessageResponse)
def request_password_reset_legacy(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    try:
        msg = create_assisted_recovery_request(db=db, email=payload.email)
        return MessageResponse(message=msg)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/confirm-password-reset", response_model=MessageResponse)
def do_confirm_password_reset_legacy(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="El reseteo directo por codigo fue deshabilitado. Solicita recuperacion asistida.",
    )


@router.get("/legal/acceptance-status", response_model=LegalAcceptanceStatusResponse)
def legal_acceptance_status(
    terms_version: str,
    privacy_version: str,
    acceptance_source: str = "desktop_app",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_legal_acceptance_status(
        db,
        user=current_user,
        terms_version=terms_version,
        privacy_version=privacy_version,
        acceptance_source=acceptance_source,
    )


@router.post("/legal/accept", response_model=LegalAcceptanceStatusResponse)
def legal_accept(
    payload: LegalAcceptanceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.accepted_terms or not payload.accepted_privacy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes aceptar terminos y privacidad para continuar.",
        )

    return register_legal_acceptance(
        db,
        user=current_user,
        accepted_terms=bool(payload.accepted_terms),
        accepted_privacy=bool(payload.accepted_privacy),
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
        acceptance_source=payload.acceptance_source,
        client_version=payload.client_version,
    )
