from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import date

from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.operations import CustomerChangeAudit
from app.models.payment import PaymentAllocation, PaymentReceipt, PaymentReversal, PaymentTransaction
from app.models.user import User
from app.core.authorization import assigned_user_id_for_company, require_supervisor
from app.core.text_utils import fix_mojibake_text
from app.services.operations_service import create_notification
try:
    from app.models.gestion import DeudorGestion
except Exception:  # pragma: no cover
    DeudorGestion = None

from app.schemas.deudor import (
    DestinatarioItem,
    DeudorDetalleItem,
    DeudorDetalleResponse,
    DeudorListItem,
    DeudorListResponse,
    RegistrarPagoResponse,
    ActualizarClienteResponse,
    DashboardCompanyItem,
    DashboardSummaryResponse,
)


def _norm_text(value: str) -> str:
    return fix_mojibake_text(value).strip()


def _norm_rut(value: str) -> str:
    txt = _norm_text(value).replace(".", "")
    if "-" in txt:
        txt = txt.split("-", 1)[0]
    return txt.replace("-", "").lstrip("0")


def _norm_expediente(value: str) -> str:
    txt = _norm_text(value).replace("\u00a0", " ")
    txt = "".join(txt.split())
    if txt.endswith(".0"):
        txt = txt[:-2]
    return txt.lower()


def _rut_db_expr(column):
    return func.ltrim(
        func.replace(
            func.replace(
                func.trim(column),
                ".",
                "",
            ),
            "-",
            "",
        ),
        "0",
    )


def _saldo_pendiente_detalle(row: DeudorDetalle) -> float:
    saldo = float(getattr(row, "saldo_actual", 0) or 0)
    saldo_calc = max(
        float(getattr(row, "copago", 0) or 0) - float(getattr(row, "total_pagos", 0) or 0),
        0.0,
    )
    if saldo <= 0:
        return saldo_calc
    if abs(saldo - saldo_calc) > 0.01:
        return saldo_calc
    return saldo


def clear_empresa_deudores_service(db: Session, *, empresa: str) -> bool:
    empresa_txt = _norm_text(empresa)
    if not empresa_txt:
        raise ValueError("Debes indicar una empresa válida.")

    deleted_detalle = db.query(DeudorDetalle).filter(DeudorDetalle.empresa == empresa_txt).delete(synchronize_session=False)
    deleted_resumen = db.query(DeudorResumen).filter(DeudorResumen.empresa == empresa_txt).delete(synchronize_session=False)
    db.commit()
    return bool(deleted_detalle or deleted_resumen)


def clear_all_deudores_service(db: Session) -> list[str]:
    empresas = [
        empresa
        for (empresa,) in db.query(DeudorResumen.empresa).distinct().all()
        if _norm_text(empresa)
    ]

    db.query(DeudorDetalle).delete(synchronize_session=False)
    db.query(DeudorResumen).delete(synchronize_session=False)
    db.commit()
    return sorted(set(empresas))


def delete_deudor_individual_service(
    db: Session,
    *,
    empresa: str,
    rut: str,
) -> bool:
    empresa_txt = _norm_text(empresa)
    rut_norm = _norm_rut(rut)
    if not empresa_txt:
        raise ValueError("Debes indicar una empresa válida.")
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")

    deleted_detalle = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
        )
        .delete(synchronize_session=False)
    )
    deleted_resumen = (
        db.query(DeudorResumen)
        .filter(
            func.trim(DeudorResumen.empresa) == empresa_txt,
            _rut_db_expr(DeudorResumen.rut_afiliado) == rut_norm,
        )
        .delete(synchronize_session=False)
    )

    deleted_gestiones = 0
    if DeudorGestion is not None:
        deleted_gestiones = (
            db.query(DeudorGestion)
            .filter(
                func.trim(DeudorGestion.empresa) == empresa_txt,
                _rut_db_expr(DeudorGestion.rut_afiliado) == rut_norm,
            )
            .delete(synchronize_session=False)
        )

    db.commit()
    return bool(deleted_detalle or deleted_resumen or deleted_gestiones)


def _to_resumen_item(row: DeudorResumen) -> DeudorListItem:
    return DeudorListItem(
        empresa=row.empresa,
        rut_afiliado=row.rut_afiliado,
        dv=row.dv,
        rut_completo=row.rut_completo,
        nombre_afiliado=row.nombre_afiliado,
        estado_deudor=row.estado_deudor,
        bn=row.bn,
        nro_expediente=row.nro_expediente,
        max_emision_ok=row.max_emision_ok,
        min_emision_ok=row.min_emision_ok,
        copago=float(row.copago or 0),
        total_pagos=float(row.total_pagos or 0),
        saldo_actual=float(row.saldo_actual or 0),
        source_file=_norm_text(getattr(row, "source_file", "")),
        periodo_carga=_norm_text(getattr(row, "periodo_carga", "")),
    )


