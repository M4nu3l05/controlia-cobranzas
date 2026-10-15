from __future__ import annotations

from collections import Counter, defaultdict
from io import BytesIO
import hashlib
import os
import re
import unicodedata

import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.deudor import DeudorResumen
from app.models.debtor_assignment import (
    DebtorAssignmentAlias,
    DebtorAssignmentAudit,
    DebtorUserAssignment,
)
from app.models.user import User
from app.models.deudor import DeudorDetalle
from app.core.authorization import primary_user_id_for_company


def normalize_assignment_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _header_key(value: object) -> str:
    return normalize_assignment_name(value).replace(" ", "")


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\u00a0", " ").strip()
    return "" if text.casefold() in {"", "nan", "none", "nat"} else re.sub(r"\s+", " ", text)


def normalize_assignment_rut(value: object) -> str:
    text = _clean_text(value).replace(".", "").replace(" ", "").upper()
    if "-" in text:
        text = text.rsplit("-", 1)[0]
    return "".join(char for char in text if char.isdigit()).lstrip("0")


def user_has_debtor_assignments(db: Session, user_id: int) -> bool:
    if not inspect(db.connection()).has_table("debtor_user_assignments"):
        return False
    return db.query(DebtorUserAssignment.id).filter(
        DebtorUserAssignment.user_id == int(user_id)
    ).first() is not None


def _find_column(columns: list[object], candidates: set[str]) -> str:
    for column in columns:
        if _header_key(column) in candidates:
            return str(column)
    return ""


def _read_assignment_dataframe(content: bytes) -> tuple[pd.DataFrame, str, str, str]:
    if not content:
        raise ValueError("El archivo recibido está vacío.")
    xls = pd.ExcelFile(BytesIO(content))
    rut_candidates = {
        "rutafiliado", "rutdeudor", "rut", "rutemp", "rutempleador", "rutempresa"
    }
    owner_candidates = {
        "ejecutiva", "ejecutivo", "ejecutivaasignada", "ejecutivoasignado", "asignadaa"
    }
    for sheet_name in xls.sheet_names:
        frame = pd.read_excel(BytesIO(content), sheet_name=sheet_name, dtype=str).fillna("")
        rut_column = _find_column(list(frame.columns), rut_candidates)
        owner_column = _find_column(list(frame.columns), owner_candidates)
        if rut_column and owner_column:
            return frame, str(sheet_name), rut_column, owner_column
    raise ValueError(
        "No se encontraron en una misma hoja las columnas de RUT y Ejecutiva. "
        "Se aceptan, por ejemplo, 'Rut_Afiliado' y 'Ejecutiva'."
    )


def _assignment_source(content: bytes) -> dict:
    frame, sheet_name, rut_column, owner_column = _read_assignment_dataframe(content)
    label_rows: Counter[str] = Counter()
    label_display: dict[str, str] = {}
    label_debtors: dict[str, set[str]] = defaultdict(set)
    labels_by_rut: dict[str, set[str]] = defaultdict(set)
    raw_label_by_rut: dict[tuple[str, str], str] = {}
    blank_debtors: set[str] = set()
    blank_assignments = 0
    valid_rows = 0

    for _, row in frame.iterrows():
        rut = normalize_assignment_rut(row.get(rut_column, ""))
        if not rut:
            continue
        valid_rows += 1
        raw_label = _clean_text(row.get(owner_column, ""))
        normalized_label = normalize_assignment_name(raw_label)
        if not normalized_label:
            blank_assignments += 1
            blank_debtors.add(rut)
            continue
        label_rows[normalized_label] += 1
        label_display.setdefault(normalized_label, raw_label)
        label_debtors[normalized_label].add(rut)
        labels_by_rut[rut].add(normalized_label)
        raw_label_by_rut[(rut, normalized_label)] = raw_label

    conflicts = {rut: labels for rut, labels in labels_by_rut.items() if len(labels) > 1}
    return {
        "sheet_name": sheet_name,
        "valid_rows": valid_rows,
        "blank_assignments": blank_assignments,
        "label_rows": label_rows,
        "label_display": label_display,
        "label_debtors": label_debtors,
        "labels_by_rut": labels_by_rut,
        "raw_label_by_rut": raw_label_by_rut,
        "blank_debtors": blank_debtors,
        "conflicts": conflicts,
    }


def _active_supervisors(db: Session) -> tuple[dict[int, User], dict[str, list[User]]]:
    users = (
        db.query(User)
        .filter(User.role == "supervisor", User.is_active.is_(True))
        .order_by(User.id.asc())
        .all()
    )
    by_id = {int(user.id): user for user in users}
    by_name: dict[str, list[User]] = defaultdict(list)
    for user in users:
        by_name[normalize_assignment_name(user.username)].append(user)
    return by_id, by_name


