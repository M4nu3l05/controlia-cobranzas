import pandas as pd

import deudores.database as db


def _insert_cart56_case(monkeypatch, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "get_data_dir", lambda: tmp_path)
    empresa = "Cart-56"
    rut = "76066341"
    expediente = "3-127349594"

    resumen = pd.DataFrame(
        [
            {
                "Rut_Afiliado": rut,
                "Dv": "7",
                "Nombre_Afiliado": "Empresa Demo",
                "Nro_Expediente": expediente,
                "Copago": "1221978",
                "Total_Pagos": "0",
                "Saldo_Actual": "1221978",
                "Estado_deudor": "Sin Gestion",
                db.COL_EMPRESA: empresa,
                db.COL_FECHA_CARGA: "",
            }
        ]
    )
    detalle = pd.DataFrame(
        [
            {
                "Rut_Afiliado": rut,
                "Dv": "7",
                "Nombre_Afiliado": "Empresa Demo",
                "Nro_Expediente": expediente,
                "Copago": "733187",
                "Total_Pagos": "0",
                "Saldo_Actual": "733187",
                "Estado_deudor": "Sin Gestion",
                db.COL_EMPRESA: empresa,
                db.COL_FECHA_CARGA: "",
            },
            {
                "Rut_Afiliado": rut,
                "Dv": "7",
                "Nombre_Afiliado": "Empresa Demo",
                "Nro_Expediente": expediente,
                "Copago": "488791",
                "Total_Pagos": "0",
                "Saldo_Actual": "488791",
                "Estado_deudor": "Sin Gestion",
                db.COL_EMPRESA: empresa,
                db.COL_FECHA_CARGA: "",
            },
        ]
    )

    with db._conexion(empresa) as con:
        for table, frame in ((db.TABLA, resumen), (db.TABLA_DETALLE, detalle)):
            for col in frame.columns:
                db._ensure_column(con, table, col, "TEXT")
        resumen.to_sql(db.TABLA, con, if_exists="append", index=False)
        detalle.to_sql(db.TABLA_DETALLE, con, if_exists="append", index=False)

    return empresa, rut, expediente


def test_cart56_pago_total_se_distribuye_en_filas_misma_licencia(monkeypatch, tmp_path):
    empresa, rut, expediente = _insert_cart56_case(monkeypatch, tmp_path)

    resultado = db.registrar_pago_por_rut(
        empresa=empresa,
        rut=rut,
        tipo_pago="Pago total de la deuda",
        monto=1221978,
        expediente=expediente,
    )

    detalle = db.cargar_detalle_empresa(empresa).sort_values("Copago").reset_index(drop=True)

    assert resultado["saldo_actual"] == 0
    assert detalle["Saldo_Actual"].apply(db._parse_num).tolist() == [0, 0]
    assert detalle["Total_Pagos"].apply(db._parse_num).tolist() == [488791, 733187]


def test_cart56_abono_con_misma_licencia_actualiza_monto_seleccionado(monkeypatch, tmp_path):
    empresa, rut, expediente = _insert_cart56_case(monkeypatch, tmp_path)
    detalle = db.cargar_detalle_empresa(empresa)
    detalle_id = detalle.loc[detalle["Copago"] == "733187", "_detalle_id"].iloc[0]

    resultado = db.registrar_pago_por_rut(
        empresa=empresa,
        rut=rut,
        tipo_pago="Abono a la deuda",
        monto=300000,
        expediente=expediente,
        detalle_id=detalle_id,
    )

    detalle_actualizado = db.cargar_detalle_empresa(empresa)
    fila_abonada = detalle_actualizado.loc[detalle_actualizado["_detalle_id"].astype(str) == str(detalle_id)].iloc[0]
    fila_intacta = detalle_actualizado.loc[detalle_actualizado["Copago"] == "488791"].iloc[0]

    assert resultado["saldo_actual"] == 921978
    assert db._parse_num(fila_abonada["Total_Pagos"]) == 300000
    assert db._parse_num(fila_abonada["Saldo_Actual"]) == 433187
    assert db._parse_num(fila_intacta["Total_Pagos"]) == 0
    assert db._parse_num(fila_intacta["Saldo_Actual"]) == 488791