def _to_detalle_item(row: DeudorDetalle) -> DeudorDetalleItem:
    return DeudorDetalleItem(
        id=int(row.id),
        empresa=row.empresa,
        rut_afiliado=row.rut_afiliado,
        dv=row.dv,
        rut_completo=row.rut_completo,
        nombre_afiliado=row.nombre_afiliado,
        nombre_afil=_norm_text(getattr(row, "nombre_afil", "")),
        rut_afil=_norm_text(getattr(row, "rut_afil", "")),
        fecha_pago=_norm_text(getattr(row, "fecha_pago", "")),
        mail_afiliado=row.mail_afiliado,
        bn=row.bn,
        telefono_fijo_afiliado=row.telefono_fijo_afiliado,
        telefono_movil_afiliado=row.telefono_movil_afiliado,
        direccion_deudor=_norm_text(getattr(row, "direccion_deudor", "")),
        comuna_deudor=_norm_text(getattr(row, "comuna_deudor", "")),
        ciudad_deudor=_norm_text(getattr(row, "ciudad_deudor", "")),
        nro_expediente=row.nro_expediente,
        id_deuda=_norm_text(getattr(row, "id_deuda", "")),
        fecha_emision=row.fecha_emision,
        fecha_vencimiento=_norm_text(getattr(row, "fecha_vencimiento", "")),
        prestador=_norm_text(getattr(row, "prestador", "")),
        fecha_prestacion=_norm_text(getattr(row, "fecha_prestacion", "")),
        fecha_prestacion2=_norm_text(getattr(row, "fecha_prestacion2", "")),
        copago=float(row.copago or 0),
        total_pagos=float(row.total_pagos or 0),
        saldo_actual=float(row.saldo_actual or 0),
        monto_total=float(getattr(row, "monto_total", 0) or 0),
        monto_cobrar=float(getattr(row, "monto_cobrar", 0) or 0),
        monto_facturado=float(getattr(row, "monto_facturado", 0) or 0),
        monto_liquidado=float(getattr(row, "monto_liquidado", 0) or 0),
        monto_pagado_parcial=float(getattr(row, "monto_pagado_parcial", 0) or 0),
        monto_condonado=float(getattr(row, "monto_condonado", 0) or 0),
        monto_gestionado=float(getattr(row, "monto_gestionado", 0) or 0),
        cuota_acordada=float(getattr(row, "cuota_acordada", 0) or 0),
        cart56_fecha_recep=row.cart56_fecha_recep,
        cart56_fecha_recep_isa=row.cart56_fecha_recep_isa,
        cart56_dias_pagar=_norm_text(getattr(row, "cart56_dias_pagar", "")),
        cart56_mto_pagar=float(row.cart56_mto_pagar or 0),
        mail_emp=row.mail_emp,
        telefono_empleador=row.telefono_empleador,
        estado_deudor=row.estado_deudor,
        source_file=_norm_text(getattr(row, "source_file", "")),
        periodo_carga=_norm_text(getattr(row, "periodo_carga", "")),
    )


def list_destinatarios_service(
    db: Session,
    *,
    empresa: str = "",
    periodo_carga: str = "",
    limit: int = 5000,
    empresas_permitidas: list[str] | None = None,
) -> list[DestinatarioItem]:
    empresa_txt = _norm_text(empresa)
    periodo_txt = _norm_text(periodo_carga)

    resumen_q = db.query(DeudorResumen)
    detalle_q = db.query(DeudorDetalle)

    # None = sin restriccion (admin/supervisor). Una lista vacia significa
    # "sin carteras asignadas", nunca "todas las carteras".
    if empresas_permitidas is not None:
        permitidas = [_norm_text(item) for item in empresas_permitidas if _norm_text(item)]
        if not permitidas:
            return []
        resumen_q = resumen_q.filter(func.trim(DeudorResumen.empresa).in_(permitidas))
        detalle_q = detalle_q.filter(func.trim(DeudorDetalle.empresa).in_(permitidas))

    if empresa_txt:
        resumen_q = resumen_q.filter(func.trim(DeudorResumen.empresa) == empresa_txt)
        detalle_q = detalle_q.filter(func.trim(DeudorDetalle.empresa) == empresa_txt)

    if periodo_txt and periodo_txt.lower() != "acumulado":
        resumen_q = resumen_q.filter(func.trim(DeudorResumen.periodo_carga) == periodo_txt)
        detalle_q = detalle_q.filter(func.trim(DeudorDetalle.periodo_carga) == periodo_txt)

    resumen_rows = (
        resumen_q.order_by(
            DeudorResumen.updated_at.desc(),
            DeudorResumen.id.desc(),
        )
        .limit(max(1, min(int(limit), 50000)))
        .all()
    )
    if not resumen_rows:
        return []

    def _email_valido(email: str) -> bool:
        txt = _norm_text(email).lower()
        return bool(txt and txt not in {"nan", "none", "n", "—"} and "@" in txt)

    email_by_key: dict[tuple[str, str], str] = {}
    expediente_by_key: dict[tuple[str, str], str] = {}
    detalle_rows = (
        detalle_q.order_by(
            DeudorDetalle.updated_at.desc(),
            DeudorDetalle.id.desc(),
        )
        .all()
    )
    for det in detalle_rows:
        key = (_norm_text(det.empresa), _norm_rut(det.rut_afiliado))
        if not key[0] or not key[1]:
            continue

        expediente = _norm_text(getattr(det, "nro_expediente", ""))
        if expediente and key not in expediente_by_key:
            expediente_by_key[key] = expediente

        if key in email_by_key and _email_valido(email_by_key[key]):
            continue
        mail = _norm_text(det.mail_afiliado)
        if _email_valido(mail):
            email_by_key[key] = mail
        elif key not in email_by_key:
            email_by_key[key] = mail

    seen_keys: set[tuple[str, str]] = set()
    out: list[DestinatarioItem] = []
    for row in resumen_rows:
        key = (_norm_text(row.empresa), _norm_rut(row.rut_afiliado))
        if key in seen_keys or not key[0] or not key[1]:
            continue
        seen_keys.add(key)

        out.append(
            DestinatarioItem(
                empresa=row.empresa,
                rut_afiliado=row.rut_afiliado,
                nombre_afiliado=row.nombre_afiliado,
                mail_afiliado=email_by_key.get(key, ""),
                estado_deudor=row.estado_deudor,
                nro_expediente=expediente_by_key.get(key, _norm_text(getattr(row, "nro_expediente", ""))),
                copago=float(row.copago or 0),
                total_pagos=float(row.total_pagos or 0),
                saldo_actual=float(row.saldo_actual or 0),
                source_file=_norm_text(getattr(row, "source_file", "")),
                periodo_carga=_norm_text(getattr(row, "periodo_carga", "")),
            )
        )

    out.sort(key=lambda x: (str(x.empresa or ""), str(x.nombre_afiliado or ""), str(x.rut_afiliado or "")))
    return out


