from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.models.operations import DerivationTracking
from app.models.user import User
from app.schemas.gestion import GestionCreateRequest, GestionItem
from app.core.authorization import (
    AuthorizationError,
    is_derivation,
    require_company_operation,
    require_supervisor,
    resolve_derivation_target,
)
from app.services.deudor_service import (
    reverse_payment_transaction_service,
    revertir_pago_backend_service,
)
from app.services.operations_service import create_notification

ESTADO_DEUDOR_DEFAULT = "Sin Gestión"

MAPEO_ESTADO_GESTION_A_DEUDOR = {
    "enviado": "Gestionado",
    "entregado": "Gestionado",
    "no entregado": "Inubicable",
    "sin respuesta": "Gestionado",
    "respondido": "Contactado",
    "rechazado": "Gestionado",
    "birlado": "Birlado",
    "cip con intención de pago": "CIP Con intención de pago",
    "sip sin intención de pago": "SIP Sin intención de pago",
    "sip con intención de pago": "SIP Sin intención de pago",
    "fallecido": "Fallecido",
    "contactado": "Contactado",
    "gestionado": "Gestionado",
    "inubicable": "Inubicable",
    "pagado": "Gestionado",
    "cliente sin deuda": "Cliente Sin deuda",
}


def _norm_text(value: str) -> str:
    return str(value or "").strip()


def _norm_rut(value: str) -> str:
    return _norm_text(value).replace(".", "").replace("-", "").lstrip("0")


def _estado_gestion_a_estado_deudor(estado_gestion: str) -> str:
    estado_norm = " ".join(str(estado_gestion or "").strip().lower().split())
    return MAPEO_ESTADO_GESTION_A_DEUDOR.get(
        estado_norm,
        "Gestionado" if estado_norm else ESTADO_DEUDOR_DEFAULT,
    )


def _fecha_sort_key(fecha: str, fallback_id: int) -> tuple:
    txt = _norm_text(fecha)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return (datetime.strptime(txt, fmt), fallback_id)
        except Exception:
            pass
    return (datetime.min, fallback_id)


import re


def _to_item(row: DeudorGestion, tracking: DerivationTracking | None = None) -> GestionItem:
    due_at = getattr(tracking, "due_at", None)
    completed_at = getattr(tracking, "completed_at", None)
    return GestionItem(
        id=row.id,
        empresa=row.empresa,
        rut_afiliado=row.rut_afiliado,
        nombre_afiliado=row.nombre_afiliado,
        tipo_gestion=row.tipo_gestion,
        estado=row.estado,
        fecha_gestion=row.fecha_gestion,
        observacion=row.observacion,
        origen=row.origen,
        assigned_to_user_id=row.assigned_to_user_id,
        derivation_created_by_user_id=(
            int(tracking.created_by_user_id) if tracking is not None else None
        ),
        derivation_due_at=due_at,
        derivation_completed_at=completed_at,
        derivation_is_overdue=bool(due_at and completed_at is None and due_at < datetime.now()),
    )




def _extraer_payload_pago_desde_observacion(observacion: str) -> dict:
    texto = _norm_text(observacion)

    def _extract(label: str) -> str:
        m = re.search(rf"{label}:\s*([^|]+)", texto, flags=re.IGNORECASE)
        return m.group(1).strip() if m else ""

    empresa = _extract("Empresa")
    expediente = _extract("Expediente")
    tipo_pago = _extract("Tipo")
    monto_txt = _extract("Monto")
    transaction_id = _extract("Transaccion")

    monto = 0.0
    if monto_txt:
        try:
            limpio = monto_txt.replace("$", "").replace(" ", "").replace(",", "")
            monto = float(limpio)
        except Exception:
            monto = 0.0

    return {
        "empresa": empresa,
        "expediente": expediente,
        "tipo_pago": tipo_pago,
        "monto": monto,
        "transaction_id": transaction_id,
    }


