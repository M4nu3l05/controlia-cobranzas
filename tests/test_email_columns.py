import pandas as pd
import pytest

from envios.worker import obtener_columna_email


def test_detecta_columna_mail_afiliado():
    df = pd.DataFrame({"mail_afiliado": ["a@b.com"]})
    assert obtener_columna_email(df) == "mail_afiliado"


def test_falla_si_no_hay_columna_email():
    df = pd.DataFrame({"rut": ["1-9"], "nombre": ["X"]})
    with pytest.raises(ValueError):
        obtener_columna_email(df)