def list_deudores_service(
    db: Session,
    *,
    q: str = "",
    empresa: str = "",
    periodo_carga: str = "",
    limit: int = 500,
) -> DeudorListResponse:
    query = db.query(DeudorResumen)

    empresa_txt = _norm_text(empresa)
    if empresa_txt:
        query = query.filter(func.trim(DeudorResumen.empresa) == empresa_txt)

    periodo_txt = _norm_text(periodo_carga)
    if periodo_txt and periodo_txt.lower() != "acumulado":
        query = query.filter(func.trim(DeudorResumen.periodo_carga) == periodo_txt)

    q_txt = _norm_text(q)
    if q_txt:
        rut_q = _norm_rut(q_txt)
        like_q = f"%{q_txt}%"
        query = query.filter(
            or_(
                DeudorResumen.nombre_afiliado.ilike(like_q),
                DeudorResumen.rut_completo.ilike(like_q),
                _rut_db_expr(DeudorResumen.rut_afiliado) == rut_q,
                DeudorResumen.bn.ilike(like_q),
                DeudorResumen.estado_deudor.ilike(like_q),
                DeudorResumen.periodo_carga.ilike(like_q),
                DeudorResumen.source_file.ilike(like_q),
            )
        )

    rows = (
        query.order_by(
            DeudorResumen.nombre_afiliado.asc(),
            DeudorResumen.rut_afiliado.asc(),
        )
        .limit(max(1, min(int(limit), 5000)))
        .all()
    )

    items = [_to_resumen_item(row) for row in rows]
    return DeudorListResponse(items=items, total=len(items))


def get_deudor_detalle_service(
    db: Session,
    *,
    rut: str,
    empresa: str = "",
) -> DeudorDetalleResponse:
    rut_norm = _norm_rut(rut)
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")

    resumen_query = db.query(DeudorResumen).filter(
        or_(
            _rut_db_expr(DeudorResumen.rut_afiliado) == rut_norm,
            _rut_db_expr(DeudorResumen.rut_completo) == rut_norm,
        )
    )

    detalle_query = db.query(DeudorDetalle).filter(
        or_(
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
            _rut_db_expr(DeudorDetalle.rut_completo) == rut_norm,
        )
    )

    empresa_txt = _norm_text(empresa)
    if empresa_txt:
        resumen_query = resumen_query.filter(func.trim(DeudorResumen.empresa) == empresa_txt)
        detalle_query = detalle_query.filter(func.trim(DeudorDetalle.empresa) == empresa_txt)

    resumen_row = (
        resumen_query.order_by(
            DeudorResumen.updated_at.desc(),
            DeudorResumen.id.desc(),
        ).first()
    )

    detalle_rows = (
        detalle_query.order_by(
            DeudorDetalle.nro_expediente.asc(),
            DeudorDetalle.id.asc(),
        ).all()
    )

    if not resumen_row and not detalle_rows:
        raise ValueError("No se encontró información para el RUT indicado.")

    empresa_resp = empresa_txt or (
        resumen_row.empresa if resumen_row else detalle_rows[0].empresa
    )

    return DeudorDetalleResponse(
        rut=rut_norm,
        empresa=empresa_resp,
        resumen=_to_resumen_item(resumen_row) if resumen_row else None,
        detalle=[_to_detalle_item(row) for row in detalle_rows],
    )


def _recalcular_resumen_desde_detalle(
    db: Session,
    *,
    empresa: str,
    rut_norm: str,
    estado_deudor_objetivo: str | None = None,
) -> tuple[float, float, float, str]:
    detalle_rows = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
        )
        .order_by(DeudorDetalle.id.asc())
        .all()
    )

    if not detalle_rows:
        raise ValueError("No se encontraron expedientes para recalcular el resumen.")

    copago_total = float(sum(float(r.copago or 0) for r in detalle_rows))
    total_pagos_total = float(sum(float(r.total_pagos or 0) for r in detalle_rows))
    saldo_total = float(sum(float(r.saldo_actual or 0) for r in detalle_rows))
    expedientes_validos = [
        _norm_text(getattr(r, "nro_expediente", ""))
        for r in detalle_rows
        if _norm_text(getattr(r, "nro_expediente", ""))
    ]
    expedientes_unicos: list[str] = list(dict.fromkeys(expedientes_validos))
    resumen_expediente = (
        expedientes_unicos[0]
        if len(expedientes_unicos) == 1
        else str(len(detalle_rows))
    )

    estado_deudor = _norm_text(estado_deudor_objetivo) if estado_deudor_objetivo else (
        "Cliente Sin deuda" if saldo_total <= 0.5 else "Pagado"
    )

    resumen_rows = (
        db.query(DeudorResumen)
        .filter(
            func.trim(DeudorResumen.empresa) == empresa,
            _rut_db_expr(DeudorResumen.rut_afiliado) == rut_norm,
        )
        .all()
    )
    for row in resumen_rows:
        row.copago = copago_total
        row.total_pagos = total_pagos_total
        row.saldo_actual = max(0.0, saldo_total)
        row.estado_deudor = estado_deudor
        row.nro_expediente = resumen_expediente

    for row in detalle_rows:
        row.estado_deudor = estado_deudor

    return copago_total, total_pagos_total, max(0.0, saldo_total), estado_deudor


