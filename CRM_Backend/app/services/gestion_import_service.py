from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from sqlalchemy.orm import Session

from app.models.deudor import DeudorResumen
from app.models.gestion import DeudorGestion
from app.services.gestion_service import (
    normalizar_fecha_gestion_iso,
    recalcular_estados_deudores_lote,
)


SHEETS = {"SMS": "SMS", "Email": "Email", "Carta": "Carta"}


def _norm_text(value: object) -> str:
    return str(value or "").strip()


def _norm_header(value: object) -> str:
    return "".join(ch for ch in _norm_text(value).lower() if ch.isalnum())


def _norm_rut(value: object) -> str:
    text = _norm_text(value).replace(".", "")
    if "-" in text:
        text = text.split("-", 1)[0]
    return text.replace("-", "").lstrip("0")


def _normalizar_fecha(value: object) -> str:
    text = _norm_text(value)
    if not text or text.lower() in {"nan", "none", "nat"}:
        return ""
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    return parsed.strftime("%d/%m/%Y") if not pd.isna(parsed) else text[:20].rstrip()


def _column(columns: list[object], *aliases: str) -> object | None:
    by_normalized = {_norm_header(col): col for col in columns}
    for alias in aliases:
        found = by_normalized.get(_norm_header(alias))
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class GestionImportRow:
    rut: str
    nombre: str
    tipo: str
    estado: str
    fecha: str
    observacion: str
    origen: str
    empresa_explicit: str


def _read_workbook(content: bytes) -> tuple[list[GestionImportRow], list[str]]:
    try:
        workbook = pd.ExcelFile(BytesIO(content))
    except Exception as exc:
        raise ValueError("El archivo seleccionado no es un Excel válido.") from exc

    rows: list[GestionImportRow] = []
    warnings: list[str] = []
    found_sheets = 0

    for sheet_name, management_type in SHEETS.items():
        if sheet_name not in workbook.sheet_names:
            warnings.append(f"Hoja '{sheet_name}' no encontrada en el Excel.")
            continue
        found_sheets += 1
        frame = pd.read_excel(BytesIO(content), sheet_name=sheet_name, dtype=str).fillna("")
        rut_col = _column(list(frame.columns), "Rut_Afiliado", "RUT Afiliado", "RUT")
        if rut_col is None:
            raise ValueError(f"La hoja '{sheet_name}' no contiene la columna Rut_Afiliado.")

        name_col = _column(list(frame.columns), "Nombre_Afiliado", "Nombre Afiliado", "Nombre")
        state_col = _column(list(frame.columns), "Estado")
        date_col = _column(list(frame.columns), "Fecha_gestion", "Fecha gestión", "Fecha")
        observation_col = _column(list(frame.columns), "Observacion", "Observación")
        company_col = _column(list(frame.columns), "Empresa", "Isapre")

        for _, source in frame.iterrows():
            rut = _norm_rut(source.get(rut_col, ""))
            if not rut:
                continue
            rows.append(
                GestionImportRow(
                    rut=rut,
                    nombre=_norm_text(source.get(name_col, "")) if name_col is not None else "",
                    tipo=management_type,
                    estado=_norm_text(source.get(state_col, "")) if state_col is not None else "",
                    fecha=_normalizar_fecha(source.get(date_col, "")) if date_col is not None else "",
                    observacion=(
                        _norm_text(source.get(observation_col, ""))
                        if observation_col is not None
                        else ""
                    ),
                    origen=f"excel_{sheet_name}",
                    empresa_explicit=(
                        _norm_text(source.get(company_col, "")) if company_col is not None else ""
                    ),
                )
            )

    if found_sheets == 0:
        raise ValueError("El archivo debe contener al menos una hoja llamada SMS, Email o Carta.")
    if not rows:
        raise ValueError("No se encontraron gestiones con RUT para importar.")
    return rows, warnings


def _debtor_candidates(db: Session) -> tuple[dict[str, list[str]], dict[tuple[str, str], str]]:
    companies: dict[str, set[str]] = {}
    names: dict[tuple[str, str], str] = {}
    rows = db.query(
        DeudorResumen.rut_afiliado,
        DeudorResumen.empresa,
        DeudorResumen.nombre_afiliado,
    ).all()
    for rut_value, company_value, name_value in rows:
        rut = _norm_rut(rut_value)
        company = _norm_text(company_value)
        if not rut or not company:
            continue
        companies.setdefault(rut, set()).add(company)
        names.setdefault((company, rut), _norm_text(name_value))
    return ({rut: sorted(values) for rut, values in companies.items()}, names)


def _canonical_company(value: str, candidates: list[str]) -> str:
    requested = _norm_text(value).casefold()
    return next((company for company in candidates if company.casefold() == requested), "")