def _recalcular_estado_deudor(db: Session, *, empresa: str, rut: str) -> None:
    empresa_txt = _norm_text(empresa)
    rut_norm = _norm_rut(rut)

    rows = (
        db.query(DeudorGestion)
        .filter(
            func.trim(DeudorGestion.empresa) == empresa_txt,
            func.ltrim(
                func.replace(
                    func.replace(func.trim(DeudorGestion.rut_afiliado), ".", ""),
                    "-",
                    "",
                ),
                "0",
            ) == rut_norm,
        )
        .all()
    )

    operational_rows = [row for row in rows if row.assigned_to_user_id is None]
    if operational_rows:
        rows_sorted = sorted(
            operational_rows,
            key=lambda r: _fecha_sort_key(r.fecha_gestion, r.id),
            reverse=True,
        )
        estado_deudor = _estado_gestion_a_estado_deudor(rows_sorted[0].estado)
    else:
        estado_deudor = ESTADO_DEUDOR_DEFAULT

    resumen_rows = (
        db.query(DeudorResumen)
        .filter(
            func.trim(DeudorResumen.empresa) == empresa_txt,
            func.ltrim(
                func.replace(
                    func.replace(func.trim(DeudorResumen.rut_afiliado), ".", ""),
                    "-",
                    "",
                ),
                "0",
            ) == rut_norm,
        )
        .all()
    )
    for row in resumen_rows:
        row.estado_deudor = estado_deudor

    detalle_rows = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            func.ltrim(
                func.replace(
                    func.replace(func.trim(DeudorDetalle.rut_afiliado), ".", ""),
                    "-",
                    "",
                ),
                "0",
            ) == rut_norm,
        )
        .all()
    )
    for row in detalle_rows:
        row.estado_deudor = estado_deudor

    db.commit()


def list_gestiones_service(
    db: Session,
    *,
    rut: str,
    empresa: str = "",
) -> list[GestionItem]:
    rut_norm = _norm_rut(rut)
    empresa_txt = _norm_text(empresa)

    query = db.query(DeudorGestion).filter(
        func.ltrim(
            func.replace(
                func.replace(func.trim(DeudorGestion.rut_afiliado), ".", ""),
                "-",
                "",
            ),
            "0",
        ) == rut_norm
    )

    if empresa_txt:
        query = query.filter(func.trim(DeudorGestion.empresa) == empresa_txt)

    rows = query.all()
    rows_sorted = sorted(rows, key=lambda r: _fecha_sort_key(r.fecha_gestion, r.id), reverse=True)
    return [_to_item(row) for row in rows_sorted]


def list_gestiones_global_service(
    db: Session,
    *,
    empresa: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
) -> list[GestionItem]:
    empresa_txt = _norm_text(empresa)
    fecha_desde_txt = _norm_text(fecha_desde)
    fecha_hasta_txt = _norm_text(fecha_hasta)

    query = db.query(DeudorGestion)
    if empresa_txt:
        query = query.filter(func.trim(DeudorGestion.empresa) == empresa_txt)

    rows = query.all()
    rows_sorted = sorted(rows, key=lambda r: _fecha_sort_key(r.fecha_gestion, r.id), reverse=True)

    if fecha_desde_txt or fecha_hasta_txt:
        desde_key = _fecha_sort_key(fecha_desde_txt, 0)[0] if fecha_desde_txt else None
        hasta_key = _fecha_sort_key(fecha_hasta_txt, 0)[0] if fecha_hasta_txt else None

        filtradas: list[DeudorGestion] = []
        for row in rows_sorted:
            fecha_row = _fecha_sort_key(row.fecha_gestion, row.id)[0]
            if fecha_row == datetime.min:
                continue
            if desde_key is not None and fecha_row < desde_key:
                continue
            if hasta_key is not None and fecha_row > hasta_key:
                continue
            filtradas.append(row)
        rows_sorted = filtradas

    return [_to_item(row) for row in rows_sorted]