def registrar_pago_service(
    db: Session,
    *,
    executor: User,
    rut: str,
    empresa: str,
    expediente: str,
    tipo_pago: str,
    monto: float,
    observaciones: str = "",
    nombre_afiliado: str = "",
    detalle_id: int | None = None,
    fecha_efectiva: date | None = None,
    idempotency_key: str = "",
    distribucion: list | None = None,
    comprobante_nombre: str = "",
    comprobante_tipo: str = "",
    comprobante_base64: str = "",
) -> RegistrarPagoResponse:
    empresa_txt = _norm_text(empresa)
    expediente_txt = _norm_text(expediente)
    tipo_pago_txt = _norm_text(tipo_pago)
    observaciones_txt = _norm_text(observaciones)
    nombre_txt = _norm_text(nombre_afiliado)
    rut_norm = _norm_rut(rut)
    idempotency_txt = _norm_text(idempotency_key)
    amount_clp = int(round(float(monto or 0)))
    effective_date = fecha_efectiva or date.today()

    if not empresa_txt:
        raise ValueError("Debes indicar la empresa.")
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")
    if not expediente_txt:
        raise ValueError("Debes indicar el expediente.")
    if amount_clp <= 0:
        raise ValueError("El monto debe ser mayor a 0.")
    if len(idempotency_txt) < 8:
        raise ValueError("La operacion de pago no tiene un identificador idempotente valido.")

    existing_transaction = db.query(PaymentTransaction).filter(
        PaymentTransaction.idempotency_key == idempotency_txt
    ).first()
    if existing_transaction is not None:
        if (
            existing_transaction.empresa != empresa_txt
            or existing_transaction.rut_afiliado != rut_norm
            or int(existing_transaction.amount_clp) != amount_clp
            or existing_transaction.payment_type != tipo_pago_txt
            or existing_transaction.effective_date != effective_date
            or int(existing_transaction.registered_by_user_id) != int(executor.id)
        ):
            raise ValueError("El identificador del pago ya fue utilizado con datos diferentes.")
        resumen = db.query(DeudorResumen).filter(
            func.trim(DeudorResumen.empresa) == empresa_txt,
            _rut_db_expr(DeudorResumen.rut_afiliado) == rut_norm,
        ).first()
        expediente_rows = db.query(DeudorDetalle).filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
            func.trim(DeudorDetalle.nro_expediente) == expediente_txt,
        ).all()
        return RegistrarPagoResponse(
            ok=True,
            empresa=empresa_txt,
            rut=rut_norm,
            expediente=expediente_txt,
            tipo_pago=existing_transaction.payment_type,
            monto=float(existing_transaction.amount_clp),
            saldo_expediente=float(sum(_saldo_pendiente_detalle(row) for row in expediente_rows)),
            saldo_resumen=float(getattr(resumen, "saldo_actual", 0) or 0),
            total_pagos_resumen=float(getattr(resumen, "total_pagos", 0) or 0),
            estado_deudor=_norm_text(getattr(resumen, "estado_deudor", "")),
            transaction_id=existing_transaction.public_id,
            idempotent_replay=True,
        )

    receipt_content = b""
    receipt_name = _norm_text(comprobante_nombre)
    if comprobante_base64:
        try:
            receipt_content = base64.b64decode(comprobante_base64, validate=True)
        except Exception as exc:
            raise ValueError("El comprobante adjunto no tiene un formato valido.") from exc
        if len(receipt_content) > 5 * 1024 * 1024:
            raise ValueError("El comprobante no puede superar 5 MB.")
        if not receipt_name:
            raise ValueError("Debes indicar el nombre del comprobante adjunto.")
        if not receipt_name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
            raise ValueError("El comprobante debe ser PDF, JPG o PNG.")

    detalle_rows_rut = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
        )
        .order_by(DeudorDetalle.id.asc())
        .all()
    )
    expediente_norm = _norm_expediente(expediente_txt)
    detalle_rows = [
        row for row in detalle_rows_rut
        if _norm_expediente(getattr(row, "nro_expediente", "")) == expediente_norm
    ]
    if not detalle_rows:
        raise ValueError("No se encontró el expediente indicado para ese deudor.")

    tipo_pago_norm = tipo_pago_txt.lower()
    detail_by_id = {int(row.id): row for row in detalle_rows_rut}
    allocation_plan: list[tuple[DeudorDetalle, int]] = []

    if distribucion:
        seen_ids: set[int] = set()
        for allocation in distribucion:
            allocation_detail_id = int(
                getattr(allocation, "detalle_id", None)
                if not isinstance(allocation, dict)
                else allocation.get("detalle_id")
            )
            allocation_amount = int(
                getattr(allocation, "monto", 0)
                if not isinstance(allocation, dict)
                else allocation.get("monto", 0)
            )
            if allocation_detail_id in seen_ids:
                raise ValueError("Un concepto no puede repetirse en la distribucion del pago.")
            row = detail_by_id.get(allocation_detail_id)
            if row is None:
                raise ValueError("La distribucion contiene un concepto que no pertenece al deudor.")
            seen_ids.add(allocation_detail_id)
            allocation_plan.append((row, allocation_amount))
        if sum(value for _, value in allocation_plan) != amount_clp:
            raise ValueError("La suma de la distribucion debe coincidir con el monto del pago.")
    elif "pago total" in tipo_pago_norm:
        saldos_por_fila = {int(row.id): int(round(_saldo_pendiente_detalle(row))) for row in detalle_rows}
        saldo_expediente = sum(saldos_por_fila.values())
        if amount_clp != saldo_expediente:
            raise ValueError("Monto no corresponde al Saldo Actual, verificar monto de pago")
        allocation_plan = [
            (row, saldos_por_fila[int(row.id)])
            for row in detalle_rows
            if saldos_por_fila[int(row.id)] > 0
        ]
    else:
        if detalle_id is not None:
            detalle_row = detail_by_id.get(int(detalle_id))
            if detalle_row is None or detalle_row not in detalle_rows:
                raise ValueError("No se encontro el monto seleccionado para registrar el abono.")
        else:
            if len(detalle_rows) > 1:
                raise ValueError("Debes seleccionar a que monto de la licencia se registrara el abono.")
            detalle_row = detalle_rows[0]
        allocation_plan = [(detalle_row, amount_clp)]

    if not allocation_plan:
        raise ValueError("El pago no tiene conceptos pendientes para distribuir.")

    allocation_snapshots: list[tuple[DeudorDetalle, int, int, int]] = []
    for row, allocation_amount in allocation_plan:
        balance_before = int(round(_saldo_pendiente_detalle(row)))
        if allocation_amount <= 0 or allocation_amount > balance_before:
            raise ValueError("La distribucion no puede superar el saldo de un concepto.")
        balance_after = balance_before - allocation_amount
        row.total_pagos = float(row.total_pagos or 0) + allocation_amount
        row.saldo_actual = float(balance_after)
        allocation_snapshots.append((row, allocation_amount, balance_before, balance_after))

    detalle_row = allocation_plan[0][0]

    estado_por_pago = "Abonado" if "abono" in tipo_pago_norm else "Cliente Sin deuda"

    copago_total, total_pagos_total, saldo_total, estado_deudor = _recalcular_resumen_desde_detalle(
        db,
        empresa=empresa_txt,
        rut_norm=rut_norm,
        estado_deudor_objetivo=estado_por_pago,
    )

    transaction = PaymentTransaction(
        public_id=str(uuid.uuid4()),
        idempotency_key=idempotency_txt,
        empresa=empresa_txt,
        rut_afiliado=rut_norm,
        payment_type=tipo_pago_txt,
        amount_clp=amount_clp,
        effective_date=effective_date,
        observations=observaciones_txt,
        registered_by_user_id=int(executor.id),
        registered_by_username=_norm_text(getattr(executor, "username", "")),
        status="confirmed",
    )
    db.add(transaction)
    db.flush()
    for row, allocation_amount, balance_before, balance_after in allocation_snapshots:
        db.add(
            PaymentAllocation(
                transaction_id=int(transaction.id),
                deudor_detalle_id=int(row.id),
                expediente=_norm_text(row.nro_expediente),
                amount_clp=allocation_amount,
                balance_before_clp=balance_before,
                balance_after_clp=balance_after,
            )
        )
    if receipt_content:
        db.add(
            PaymentReceipt(
                transaction_id=int(transaction.id),
                filename=receipt_name,
                content_type=_norm_text(comprobante_tipo) or "application/octet-stream",
                sha256=hashlib.sha256(receipt_content).hexdigest(),
                size_bytes=len(receipt_content),
                content=receipt_content,
            )
        )

    if DeudorGestion is not None:
        estado_gestion = "Abonado" if "abono" in tipo_pago_norm else "Pagado"
        nombre_gestion = nombre_txt or detalle_row.nombre_afiliado or rut_norm
        observacion_gestion = (
            f"Pago registrado | Empresa: {empresa_txt} | Expediente: {expediente_txt} | "
            f"Tipo: {tipo_pago_txt} | Monto: {amount_clp:.2f} | "
            f"Transaccion: {transaction.public_id} | Fecha efectiva: {effective_date.isoformat()}"
        )
        if observaciones_txt:
            observacion_gestion += f" | Observaciones: {observaciones_txt}"

        from datetime import datetime
        db.add(
            DeudorGestion(
                empresa=empresa_txt,
                rut_afiliado=rut_norm,
                nombre_afiliado=nombre_gestion,
                tipo_gestion="Pago",
                estado=estado_gestion,
                fecha_gestion=datetime.now().strftime("%d/%m/%Y"),
                observacion=observacion_gestion,
                origen="backend_pago",
            )
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(PaymentTransaction).filter(
            PaymentTransaction.idempotency_key == idempotency_txt
        ).first()
        if concurrent is None:
            raise
        return registrar_pago_service(
            db,
            executor=executor,
            rut=rut,
            empresa=empresa,
            expediente=expediente,
            tipo_pago=tipo_pago,
            monto=monto,
            observaciones=observaciones,
            nombre_afiliado=nombre_afiliado,
            detalle_id=detalle_id,
            fecha_efectiva=effective_date,
            idempotency_key=idempotency_txt,
            distribucion=distribucion,
            comprobante_nombre=comprobante_nombre,
            comprobante_tipo=comprobante_tipo,
            comprobante_base64=comprobante_base64,
        )

    return RegistrarPagoResponse(
        ok=True,
        empresa=empresa_txt,
        rut=rut_norm,
        expediente=expediente_txt,
        tipo_pago=tipo_pago_txt,
        monto=float(amount_clp),
        saldo_expediente=float(sum(_saldo_pendiente_detalle(row) for row in detalle_rows)),
        saldo_resumen=float(saldo_total),
        total_pagos_resumen=float(total_pagos_total),
        estado_deudor=estado_deudor,
        transaction_id=transaction.public_id,
        idempotent_replay=False,
    )



def _safe_ratio(part: float, total: float) -> float:
    try:
        total_f = float(total or 0)
        if total_f <= 0:
            return 0.0
        return (float(part or 0) / total_f) * 100.0
    except Exception:
        return 0.0


def _build_global_status(
    *,
    total_deudores: int,
    sin_gestion: int,
    gestiones_hoy: int,
    managed_pct: float,
) -> tuple[str, str]:
    if total_deudores <= 0:
        return "Sin datos", "Carga una base de deudores para activar el panel operativo."

    sin_ratio = _safe_ratio(sin_gestion, total_deudores)

    if managed_pct >= 70 and gestiones_hoy >= max(5, int(total_deudores * 0.02)):
        return "Alta", "Mantén el ritmo actual y focaliza la cartera en 'Sin Gestión' más antigua."
    if managed_pct >= 45 and sin_ratio <= 55:
        return "Media", "La cobertura es aceptable, pero conviene acelerar gestiones en cartera pendiente."
    return "Crítica", "Prioriza asignación sobre casos sin gestión y aumenta el volumen diario de contacto."


def get_dashboard_summary_service(
    db: Session,
    *,
    empresas: list[str] | None = None,
    periodo_carga: str = "",
) -> DashboardSummaryResponse:
    empresas = [str(e).strip() for e in (empresas or []) if str(e).strip()]

    resumen_base_query = db.query(DeudorResumen)
    detalle_base_query = db.query(DeudorDetalle)

    if empresas:
        resumen_base_query = resumen_base_query.filter(DeudorResumen.empresa.in_(empresas))
        detalle_base_query = detalle_base_query.filter(DeudorDetalle.empresa.in_(empresas))

    periodos_disponibles = sorted(
        [
            str(p[0]).strip()
            for p in resumen_base_query.with_entities(DeudorResumen.periodo_carga).distinct().all()
            if str(p[0] or "").strip()
        ],
        reverse=True,
    )

    periodo_txt = _norm_text(periodo_carga)
    resumen_query = resumen_base_query
    detalle_query = detalle_base_query
    if periodo_txt and periodo_txt.lower() != "acumulado":
        resumen_query = resumen_query.filter(func.trim(DeudorResumen.periodo_carga) == periodo_txt)
        detalle_query = detalle_query.filter(func.trim(DeudorDetalle.periodo_carga) == periodo_txt)

    resumen_rows = resumen_query.all()
    detalle_rows = detalle_query.all()

    estado_counts: dict[str, int] = {}
    companies_out: list[DashboardCompanyItem] = []

    total_deudores = len(resumen_rows)
    copago_total = float(sum(float(r.copago or 0) for r in resumen_rows))
    total_pagos_total = float(sum(float(r.total_pagos or 0) for r in resumen_rows))
    saldo_total = float(sum(float(r.saldo_actual or 0) for r in resumen_rows))

    for row in resumen_rows:
        estado = _norm_text(getattr(row, "estado_deudor", "")) or "Sin Gestión"
        estado_counts[estado] = int(estado_counts.get(estado, 0)) + 1

    sin_gestion_total = int(estado_counts.get("Sin Gestión", 0))
    gestionados_total = max(total_deudores - sin_gestion_total, 0)
    cobertura_pct = _safe_ratio(gestionados_total, total_deudores)
    pagos_vs_copago_pct = _safe_ratio(total_pagos_total, copago_total)
    contactados_total = int(
        sum(
            int(estado_counts.get(k, 0))
            for k in [
                "Contactado",
                "CIP Con intención de pago",
                "Promesa de pago",
                "Acuerdo de pago",
            ]
        )
    )

    tipos_hoy: dict[str, int] = {}
    gestiones_hoy = 0
    gestiones_7d = 0
    allowed_ruts = {_norm_rut(getattr(r, "rut_afiliado", "")) for r in resumen_rows if _norm_rut(getattr(r, "rut_afiliado", ""))}

    if DeudorGestion is not None:
        gest_query = db.query(DeudorGestion)
        if empresas:
            gest_query = gest_query.filter(DeudorGestion.empresa.in_(empresas))
        gest_rows = gest_query.all()

        today = __import__("datetime").datetime.now().date()
        rut_hoy = set()
        rut_7d = set()

        for row in gest_rows:
            fecha_txt = _norm_text(getattr(row, "fecha_gestion", ""))
            fecha_dt = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    fecha_dt = __import__("datetime").datetime.strptime(fecha_txt, fmt).date()
                    break
                except Exception:
                    pass
            if fecha_dt is None:
                continue

            rut_g = _norm_rut(getattr(row, "rut_afiliado", ""))
            if allowed_ruts and rut_g not in allowed_ruts:
                continue

            if fecha_dt == today:
                rut_hoy.add(rut_g)
                tipo = _norm_text(getattr(row, "tipo_gestion", "")) or "Sin tipo"
                tipos_hoy[tipo] = int(tipos_hoy.get(tipo, 0)) + 1

            if 0 <= (today - fecha_dt).days <= 6:
                rut_7d.add(rut_g)

        gestiones_hoy = len(rut_hoy)
        gestiones_7d = len(rut_7d)

    empresas_keys = empresas or sorted({str(r.empresa) for r in resumen_rows})
    for empresa in empresas_keys:
        emp_rows = [r for r in resumen_rows if _norm_text(r.empresa) == empresa]
        if not emp_rows:
            continue

        total_emp = len(emp_rows)
        copago_emp = float(sum(float(r.copago or 0) for r in emp_rows))
        pagos_emp = float(sum(float(r.total_pagos or 0) for r in emp_rows))
        saldo_emp = float(sum(float(r.saldo_actual or 0) for r in emp_rows))
        sin_gestion_emp = sum(1 for r in emp_rows if (_norm_text(r.estado_deudor) or "Sin Gestión") == "Sin Gestión")
        gestionados_emp = max(total_emp - sin_gestion_emp, 0)
        cobertura_emp = _safe_ratio(gestionados_emp, total_emp)

        if total_emp <= 0:
            status_label, status_level = "Sin base", "info"
        elif cobertura_emp >= 70:
            status_label, status_level = "Al día", "good"
        elif cobertura_emp >= 40:
            status_label, status_level = "Intermedio", "warn"
        else:
            status_label, status_level = "Pendiente", "danger"

        companies_out.append(
            DashboardCompanyItem(
                empresa=empresa,
                deudores=total_emp,
                copago=copago_emp,
                total_pagos=pagos_emp,
                saldo_actual=saldo_emp,
                sin_gestion=sin_gestion_emp,
                gestionados=gestionados_emp,
                cobertura_pct=cobertura_emp,
                status_label=status_label,
                status_level=status_level,
                freshness=(periodo_txt or "Acumulado") if periodo_txt else "Acumulado",
            )
        )

    health_label, focus_text = _build_global_status(
        total_deudores=total_deudores,
        sin_gestion=sin_gestion_total,
        gestiones_hoy=gestiones_hoy,
        managed_pct=cobertura_pct,
    )

    return DashboardSummaryResponse(
        periodo_carga=periodo_txt,
        periodos_disponibles=periodos_disponibles,
        total_deudores=total_deudores,
        copago_total=copago_total,
        total_pagos_total=total_pagos_total,
        saldo_total=saldo_total,
        sin_gestion_total=sin_gestion_total,
        gestionados_total=gestionados_total,
        cobertura_pct=cobertura_pct,
        pagos_vs_copago_pct=pagos_vs_copago_pct,
        contactados_total=contactados_total,
        gestiones_hoy=gestiones_hoy,
        gestiones_7d=gestiones_7d,
        estado_counts=estado_counts,
        tipos_hoy=dict(sorted(tipos_hoy.items(), key=lambda kv: kv[1], reverse=True)[:5]),
        health_label=health_label,
        focus_text=focus_text,
        companies=companies_out,
    )


def revertir_pago_backend_service(
    db: Session,
    *,
    rut: str,
    empresa: str,
    expediente: str,
    monto: float,
) -> tuple[float, float, float, str]:
    empresa_txt = _norm_text(empresa)
    expediente_txt = _norm_text(expediente)
    rut_norm = _norm_rut(rut)
    monto_val = float(monto or 0)

    if not empresa_txt:
        raise ValueError("Debes indicar la empresa.")
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")
    if not expediente_txt:
        raise ValueError("Debes indicar el expediente.")
    if monto_val <= 0:
        raise ValueError("El monto a revertir debe ser mayor a 0.")

    detalle_row = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_norm,
            func.trim(DeudorDetalle.nro_expediente) == expediente_txt,
        )
        .order_by(DeudorDetalle.id.asc())
        .first()
    )
    if not detalle_row:
        raise ValueError("No se encontró el expediente indicado para revertir el pago.")

    total_pagos_detalle = float(detalle_row.total_pagos or 0)
    saldo_actual_detalle = float(detalle_row.saldo_actual or 0)
    copago_detalle = float(detalle_row.copago or 0)

    detalle_row.total_pagos = max(0.0, total_pagos_detalle - monto_val)
    detalle_row.saldo_actual = min(copago_detalle, max(0.0, saldo_actual_detalle + monto_val))

    copago_total, total_pagos_total, saldo_total, estado_deudor = _recalcular_resumen_desde_detalle(
        db,
        empresa=empresa_txt,
        rut_norm=rut_norm,
        estado_deudor_objetivo=None,
    )

    db.commit()
    return copago_total, total_pagos_total, saldo_total, estado_deudor




