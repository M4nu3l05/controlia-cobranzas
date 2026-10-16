import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

import envios.view_plantillas as templates_module
import deudores.detalle_dialog as detail_module
from deudores.detalle_dialog import _CorreoDeudorMixin, _VistaPreviaEmailDialog


class _MailHost(_CorreoDeudorMixin, QWidget):
    def __init__(self):
        QWidget.__init__(self)
        self._session = None
        self._rut = "12345678"
        self._plantillas = [{"nombre": "Aviso", "asunto": "Hola", "cuerpo": "Mensaje"}]
        self._info_cliente = {
            "Nombre": "Persona Prueba",
            "Correo": "persona@example.test",
            "Teléfono Móvil": "+56911111111",
        }
        self._fila_resumen = {}
        self._filas_deuda = []


def test_email_send_action_lives_in_preview_dialog():
    app = QApplication.instance() or QApplication([])
    host = _MailHost()
    card = host._construir_card_correo()

    assert hasattr(host, "btn_preview_email")
    assert hasattr(host, "btn_enviar_whatsapp")
    assert not hasattr(host, "btn_enviar_email")

    preview = _VistaPreviaEmailDialog(
        "persona@example.test",
        "Asunto de prueba",
        "Cuerpo de prueba",
    )
    assert preview.btn_enviar.text().endswith("Enviar email")
    assert preview.btn_cerrar.text() == "Cerrar"
    preview.btn_enviar.click()
    app.processEvents()

    assert preview.send_requested is True
    assert preview.result() == QDialog.DialogCode.Accepted
    preview.close()
    card.close()
    host.close()


def test_preview_close_does_not_request_send():
    app = QApplication.instance() or QApplication([])
    preview = _VistaPreviaEmailDialog("persona@example.test", "Asunto", "Cuerpo")
    preview.btn_cerrar.click()
    app.processEvents()

    assert preview.send_requested is False
    assert preview.result() == QDialog.DialogCode.Rejected
    preview.close()


def test_preview_sends_the_exact_rendered_message(monkeypatch):
    app = QApplication.instance() or QApplication([])
    host = _MailHost()
    preview_data = (
        "persona@example.test",
        "Persona Prueba",
        "Aviso",
        "Asunto renderizado",
        "Cuerpo renderizado",
    )
    sent = []

    class _AcceptedPreview:
        def __init__(self, destinatario, asunto, cuerpo, parent):
            assert (destinatario, asunto, cuerpo) == (
                preview_data[0],
                preview_data[3],
                preview_data[4],
            )
            assert parent is host
            self.send_requested = True

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(detail_module, "_VistaPreviaEmailDialog", _AcceptedPreview)
    host._generar_preview = lambda: preview_data
    host._enviar_email = lambda data=None: sent.append(data)

    host._vista_previa_email()
    app.processEvents()

    assert sent == [preview_data]
    host.close()


def test_available_variable_can_be_copied_and_pasted(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        templates_module,
        "cargar_plantillas",
        lambda _session=None: [{"nombre": "Aviso", "asunto": "", "cuerpo": ""}],
    )
    widget = templates_module.TabPlantillas(session=None)
    widget.show()
    app.processEvents()

    flags = widget.lbl_vars.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard

    variable = "{nombre}"
    start = widget.lbl_vars.text().index(variable)
    widget.lbl_vars.setSelection(start, len(variable))
    widget.lbl_vars.setFocus()
    QTest.keyClick(widget.lbl_vars, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    widget.txt_cuerpo.setFocus()
    QTest.keyClick(widget.txt_cuerpo, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()

    assert widget.txt_cuerpo.toPlainText() == variable
    widget.close()