def _resolve_labels(
    db: Session,
    *,
    empresa: str,
    source: dict,
    overrides: dict[str, int] | None = None,
) -> tuple[dict[str, User], list[dict]]:
    users_by_id, users_by_name = _active_supervisors(db)
    alias_rows = db.query(DebtorAssignmentAlias).filter(
        DebtorAssignmentAlias.empresa == empresa
    ).all()
    aliases = {row.normalized_label: int(row.user_id) for row in alias_rows}
    normalized_overrides = {
        normalize_assignment_name(label): int(user_id or 0)
        for label, user_id in (overrides or {}).items()
        if normalize_assignment_name(label)
    }

    resolved: dict[str, User] = {}
    matches: list[dict] = []
    for normalized_label in sorted(source["label_rows"]):
        status = "unmatched"
        user = None
        override_id = normalized_overrides.get(normalized_label)
        alias_id = aliases.get(normalized_label)
        if override_id is not None:
            if override_id <= 0:
                status = "invalid_user"
            else:
                user = users_by_id.get(override_id)
                status = "matched_override" if user else "invalid_user"
        elif alias_id is not None:
            user = users_by_id.get(alias_id)
            status = "matched_alias" if user else "inactive_alias"
        else:
            candidates = users_by_name.get(normalized_label, [])
            if len(candidates) == 1:
                user = candidates[0]
                status = "matched"
            elif len(candidates) > 1:
                status = "ambiguous"
        if user is not None:
            resolved[normalized_label] = user
        matches.append({
            "source_label": source["label_display"].get(normalized_label, ""),
            "normalized_label": normalized_label,
            "row_count": int(source["label_rows"][normalized_label]),
            "debtor_count": len(source["label_debtors"][normalized_label]),
            "user_id": int(user.id) if user is not None else None,
            "username": str(user.username or "") if user is not None else "",
            "status": status,
        })
    return resolved, matches


def preview_debtor_assignments_service(
    db: Session,
    *,
    empresa: str,
    content: bytes,
    source_file: str,
) -> dict:
    empresa_txt = _clean_text(empresa)
    source = _assignment_source(content)
    _, matches = _resolve_labels(db, empresa=empresa_txt, source=source)
    source_ruts = set(source["labels_by_rut"]) | set(source["blank_debtors"])
    existing_ruts = {
        normalize_assignment_rut(rut)
        for (rut,) in db.query(DeudorResumen.rut_afiliado).filter(
            DeudorResumen.empresa == empresa_txt
        ).all()
    }
    primary_user_id = primary_user_id_for_company(db, empresa_txt)
    primary_user = db.query(User).filter(User.id == primary_user_id).first() if primary_user_id else None
    if primary_user is not None and (
        str(primary_user.role or "").strip().lower() != "supervisor"
        or not bool(primary_user.is_active)
    ):
        primary_user = None
    if source["blank_debtors"] and primary_user is None:
        raise ValueError(
            f"La cartera '{empresa_txt}' tiene filas con Ejecutiva vacía y no posee un Supervisor titular activo."
        )
    return {
        "empresa": empresa_txt,
        "source_file": os.path.basename(source_file),
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "sheet_name": source["sheet_name"],
        "total_rows": int(source["valid_rows"]),
        "unique_debtors": len(source_ruts),
        "existing_debtors": len(source_ruts & existing_ruts),
        "missing_debtors": len(source_ruts - existing_ruts),
        "blank_assignments": int(source["blank_assignments"]),
        "blank_default_user_id": int(primary_user.id) if primary_user is not None else None,
        "blank_default_username": str(primary_user.username or "") if primary_user is not None else "",
        "conflicting_debtors": len(source["conflicts"]),
        "unresolved_labels": sum(1 for item in matches if item["user_id"] is None),
        "matches": matches,
    }


