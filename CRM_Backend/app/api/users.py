from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.user import (
    UserCreateRequest,
    UserListItem,
    UserUpdateRequest,
    UserCarteraAssignmentBulkRequest,
    UserCarteraAssignmentItem,
    UserCarteraEmpresasResponse,
    AssistedPasswordResetResponse,
)
from app.services.user_service import (
    admin_create_user_service,
    admin_delete_user_service,
    admin_list_users_service,
    admin_update_user_service,
    get_current_user_carteras_service,
    get_user_carteras_service,
    list_cartera_assignments_service,
    save_cartera_assignments_service,
    assisted_reset_password_service,
)

router = APIRouter(prefix="/users", tags=["users"])


def _ensure_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar usuarios.",
        )


def _ensure_admin_or_supervisor(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para consultar usuarios.",
        )


@router.get("", response_model=list[UserListItem])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    return admin_list_users_service(db)


@router.get("/carteras", response_model=list[UserCarteraAssignmentItem])
def list_cartera_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return list_cartera_assignments_service(
            db=db,
            executor=current_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.put("/carteras", response_model=list[UserCarteraAssignmentItem])
def save_cartera_assignments(
    payload: UserCarteraAssignmentBulkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        normalized = [{"empresa": item.empresa, "user_id": item.user_id} for item in payload.assignments]
        return save_cartera_assignments_service(
            db=db,
            executor=current_user,
            assignments=normalized,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/me/carteras", response_model=UserCarteraEmpresasResponse)
def get_me_carteras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        empresas = get_current_user_carteras_service(
            db=db,
            executor=current_user,
        )
        return UserCarteraEmpresasResponse(user_id=int(current_user.id), empresas=empresas)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post("", response_model=UserListItem, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    try:
        return admin_create_user_service(
            db=db,
            executor=current_user,
            email=payload.email,
            username=payload.username,
            role=payload.role,
            temp_password=payload.temp_password,
            confirm_password=payload.confirm_password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.put("/{user_id}", response_model=UserListItem)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    try:
        return admin_update_user_service(
            db=db,
            executor=current_user,
            target_user_id=user_id,
            username=payload.username,
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    try:
        admin_delete_user_service(
            db=db,
            executor=current_user,
            target_user_id=user_id,
        )
        return MessageResponse(message="Usuario eliminado correctamente.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{user_id}/carteras", response_model=UserCarteraEmpresasResponse)
def get_user_carteras(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        empresas = get_user_carteras_service(
            db=db,
            executor=current_user,
            target_user_id=user_id,
        )
        return UserCarteraEmpresasResponse(user_id=user_id, empresas=empresas)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post("/{user_id}/assisted-reset-password", response_model=AssistedPasswordResetResponse)
def assisted_reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    try:
        user_item, temp_password = assisted_reset_password_service(
            db=db,
            executor=current_user,
            target_user_id=user_id,
        )
        return AssistedPasswordResetResponse(
            user=user_item,
            temporary_password=temp_password,
            must_change_password=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