def create_gestion_service(
    db: Session,
    *,
    rut: str,
    payload: GestionCreateRequest,
    executor: User,
) -> GestionItem:
    rut_norm = _norm_rut(rut)
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")

    estado_txt = _norm_text(payload.estado)
    empresa_txt = _norm_text(payload.empresa)
    derivation = is_derivation(
        status=estado_txt,
        assigned_to_user_id=payload.assigned_to_user_id,
    )
    if derivation:
        assigned_to_user_id = resolve_derivation_target(
            db,
            company=empresa_txt,
            requested_user_id=payload.assigned_to_user_id,
        )
    else:
        require_company_operation(db, executor, empresa_txt)
        assigned_to_user_id = None

    row = DeudorGestion(
        empresa=empresa_txt,
        rut_afiliado=rut_norm,
        nombre_afiliado=_norm_text(payload.nombre_afiliado),
        tipo_gestion=_norm_text(payload.tipo_gestion),
        estado=estado_txt,
        fecha_gestion=_norm_text(payload.fecha_gestion),
        observacion=_norm_text(payload.observacion),
        origen=_norm_text(payload.origen) or "manual",
        assigned_to_user_id=assigned_to_user_id,
    )
    db.add(row)
    db.flush()

    tracking = None
    if derivation and assigned_to_user_id is not None:
        tracking = DerivationTracking(
            gestion_id=int(row.id),
            created_by_user_id=int(executor.id),
            assigned_to_user_id=int(assigned_to_user_id),
            due_at=datetime.now() + timedelta(hours=24),
        )
        db.add(tracking)
        create_notification(
            db,
            user_id=int(assigned_to_user_id),
            notification_type="derivation_assigned",
            title="Nueva derivacion asignada",
            message=f"Debes contactar a {row.nombre_afiliado or row.rut_afiliado} antes de 24 horas.",
            empresa=row.empresa,
            rut_afiliado=row.rut_afiliado,
            related_entity_type="gestion",
            related_entity_id=int(row.id),
        )
    db.commit()
    db.refresh(row)

    _recalcular_estado_deudor(db, empresa=row.empresa, rut=row.rut_afiliado)
    return _to_item(row, tracking)