def reverse_payment_transaction_service(
    db: Session,
    *,
    transaction_public_id: str,
    executor: User,
    reason: str = "",
) -> tuple[float, float, float, str]:
    require_supervisor(executor, action="revertir un pago")
    transaction = db.query(PaymentTransaction).filter(
        PaymentTransaction.public_id == _norm_text(transaction_public_id)
    ).first()
    if not transaction:
        raise ValueError("La transaccion de pago no existe.")
    if transaction.status != "confirmed":
        raise ValueError("La transaccion ya fue revertida o no se encuentra confirmada.")

    allocations = db.query(PaymentAllocation).filter(
        PaymentAllocation.transaction_id == int(transaction.id)
    ).all()
    if not allocations:
        raise ValueError("La transaccion no contiene una distribucion recuperable.")

    for allocation in allocations:
        detail = db.query(DeudorDetalle).filter(
            DeudorDetalle.id == int(allocation.deudor_detalle_id)
        ).first()
        if not detail:
            raise ValueError("No se encontro uno de los conceptos asociados al pago.")
        current_paid = int(round(float(detail.total_pagos or 0)))
        allocation_amount = int(allocation.amount_clp)
        if current_paid < allocation_amount:
            raise ValueError(
                "El pago no puede revertirse porque los saldos fueron modificados de forma incompatible."
            )
        detail.total_pagos = float(current_paid - allocation_amount)
        detail.saldo_actual = float(
            min(
                int(round(float(detail.copago or 0))),
                int(round(float(detail.saldo_actual or 0))) + allocation_amount,
            )
        )

    transaction.status = "reversed"
    db.add(transaction)
    db.add(
        PaymentReversal(
            transaction_id=int(transaction.id),
            reason=_norm_text(reason) or "Reversa solicitada desde el historial de gestiones.",
            reversed_by_user_id=int(executor.id),
            reversed_by_username=_norm_text(getattr(executor, "username", "")),
        )
    )
    result = _recalcular_resumen_desde_detalle(
        db,
        empresa=transaction.empresa,
        rut_norm=transaction.rut_afiliado,
        estado_deudor_objetivo=None,
    )
    db.commit()
    return result


