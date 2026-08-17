from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationError, is_privileged_operator
from app.models.commission import CommissionRate, CommissionReset
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.schemas.commission import (
    CommissionCompanyBreakdown,
    CommissionRateItem,
    CommissionSummaryItem,
)


def _company_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _rate_map(db: Session) -> dict[str, float]:
    return {
        _company_key(row.empresa): float(row.percent or 0)
        for row in db.query(CommissionRate).all()
    }


def _rate_items(db: Session) -> list[CommissionRateItem]:
    rows = db.query(CommissionRate).order_by(CommissionRate.empresa).all()
    return [
        CommissionRateItem(
            empresa=str(row.empresa or "").strip(),
            percent=float(row.percent or 0),
            updated_at=row.updated_at,
            updated_by_username=str(row.updated_by_username or ""),
        )
        for row in rows
    ]


def list_commission_rates_service(db: Session, *, executor: User) -> list[CommissionRateItem]:
    if executor is None:
        raise AuthorizationError("Sesion invalida.")
    return _rate_items(db)


def save_commission_rates_service(
    db: Session,
    *,
    executor: User,
    rates: list[dict],
) -> list[CommissionRateItem]:
    if not is_privileged_operator(executor):
        raise AuthorizationError("Solo un supervisor puede definir los porcentajes de comision.")

    existing = {_company_key(row.empresa): row for row in db.query(CommissionRate).all()}

    for item in rates or []:
        empresa = str(item.get("empresa", "") or "").strip()
        if not empresa:
            continue
        percent = float(item.get("percent", 0) or 0)
        if percent < 0 or percent > 100:
            raise AuthorizationError("El porcentaje de comision debe estar entre 0 y 100.")

        row = existing.get(_company_key(empresa))
        if row is None:
            row = CommissionRate(empresa=empresa)
            db.add(row)
            existing[_company_key(empresa)] = row
        row.empresa = empresa
        row.percent = percent
        row.updated_by_user_id = int(executor.id)
        row.updated_by_username = str(executor.username or "")
        row.updated_at = func.now()

    db.commit()
    return _rate_items(db)


def _cutoffs(db: Session) -> tuple[datetime | None, dict[int, datetime]]:
    """Devuelve el corte global y los cortes por ejecutiva."""
    global_cutoff: datetime | None = None
    per_user: dict[int, datetime] = {}
    for row in db.query(CommissionReset).all():
        effective_at = row.effective_at
        if effective_at is None:
            continue
        if row.scope_user_id is None:
            if global_cutoff is None or effective_at > global_cutoff:
                global_cutoff = effective_at
        else:
            user_id = int(row.scope_user_id)
            if user_id not in per_user or effective_at > per_user[user_id]:
                per_user[user_id] = effective_at
    return global_cutoff, per_user


def _cutoff_for(user_id: int, global_cutoff: datetime | None, per_user: dict[int, datetime]) -> datetime | None:
    personal = per_user.get(int(user_id))
    if global_cutoff is None:
        return personal
    if personal is None:
        return global_cutoff
    return max(global_cutoff, personal)