def delete_gestion_service(db: Session, *, gestion_id: int, executor: User) -> None:
    row = db.query(DeudorGestion).filter(DeudorGestion.id == int(gestion_id)).first()
    if not row:
        raise ValueError("La gestión indicada no existe.")

    origen = _norm_text(row.origen).lower()
    if origen.startswith("excel"):
        raise ValueError("No se pueden eliminar gestiones cargadas desde Excel.")

    empresa = row.empresa
    rut = row.rut_afiliado
    tipo_gestion = _norm_text(row.tipo_gestion).lower()

    if tipo_gestion == "pago" or origen.startswith("backend_pago"):
        require_supervisor(executor, action="revertir un pago")
        payload_pago = _extraer_payload_pago_desde_observacion(row.observacion)
        empresa_pago = _norm_text(payload_pago.get("empresa")) or empresa
        expediente_pago = _norm_text(payload_pago.get("expediente"))
        monto_pago = float(payload_pago.get("monto") or 0)
        transaction_id = _norm_text(payload_pago.get("transaction_id"))

        if transaction_id:
            reverse_payment_transaction_service(
                db,
                transaction_public_id=transaction_id,
                executor=executor,
            )
        else:
            if not expediente_pago or monto_pago <= 0:
                raise ValueError(
                    "No fue posible revertir el pago porque la observación de la gestión no contiene los datos necesarios."
                )
            revertir_pago_backend_service(
                db,
                rut=rut,
                empresa=empresa_pago,
                expediente=expediente_pago,
                monto=monto_pago,
            )

        row.estado = "Pago revertido"
        row.origen = "backend_pago_revertido"
        row.observacion = f"{row.observacion} | Revertido por: {_norm_text(executor.username)}"
        db.add(row)
        db.commit()

        _recalcular_estado_deudor(db, empresa=empresa, rut=rut)
        return

    require_company_operation(db, executor, empresa)
    db.query(DerivationTracking).filter(
        DerivationTracking.gestion_id == int(row.id)
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()

    _recalcular_estado_deudor(db, empresa=empresa, rut=rut)


def clear_all_gestiones_service(db: Session) -> bool:
    deleted = db.query(DeudorGestion).delete(synchronize_session=False)

    # Al limpiar gestiones, el estado deudor debe volver a estado base.
    # Si no tiene saldo, se mantiene "Cliente Sin deuda"; en otro caso, "Sin Gestión".
    resumen_rows = db.query(DeudorResumen).all()
    for row in resumen_rows:
        saldo = float(getattr(row, "saldo_actual", 0) or 0)
        row.estado_deudor = "Cliente Sin deuda" if saldo <= 0 else ESTADO_DEUDOR_DEFAULT

    detalle_rows = db.query(DeudorDetalle).all()
    for row in detalle_rows:
        saldo = float(getattr(row, "saldo_actual", 0) or 0)
        row.estado_deudor = "Cliente Sin deuda" if saldo <= 0 else ESTADO_DEUDOR_DEFAULT

    db.commit()
    return bool(deleted)


def ensure_gestiones_optional_columns(db: Session) -> None:
    bind = getattr(db, "bind", None)
    dialect_obj = getattr(bind, "dialect", None) if bind is not None else None
    dialect = str(getattr(dialect_obj, "name", "") or "").lower()

    if dialect == "sqlite":
        rows = db.execute(text("PRAGMA table_info(deudores_gestiones)")).mappings().all()
        cols = {str(r.get("name") or "").strip() for r in rows}
        if "assigned_to_user_id" not in cols:
            db.execute(
                text(
                    "ALTER TABLE deudores_gestiones "
                    "ADD COLUMN assigned_to_user_id INTEGER NULL"
                )
            )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_deudores_gestiones_assigned_to "
                "ON deudores_gestiones(assigned_to_user_id)"
            )
        )
        db.commit()
        return

    if dialect in {"postgresql", "postgres"}:
        db.execute(
            text(
                "ALTER TABLE deudores_gestiones "
                "ADD COLUMN IF NOT EXISTS assigned_to_user_id INTEGER NULL"
            )
        )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_deudores_gestiones_assigned_to "
                "ON deudores_gestiones(assigned_to_user_id)"
            )
        )
        db.commit()
        return

    try:
        db.execute(
            text(
                "ALTER TABLE deudores_gestiones "
                "ADD COLUMN assigned_to_user_id INTEGER"
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _resolver_asignacion_por_empresa(db: Session, *, empresa: str) -> int | None:
    empresa_txt = _norm_text(empresa)
    if not empresa_txt:
        return None
    empresa_key = "".join(ch for ch in empresa_txt.lower() if ch.isalnum())
    try:
        rows = db.execute(
            text(
                """
                SELECT empresa, user_id
                FROM cartera_asignaciones
                """
            ),
        ).fetchall()
    except Exception:
        db.rollback()
        return None
    for row in rows:
        row_key = "".join(ch for ch in _norm_text(row[0]).lower() if ch.isalnum())
        if row_key != empresa_key or row[1] is None:
            continue
        try:
            return int(row[1])
        except Exception:
            return None
    return None


def list_gestiones_asignadas_para_usuario_service(
    db: Session,
    *,
    user_id: int,
) -> list[GestionItem]:
    rows = (
        db.query(DeudorGestion)
        .filter(DeudorGestion.assigned_to_user_id == int(user_id))
        .all()
    )
    rows_sorted = sorted(rows, key=lambda r: _fecha_sort_key(r.fecha_gestion, r.id), reverse=True)
    tracking_rows = (
        db.query(DerivationTracking)
        .filter(DerivationTracking.gestion_id.in_([int(row.id) for row in rows_sorted]))
        .all()
        if rows_sorted
        else []
    )
    tracking_by_gestion = {int(item.gestion_id): item for item in tracking_rows}
    out: list[GestionItem] = []
    for row in rows_sorted:
        estado = " ".join(str(row.estado or "").strip().lower().split())
        if estado == "gestión realizada" or estado == "gestion realizada":
            continue
        out.append(_to_item(row, tracking_by_gestion.get(int(row.id))))
    return out


def marcar_gestion_asignada_realizada_service(
    db: Session,
    *,
    gestion_id: int,
    executor: User,
) -> GestionItem:
    row = db.query(DeudorGestion).filter(DeudorGestion.id == int(gestion_id)).first()
    if not row:
        raise ValueError("La gestión indicada no existe.")

    if row.assigned_to_user_id is None:
        raise ValueError("La gestión no está marcada como tarea asignada.")

    if int(row.assigned_to_user_id) != int(executor.id):
        raise AuthorizationError("No tienes permiso para cerrar esta gestion asignada.")

    row.estado = "Gestión realizada"
    row.updated_at = datetime.now()
    db.add(row)
    tracking = db.query(DerivationTracking).filter(
        DerivationTracking.gestion_id == int(row.id)
    ).first()
    if tracking is not None:
        tracking.completed_at = datetime.now()
        tracking.completed_by_user_id = int(executor.id)
        db.add(tracking)
        if int(tracking.created_by_user_id) != int(executor.id):
            create_notification(
                db,
                user_id=int(tracking.created_by_user_id),
                notification_type="derivation_completed",
                title="Derivacion completada",
                message=f"La derivacion de {row.nombre_afiliado or row.rut_afiliado} fue marcada como realizada.",
                empresa=row.empresa,
                rut_afiliado=row.rut_afiliado,
                related_entity_type="gestion",
                related_entity_id=int(row.id),
            )
    db.commit()
    db.refresh(row)

    _recalcular_estado_deudor(db, empresa=row.empresa, rut=row.rut_afiliado)
    return _to_item(row, tracking)