def apply_debtor_assignments_service(
    db: Session,
    *,
    empresa: str,
    content: bytes,
    source_file: str,
    executor: User,
    expected_file_sha256: str,
    overrides: dict[str, int] | None = None,
    commit: bool = True,
) -> dict:
    empresa_txt = _clean_text(empresa)
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != _clean_text(expected_file_sha256).lower():
        raise ValueError("El archivo cambió después de la vista previa. Debes revisarlo nuevamente.")

    source = _assignment_source(content)
    if source["conflicts"]:
        raise ValueError(
            f"Hay {len(source['conflicts'])} RUT con más de una ejecutiva. La distribución no fue aplicada."
        )

    resolved, matches = _resolve_labels(
        db, empresa=empresa_txt, source=source, overrides=overrides
    )
    if any(item["status"] == "invalid_user" for item in matches):
        raise ValueError(
            "La relación manual contiene un usuario inexistente, inactivo o sin rol Supervisor."
        )
    unresolved = [item for item in matches if item["user_id"] is None]
    if unresolved:
        labels = ", ".join(str(item["source_label"] or "") for item in unresolved[:5])
        raise ValueError(
            "Todos los nombres de la columna Ejecutiva deben relacionarse con un Supervisor activo. "
            f"Pendientes: {labels}."
        )

    blank_user = None
    if source["blank_debtors"]:
        primary_user_id = primary_user_id_for_company(db, empresa_txt)
        blank_user = db.query(User).filter(User.id == primary_user_id).first() if primary_user_id else None
        if blank_user is None or str(blank_user.role or "").strip().lower() != "supervisor" or not bool(blank_user.is_active):
            raise ValueError(
                f"La cartera '{empresa_txt}' tiene filas con Ejecutiva vacía y no posee un Supervisor titular activo."
            )
    existing_ruts = {
        normalize_assignment_rut(rut)
        for (rut,) in db.query(DeudorResumen.rut_afiliado).filter(
            DeudorResumen.empresa == empresa_txt
        ).all()
    }
    current_rows = db.query(DebtorUserAssignment).filter(
        DebtorUserAssignment.empresa == empresa_txt
    ).all()
    current = {normalize_assignment_rut(row.rut_afiliado): row for row in current_rows}

    assigned = reassigned = unchanged = missing = 0
    source_ruts = set(source["labels_by_rut"]) | set(source["blank_debtors"])
    for rut in source_ruts:
        if rut not in existing_ruts:
            missing += 1
            continue
        labels = source["labels_by_rut"].get(rut, set())
        normalized_label = next(iter(labels)) if labels else ""
        user = resolved.get(normalized_label) if normalized_label else blank_user
        if user is None:
            raise ValueError(f"No fue posible determinar la Ejecutiva responsable del RUT {rut}.")
        raw_label = source["raw_label_by_rut"].get((rut, normalized_label), "")
        row = current.get(rut)
        previous_user_id = int(row.user_id) if row is not None else None
        if row is None:
            row = DebtorUserAssignment(
                empresa=empresa_txt,
                rut_afiliado=rut,
                user_id=int(user.id),
                assigned_by_user_id=int(executor.id),
            )
            db.add(row)
            current[rut] = row
            assigned += 1
        elif previous_user_id == int(user.id):
            unchanged += 1
        else:
            row.user_id = int(user.id)
            row.assigned_by_user_id = int(executor.id)
            reassigned += 1
        row.source_label = raw_label
        row.normalized_label = normalized_label
        row.source_file = os.path.basename(source_file)
        row.source_hash = actual_hash
        db.query(DeudorResumen).filter(
            DeudorResumen.empresa == empresa_txt,
            DeudorResumen.rut_afiliado == rut,
        ).update({"ejecutivo_asignado": str(user.username or "").strip()}, synchronize_session=False)
        db.query(DeudorDetalle).filter(
            DeudorDetalle.empresa == empresa_txt,
            DeudorDetalle.rut_afiliado == rut,
        ).update({"ejecutivo_asignado": str(user.username or "").strip()}, synchronize_session=False)
        if previous_user_id != int(user.id):
            db.add(DebtorAssignmentAudit(
                empresa=empresa_txt,
                rut_afiliado=rut,
                previous_user_id=previous_user_id,
                new_user_id=int(user.id),
                source_label=raw_label,
                source_file=os.path.basename(source_file),
                changed_by_user_id=int(executor.id),
            ))

    alias_count = 0
    aliases = {
        row.normalized_label: row
        for row in db.query(DebtorAssignmentAlias).filter(
            DebtorAssignmentAlias.empresa == empresa_txt
        ).all()
    }
    for normalized_label, user in resolved.items():
        alias = aliases.get(normalized_label)
        source_label = source["label_display"].get(normalized_label, "")
        if alias is None:
            alias = DebtorAssignmentAlias(
                empresa=empresa_txt,
                normalized_label=normalized_label,
                source_label=source_label,
                user_id=int(user.id),
                created_by_user_id=int(executor.id),
            )
            db.add(alias)
            alias_count += 1
        elif int(alias.user_id) != int(user.id) or alias.source_label != source_label:
            alias.user_id = int(user.id)
            alias.source_label = source_label
            alias.created_by_user_id = int(executor.id)
            alias_count += 1

    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "empresa": empresa_txt,
        "source_file": os.path.basename(source_file),
        "processed_debtors": len(source_ruts),
        "assigned_debtors": assigned,
        "reassigned_debtors": reassigned,
        "unchanged_debtors": unchanged,
        "unassigned_debtors": 0,
        "missing_debtors": missing,
        "aliases_saved": alias_count,
    }
