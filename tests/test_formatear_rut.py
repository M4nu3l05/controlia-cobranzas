import pytest

from deudores.detalle_dialog import _formatear_rut_completo


@pytest.mark.parametrize(
    ("rut", "dv", "rut_completo", "esperado"),
    [
        ("1234567-9", "", "1234567-9", "1.234.567-9"),
        ("1234567", "9", "", "1.234.567-9"),
        ("12.345.678-K", "", "", "12.345.678-K"),
        ("12345678", "5", "12345678-5", "12.345.678-5"),
        ("", "", "1234567-9", "1.234.567-9"),
        ("1.234.567-9", "9", "", "1.234.567-9"),
    ],
)
def test_formatear_rut_completo_no_duplica_dv(rut, dv, rut_completo, esperado):
    assert _formatear_rut_completo(rut, dv, rut_completo) == esperado
