import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from app.db.migrations import apply_backend_migrations
from app.db.session import Base
from app.models.deudor import DeudorDetalle, DeudorResumen
from app.models.gestion import DeudorGestion
from app.services.deudor_service import get_dashboard_summary_service, list_deudores_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[DeudorResumen.__table__, DeudorDetalle.__table__, DeudorGestion.__table__],
    )
    with Session(engine) as session:
        yield session


def _resumen(empresa, rut, nombre, estado, periodo, copago, pagos, saldo):
    return DeudorResumen(
        empresa=empresa,
        rut_afiliado=rut,
        dv="1",
        rut_completo=f"{rut}-1",
        nombre_afiliado=nombre,
        estado_deudor=estado,
        periodo_carga=periodo,
        copago=copago,
        total_pagos=pagos,
        saldo_actual=saldo,
    )


def test_dashboard_sql_aggregate_preserves_metrics_and_never_reads_detail(db):
    db.add_all([
        _resumen("Consalud", "1", "Ana", "Sin Gestión", "202609", 100, 10, 90),
        _resumen("Consalud", "2", "Beto", "Contactado", "202609", 200, 50, 150),
        _resumen("Colmena", "3", "Carla", "Acuerdo de pago", "202608", 300, 100, 200),
        DeudorDetalle(
            empresa="Consalud", rut_afiliado="1", dv="1", rut_completo="1-1",
            nombre_afiliado="Ana", mail_afiliado="ana@example.test", periodo_carga="202609",
        ),
    ])
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    db.add_all([
        DeudorGestion(empresa="Consalud", rut_afiliado="1", nombre_afiliado="Ana", tipo_gestion="SMS", estado="Enviado", fecha_gestion=today, fecha_gestion_iso=today),
        DeudorGestion(empresa="Consalud", rut_afiliado="1", nombre_afiliado="Ana", tipo_gestion="Email", estado="Enviado", fecha_gestion=today, fecha_gestion_iso=today),
        DeudorGestion(empresa="Consalud", rut_afiliado="2", nombre_afiliado="Beto", tipo_gestion="Llamada", estado="Contactado", fecha_gestion=yesterday, fecha_gestion_iso=yesterday),
    ])
    db.commit()

    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda _c, _cu, stmt, _p, _ctx, _many: statements.append(stmt.lower()))
    result = get_dashboard_summary_service(db, empresas=["Consalud"], periodo_carga="202609")

    assert result.total_deudores == 2
    assert result.copago_total == 300
    assert result.total_pagos_total == 60
    assert result.saldo_total == 240
    assert result.sin_gestion_total == 1
    assert result.gestionados_total == 1
    assert result.cobertura_pct == 50
    assert result.contactados_total == 1
    assert result.gestiones_hoy == 1
    assert result.gestiones_7d == 2
    assert result.tipos_hoy == {"Email": 1, "SMS": 1}
    assert not any("deudores_detalle" in statement for statement in statements)


def test_deudores_pagination_total_order_search_and_page_contacts(db):
    for index, name in enumerate(("Ana", "Ana", "Beto", "Carla", "Dora"), start=1):
        empresa = "Consalud" if index < 5 else "Colmena"
        db.add(_resumen(empresa, str(index), name, "Sin Gestión", "202609", 10, 0, 10))
        db.add(DeudorDetalle(
            empresa=empresa, rut_afiliado=str(index), dv="1", rut_completo=f"{index}-1",
            nombre_afiliado=name, mail_afiliado=f"p{index}@example.test", periodo_carga="202609",
        ))
    db.commit()

    first = list_deudores_service(db, empresa="Consalud", limit=2, offset=0, include_contact=True)
    middle = list_deudores_service(db, empresa="Consalud", limit=2, offset=2, include_contact=True)
    last = list_deudores_service(db, empresa="Consalud", limit=2, offset=4, include_contact=True)
    searched = list_deudores_service(db, q="Beto", limit=2, offset=0)
    restricted = list_deudores_service(
        db, limit=10, offset=0, include_contact=True,
        empresas_permitidas=["Consalud"],
    )

    assert first.total == middle.total == last.total == 4
    assert [item.rut_afiliado for item in first.items] == ["1", "2"]
    assert [item.rut_afiliado for item in middle.items] == ["3", "4"]
    assert last.items == []
    assert searched.total == 1 and searched.items[0].rut_afiliado == "3"
    assert restricted.total == 4
    assert {item.empresa for item in restricted.items} == {"Consalud"}
    assert {item.mail_afiliado for item in first.items} == {"p1@example.test", "p2@example.test"}
    assert all(item.mail_afiliado != "p5@example.test" for item in first.items)


def test_migration_8_backfills_historical_dates_trims_and_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE deudores_resumen (id INTEGER PRIMARY KEY, empresa TEXT, periodo_carga TEXT, estado_deudor TEXT, nombre_afiliado TEXT, rut_afiliado TEXT)")
        connection.exec_driver_sql("CREATE TABLE deudores_detalle (id INTEGER PRIMARY KEY, empresa TEXT, periodo_carga TEXT, is_active BOOLEAN, rut_afiliado TEXT)")
        connection.exec_driver_sql("CREATE TABLE deudores_gestiones (id INTEGER PRIMARY KEY, empresa TEXT, rut_afiliado TEXT, fecha_gestion TEXT)")
        connection.exec_driver_sql("CREATE TABLE backend_schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TIMESTAMP NOT NULL)")
        for version in range(1, 8):
            connection.execute(text("INSERT INTO backend_schema_migrations VALUES (:v, 'previa', CURRENT_TIMESTAMP)"), {"v": version})
        connection.exec_driver_sql("INSERT INTO deudores_resumen VALUES (1, ' Consalud ', ' 202609 ', 'Sin Gestión', 'Ana', '1')")
        connection.exec_driver_sql("INSERT INTO deudores_detalle VALUES (1, ' Consalud ', ' 202609 ', 1, '1')")
        connection.exec_driver_sql("INSERT INTO deudores_gestiones VALUES (1, ' Consalud ', '1', '17/09/2026')")
        connection.exec_driver_sql("INSERT INTO deudores_gestiones VALUES (2, 'Consalud', '2', '2026-09-16')")
        connection.exec_driver_sql("INSERT INTO deudores_gestiones VALUES (3, 'Consalud', '3', '2026-09-15 12:30:00')")
        connection.exec_driver_sql("INSERT INTO deudores_gestiones VALUES (4, 'Consalud', '4', 'fecha invalida')")

    with Session(engine) as session:
        assert apply_backend_migrations(session) == [8, 9]
        assert apply_backend_migrations(session) == []
        dates = session.execute(text("SELECT fecha_gestion_iso FROM deudores_gestiones ORDER BY id")).scalars().all()
        normalized = session.execute(text("SELECT empresa, periodo_carga FROM deudores_resumen")).one()

    assert dates == ["2026-09-17", "2026-09-16", "2026-09-15", None]
    assert normalized == ("Consalud", "202609")
    indexes = {item["name"] for item in inspect(engine).get_indexes("deudores_gestiones")}
    assert "idx_gestiones_empresa_fecha_rut" in indexes
    assert inspect(engine).has_table("debtor_user_assignments")
    assert inspect(engine).has_table("debtor_assignment_aliases")
    assert inspect(engine).has_table("debtor_assignment_audit")