def build_commission_summary(
    db: Session,
    *,
    user_ids: list[int],
) -> list[CommissionSummaryItem]:
    """Acumula comisiones por ejecutiva a partir del libro de pagos confirmados."""
    if not user_ids:
        return []

    rates = _rate_map(db)
    global_cutoff, per_user_cutoff = _cutoffs(db)

    users = db.query(User).filter(User.id.in_([int(uid) for uid in user_ids])).all()
    users_by_id = {int(user.id): user for user in users}

    transactions = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.status == "confirmed",
            PaymentTransaction.registered_by_user_id.in_([int(uid) for uid in user_ids]),
        )
        .all()
    )

    acumulado: dict[int, dict[str, dict]] = {int(uid): {} for uid in user_ids}
    for tx in transactions:
        user_id = int(tx.registered_by_user_id)
        if user_id not in acumulado:
            continue
        cutoff = _cutoff_for(user_id, global_cutoff, per_user_cutoff)
        registered_at = tx.registered_at
        if cutoff is not None and registered_at is not None and registered_at <= cutoff:
            continue

        empresa = str(tx.empresa or "").strip()
        percent = rates.get(_company_key(empresa), 0.0)
        monto = int(tx.amount_clp or 0)
        comision = int(round(monto * percent / 100.0))

        bucket = acumulado[user_id].setdefault(
            _company_key(empresa),
            {"empresa": empresa, "percent": percent, "pagos": 0, "monto": 0, "comision": 0},
        )
        bucket["empresa"] = empresa or bucket["empresa"]
        bucket["percent"] = percent
        bucket["pagos"] += 1
        bucket["monto"] += monto
        bucket["comision"] += comision

    salida: list[CommissionSummaryItem] = []
    for user_id in user_ids:
        user = users_by_id.get(int(user_id))
        if user is None:
            continue
        detalle_raw = sorted(acumulado.get(int(user_id), {}).values(), key=lambda item: item["empresa"].lower())
        detalle = [
            CommissionCompanyBreakdown(
                empresa=item["empresa"],
                percent=float(item["percent"]),
                pagos=int(item["pagos"]),
                monto_pagado_clp=int(item["monto"]),
                comision_clp=int(item["comision"]),
            )
            for item in detalle_raw
        ]
        salida.append(
            CommissionSummaryItem(
                user_id=int(user.id),
                username=str(user.username or ""),
                email=str(user.email or ""),
                pagos=sum(item.pagos for item in detalle),
                monto_pagado_clp=sum(item.monto_pagado_clp for item in detalle),
                comision_clp=sum(item.comision_clp for item in detalle),
                desde=_cutoff_for(int(user.id), global_cutoff, per_user_cutoff),
                detalle=detalle,
            )
        )

    salida.sort(key=lambda item: (-item.comision_clp, item.username.lower()))
    return salida


def commission_summary_service(db: Session, *, executor: User) -> list[CommissionSummaryItem]:
    if executor is None:
        raise AuthorizationError("Sesion invalida.")

    if is_privileged_operator(executor):
        user_ids = [
            int(row.id)
            for row in db.query(User).filter(User.role == "ejecutivo", User.is_active.is_(True)).all()
        ]
    else:
        user_ids = [int(executor.id)]

    return build_commission_summary(db, user_ids=user_ids)


def reset_commissions_service(
    db: Session,
    *,
    executor: User,
    user_id: int | None,
    note: str = "",
) -> list[CommissionSummaryItem]:
    if not is_privileged_operator(executor):
        raise AuthorizationError("Solo un supervisor puede reestablecer las comisiones.")

    objetivos = [int(user_id)] if user_id is not None else [
        int(row.id)
        for row in db.query(User).filter(User.role == "ejecutivo", User.is_active.is_(True)).all()
    ]
    # El corte se guarda con el acumulado alcanzado para dejar trazabilidad del pago.
    previos = {item.user_id: item for item in build_commission_summary(db, user_ids=objetivos)}

    # `registered_at` de los pagos usa el reloj del motor de base de datos, asi que
    # el corte tambien se resuelve alli para que la comparacion sea homogenea.
    effective_at = func.now()
    if user_id is None:
        db.add(
            CommissionReset(
                scope_user_id=None,
                effective_at=effective_at,
                total_paid_clp=sum(item.monto_pagado_clp for item in previos.values()),
                total_commission_clp=sum(item.comision_clp for item in previos.values()),
                note=str(note or "").strip(),
                created_by_user_id=int(executor.id),
                created_by_username=str(executor.username or ""),
            )
        )
    else:
        previo = previos.get(int(user_id))
        db.add(
            CommissionReset(
                scope_user_id=int(user_id),
                effective_at=effective_at,
                total_paid_clp=int(previo.monto_pagado_clp) if previo else 0,
                total_commission_clp=int(previo.comision_clp) if previo else 0,
                note=str(note or "").strip(),
                created_by_user_id=int(executor.id),
                created_by_username=str(executor.username or ""),
            )
        )

    db.commit()
    return commission_summary_service(db, executor=executor)
