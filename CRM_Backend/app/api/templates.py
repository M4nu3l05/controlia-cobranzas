from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.template import (
    EmailTemplateCreateRequest,
    EmailTemplateItem,
    EmailTemplateUpdateRequest,
)
from app.services.template_service import (
    create_email_template_service,
    delete_email_template_service,
    list_email_templates_service,
    update_email_template_service,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _ensure_can_manage_templates(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor", "ejecutivo"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar plantillas.",
        )


@router.get("/email", response_model=list[EmailTemplateItem])
def list_email_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_email_templates_service(db)


@router.post("/email", response_model=EmailTemplateItem, status_code=status.HTTP_201_CREATED)
def create_email_template(
    payload: EmailTemplateCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_can_manage_templates(current_user)
    try:
        return create_email_template_service(db, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/email/{template_id}", response_model=EmailTemplateItem)
def update_email_template(
    template_id: int,
    payload: EmailTemplateUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_can_manage_templates(current_user)
    try:
        return update_email_template_service(db, template_id=template_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/email/{template_id}", response_model=MessageResponse)
def delete_email_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_can_manage_templates(current_user)
    try:
        delete_email_template_service(db, template_id=template_id)
        return MessageResponse(message="Plantilla eliminada correctamente.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
