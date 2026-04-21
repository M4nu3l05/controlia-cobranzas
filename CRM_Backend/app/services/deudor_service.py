from __future__ import annotations

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.models.deudor import DeudorDetalle, DeudorResumen
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
    return str(value or "").strip()


def _norm_rut(value: str) -> str:
    txt = _norm_text(value).replace(".", "")
    if "-" in txt:
        txt = txt.split("-", 1)[0]
    return txt.replace("-", "").lstrip("0")


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
        empresa=row.empresa,
        rut_afiliado=row.rut_afiliado,
        dv=row.dv,
        rut_completo=row.rut_completo,
        nombre_afiliado=row.nombre_afiliado,
        mail_afiliado=row.mail_afiliado,
        bn=row.bn,
        telefono_fijo_afiliado=row.telefono_fijo_afiliado,
        telefono_movil_afiliado=row.telefono_movil_afiliado,
        nro_expediente=row.nro_expediente,
        fecha_emision=row.fecha_emision,
        copago=float(row.copago or 0),
        total_pagos=float(row.total_pagos or 0),
        saldo_actual=float(row.saldo_actual or 0),
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
) -> list[DestinatarioItem]:
    empresa_txt = _norm_text(empresa)
    periodo_txt = _norm_text(periodo_carga)

    resumen_q = db.query(DeudorResumen)
    detalle_q = db.query(DeudorDetalle)

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
    rut: str,
    empresa: str,
    expediente: str,
    tipo_pago: str,
    monto: float,
    observaciones: str = "",
    nombre_afiliado: str = "",
) -> RegistrarPagoResponse:
    empresa_txt = _norm_text(empresa)
    expediente_txt = _norm_text(expediente)
    tipo_pago_txt = _norm_text(tipo_pago)
    observaciones_txt = _norm_text(observaciones)
    nombre_txt = _norm_text(nombre_afiliado)
    rut_norm = _norm_rut(rut)

    if not empresa_txt:
        raise ValueError("Debes indicar la empresa.")
    if not rut_norm:
        raise ValueError("Debes indicar un RUT válido.")
    if not expediente_txt:
        raise ValueError("Debes indicar el expediente.")
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a 0.")

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
        raise ValueError("No se encontró el expediente indicado para ese deudor.")

    saldo_actual_detalle = float(detalle_row.saldo_actual or 0)
    total_pagos_detalle = float(detalle_row.total_pagos or 0)

    if monto - saldo_actual_detalle > 1:
        raise ValueError("Monto no corresponde al Saldo Actual, verificar monto de pago")

    if "pago total" in tipo_pago_txt.lower() and abs(monto - saldo_actual_detalle) > 1:
        raise ValueError("Monto no corresponde al Saldo Actual, verificar monto de pago")

    detalle_row.total_pagos = total_pagos_detalle + float(monto)
    detalle_row.saldo_actual = max(0.0, saldo_actual_detalle - float(monto))

    tipo_pago_norm = tipo_pago_txt.lower()
    estado_por_pago = "Abonado" if "abono" in tipo_pago_norm else "Pagado"

    copago_total, total_pagos_total, saldo_total, estado_deudor = _recalcular_resumen_desde_detalle(
        db,
        empresa=empresa_txt,
        rut_norm=rut_norm,
        estado_deudor_objetivo=estado_por_pago,
    )

    if DeudorGestion is not None:
        estado_gestion = "Abonado" if "abono" in tipo_pago_norm else "Pagado"
        nombre_gestion = nombre_txt or detalle_row.nombre_afiliado or rut_norm
        observacion_gestion = (
            f"Pago registrado | Empresa: {empresa_txt} | Expediente: {expediente_txt} | "
            f"Tipo: {tipo_pago_txt} | Monto: {float(monto):.2f}"
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

    db.commit()

    return RegistrarPagoResponse(
        ok=True,
        empresa=empresa_txt,
        rut=rut_norm,
        expediente=expediente_txt,
        tipo_pago=tipo_pago_txt,
        monto=float(monto),
        saldo_expediente=float(detalle_row.saldo_actual or 0),
        saldo_resumen=float(saldo_total),
        total_pagos_resumen=float(total_pagos_total),
        estado_deudor=estado_deudor,
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




def update_deudor_cliente_service(
    db: Session,
    *,
    rut: str,
    empresa: str,
    rut_nuevo: str,
    nombre: str,
    correo: str = "",
    correo_excel: str = "",
    telefono_fijo: str = "",
    telefono_movil: str = "",
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
    )