def update_deudor_cliente_service(
    db: Session,
    *,
    executor: User,
    rut: str,
    empresa: str,
    rut_nuevo: str,
    nombre: str,
    correo: str = "",
    correo_excel: str = "",
    telefono_fijo: str = "",
    telefono_movil: str = "",
    direccion: str = "",
    comuna: str = "",
    ciudad: str = "",
) -> ActualizarClienteResponse:
    empresa_txt = _norm_text(empresa)
    rut_original = _norm_rut(rut)
    rut_actualizado = _norm_rut(rut_nuevo)

    if not empresa_txt:
        raise ValueError("Debes indicar la empresa.")
    if not rut_original:
        raise ValueError("Debes indicar un RUT válido.")
    if not rut_actualizado:
        raise ValueError("El RUT actualizado no puede quedar vacío.")
    if not _norm_text(nombre):
        raise ValueError("El nombre no puede quedar vacío.")

    resumen_rows = (
        db.query(DeudorResumen)
        .filter(
            func.trim(DeudorResumen.empresa) == empresa_txt,
            _rut_db_expr(DeudorResumen.rut_afiliado) == rut_original,
        )
        .all()
    )

    detalle_rows = (
        db.query(DeudorDetalle)
        .filter(
            func.trim(DeudorDetalle.empresa) == empresa_txt,
            _rut_db_expr(DeudorDetalle.rut_afiliado) == rut_original,
        )
        .all()
    )

    if not resumen_rows and not detalle_rows:
        raise ValueError("No se encontró el cliente para actualizar.")

    resumen_fuente = resumen_rows[0] if resumen_rows else None
    detalle_fuente = detalle_rows[0] if detalle_rows else None
    old_values = {
        "rut": _norm_text(getattr(resumen_fuente or detalle_fuente, "rut_completo", "")),
        "nombre": _norm_text(getattr(resumen_fuente or detalle_fuente, "nombre_afiliado", "")),
        "correo": _norm_text(getattr(detalle_fuente, "mail_afiliado", "")),
        "correo_excel": _norm_text(getattr(detalle_fuente or resumen_fuente, "bn", "")),
        "telefono_fijo": _norm_text(getattr(detalle_fuente, "telefono_fijo_afiliado", "")),
        "telefono_movil": _norm_text(getattr(detalle_fuente, "telefono_movil_afiliado", "")),
        "direccion": _norm_text(getattr(detalle_fuente, "direccion_deudor", "")),
        "comuna": _norm_text(getattr(detalle_fuente, "comuna_deudor", "")),
        "ciudad": _norm_text(getattr(detalle_fuente, "ciudad_deudor", "")),
    }

    if "-" in str(rut_nuevo):
        partes = str(rut_nuevo).replace(".", "").split("-", 1)
        rut_actualizado = _norm_rut(partes[0])
        dv_nuevo = _norm_text(partes[1]).upper()
    else:
        fuente = resumen_rows[0] if resumen_rows else detalle_rows[0]
        dv_nuevo = _norm_text(getattr(fuente, "dv", "")).upper()

    rut_completo_nuevo = f"{rut_actualizado}-{dv_nuevo}" if dv_nuevo else rut_actualizado

    nombre_txt = _norm_text(nombre)
    correo_txt = _norm_text(correo)
    correo_excel_txt = _norm_text(correo_excel)
    telefono_fijo_txt = _norm_text(telefono_fijo)
    telefono_movil_txt = _norm_text(telefono_movil)
    direccion_txt = _norm_text(direccion)
    comuna_txt = _norm_text(comuna)
    ciudad_txt = _norm_text(ciudad)
    new_values = {
        "rut": rut_completo_nuevo,
        "nombre": nombre_txt,
        "correo": correo_txt,
        "correo_excel": correo_excel_txt,
        "telefono_fijo": telefono_fijo_txt,
        "telefono_movil": telefono_movil_txt,
        "direccion": direccion_txt,
        "comuna": comuna_txt,
        "ciudad": ciudad_txt,
    }

    for row in resumen_rows:
        row.rut_afiliado = rut_actualizado
        row.dv = dv_nuevo
        row.rut_completo = rut_completo_nuevo
        row.nombre_afiliado = nombre_txt
        row.bn = correo_excel_txt

    for row in detalle_rows:
        row.rut_afiliado = rut_actualizado
        row.dv = dv_nuevo
        row.rut_completo = rut_completo_nuevo
        row.nombre_afiliado = nombre_txt
        row.mail_afiliado = correo_txt
        row.bn = correo_excel_txt
        row.telefono_fijo_afiliado = telefono_fijo_txt
        row.telefono_movil_afiliado = telefono_movil_txt
        row.direccion_deudor = direccion_txt
        row.comuna_deudor = comuna_txt
        row.ciudad_deudor = ciudad_txt

    if DeudorGestion is not None:
        gestion_rows = (
            db.query(DeudorGestion)
            .filter(
                func.trim(DeudorGestion.empresa) == empresa_txt,
                _rut_db_expr(DeudorGestion.rut_afiliado) == rut_original,
            )
            .all()
        )
        for row in gestion_rows:
            row.rut_afiliado = rut_actualizado
            row.nombre_afiliado = nombre_txt

    changed_fields: list[str] = []
    for field_name, new_value in new_values.items():
        old_value = old_values.get(field_name, "")
        if old_value == new_value:
            continue
        changed_fields.append(field_name)
        db.add(
            CustomerChangeAudit(
                empresa=empresa_txt,
                rut_original=rut_original,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                changed_by_user_id=int(executor.id),
                changed_by_username=_norm_text(getattr(executor, "username", "")),
            )
        )

    owner_user_id = assigned_user_id_for_company(db, empresa_txt)
    if changed_fields and owner_user_id is not None and int(owner_user_id) != int(executor.id):
        create_notification(
            db,
            user_id=owner_user_id,
            notification_type="customer_data_changed",
            title="Datos de cliente actualizados",
            message=(
                f"{_norm_text(getattr(executor, 'username', 'Otro usuario'))} modifico "
                f"{', '.join(changed_fields)} del RUT {rut_original}."
            ),
            empresa=empresa_txt,
            rut_afiliado=rut_actualizado,
            related_entity_type="customer",
        )

    db.commit()

    return ActualizarClienteResponse(
        ok=True,
        empresa=empresa_txt,
        rut_original=rut_original,
        rut_actualizado=rut_completo_nuevo,
        nombre_afiliado=nombre_txt,
        mail_afiliado=correo_txt,
        bn=correo_excel_txt,
        telefono_fijo_afiliado=telefono_fijo_txt,
        telefono_movil_afiliado=telefono_movil_txt,
        direccion_deudor=direccion_txt,
        comuna_deudor=comuna_txt,
        ciudad_deudor=ciudad_txt,
    )


