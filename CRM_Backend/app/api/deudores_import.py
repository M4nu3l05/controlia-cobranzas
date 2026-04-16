from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.deudor import ImportDeudoresResponse
from app.services.deudor_import_service import EMPRESAS_VALIDAS, import_deudores_excel_service

router = APIRouter(prefix="/deudores", tags=["deudores-import"])


def _ensure_supervisor_or_admin(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para cargar bases de deudores.",
        )


@router.post("/import", response_model=ImportDeudoresResponse)
async def import_deudores(
    empresa: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_supervisor_or_admin(current_user)

    empresa_txt = str(empresa or "").strip()
    if empresa_txt not in EMPRESAS_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Empresa no válida. Opciones: {', '.join(EMPRESAS_VALIDAS)}",
        )

    filename = file.filename or "archivo.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes subir un archivo Excel válido (.xlsx o .xls).",
        )

    try:
        content = await file.read()
        result = import_deudores_excel_service(
            db,
            empresa=empresa_txt,
            content=content,
            source_file=filename,
        )
        return ImportDeudoresResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo importar la base de deudores: {exc}",
        ) from exc