def _resolve_rows(
    rows: list[GestionImportRow],
    candidates_by_rut: dict[str, list[str]],
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[tuple[GestionImportRow, str]], set[str], dict[str, list[str]]]:
    overrides_norm = {_norm_rut(rut): _norm_text(company) for rut, company in (overrides or {}).items()}
    resolved: list[tuple[GestionImportRow, str]] = []
    missing: set[str] = set()
    ambiguous: dict[str, list[str]] = {}

    for row in rows:
        candidates = candidates_by_rut.get(row.rut, [])
        if not candidates:
            missing.add(row.rut)
            continue

        requested = row.empresa_explicit or overrides_norm.get(row.rut, "")
        if requested:
            company = _canonical_company(requested, candidates)
            if not company:
                raise ValueError(
                    f"La cartera '{requested}' no corresponde al RUT {row.rut}. "
                    f"Opciones: {', '.join(candidates)}."
                )
            resolved.append((row, company))
            continue

        if len(candidates) == 1:
            resolved.append((row, candidates[0]))
        else:
            ambiguous[row.rut] = candidates

    return resolved, missing, ambiguous


def _key(row: GestionImportRow, company: str) -> tuple[str, str, str, str, str, str, str]:
    return (
        company,
        row.rut,
        row.tipo,
        row.estado,
        row.observacion,
        row.origen,
        row.fecha,
    )


def _existing_keys(
    db: Session,
    resolved: list[tuple[GestionImportRow, str]],
) -> set[tuple[str, str, str, str, str, str, str]]:
    ruts = sorted({row.rut for row, _company in resolved})
    if not ruts:
        return set()
    keys: set[tuple[str, str, str, str, str, str, str]] = set()
    for start in range(0, len(ruts), 400):
        batch = ruts[start:start + 400]
        for existing in db.query(DeudorGestion).filter(DeudorGestion.rut_afiliado.in_(batch)).all():
            keys.add(
                (
                    _norm_text(existing.empresa),
                    _norm_rut(existing.rut_afiliado),
                    _norm_text(existing.tipo_gestion),
                    _norm_text(existing.estado),
                    _norm_text(existing.observacion),
                    _norm_text(existing.origen),
                    _norm_text(existing.fecha_gestion),
                )
            )
    return keys


def preview_gestiones_import_service(
    db: Session,
    *,
    content: bytes,
    source_file: str,
) -> dict:
    rows, warnings = _read_workbook(content)
    candidates_by_rut, debtor_names = _debtor_candidates(db)
    resolved, missing, ambiguous = _resolve_rows(rows, candidates_by_rut)
    existing = _existing_keys(db, resolved)
    seen: set[tuple[str, str, str, str, str, str, str]] = set()
    duplicates = 0
    new_rows = 0
    for row, company in resolved:
        key = _key(row, company)
        if key in existing or key in seen:
            duplicates += 1
        else:
            seen.add(key)
            new_rows += 1

    ambiguous_items = []
    for rut, companies in sorted(ambiguous.items()):
        display_name = next(
            (debtor_names.get((company, rut), "") for company in companies if debtor_names.get((company, rut))),
            "",
        )
        ambiguous_items.append({"rut": rut, "nombre": display_name, "companies": companies})

    return {
        "source_file": source_file,
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "total_rows": len(rows),
        "valid_rows": len(resolved),
        "new_rows": new_rows,
        "duplicate_rows": duplicates,
        "missing_debtors": len(missing),
        "missing_ruts": sorted(missing),
        "ambiguous_debtors": ambiguous_items,
        "warnings": warnings,
    }


def import_gestiones_excel_service(
    db: Session,
    *,
    content: bytes,
    source_file: str,
    expected_file_sha256: str,
    company_overrides: dict[str, str] | None = None,
) -> dict:
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != _norm_text(expected_file_sha256):
        raise ValueError("El archivo cambió después de la vista previa. Vuelve a seleccionarlo.")

    rows, warnings = _read_workbook(content)
    candidates_by_rut, debtor_names = _debtor_candidates(db)
    resolved, missing, ambiguous = _resolve_rows(
        rows,
        candidates_by_rut,
        overrides=company_overrides,
    )
    if ambiguous:
        raise ValueError(
            "Debes seleccionar una cartera para todos los RUT presentes en más de una cartera."
        )

    existing = _existing_keys(db, resolved)
    seen = set(existing)
    inserted = 0
    duplicates = 0
    affected: set[tuple[str, str]] = set()

    for row, company in resolved:
        key = _key(row, company)
        if key in seen:
            duplicates += 1
            continue
        db.add(
            DeudorGestion(
                empresa=company,
                rut_afiliado=row.rut,
                nombre_afiliado=row.nombre or debtor_names.get((company, row.rut), ""),
                tipo_gestion=row.tipo,
                estado=row.estado,
                fecha_gestion=row.fecha,
                fecha_gestion_iso=normalizar_fecha_gestion_iso(row.fecha),
                observacion=row.observacion,
                origen=row.origen,
                assigned_to_user_id=None,
            )
        )
        seen.add(key)
        affected.add((company, row.rut))
        inserted += 1

    db.flush()
    recalcular_estados_deudores_lote(db, affected)
    db.commit()

    return {
        "source_file": source_file,
        "insertados": inserted,
        "omitidos_duplicados": duplicates,
        "omitidos_sin_deudor": sum(1 for row in rows if row.rut in missing),
        "deudores_actualizados": len(affected),
        "advertencias": warnings,
    }
