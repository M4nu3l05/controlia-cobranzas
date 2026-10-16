import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from admin_carteras.data_operations import CarteraDataOperationsPanel


def test_data_operations_cards_are_available_only_to_administrative_roles():
    app = QApplication.instance() or QApplication([])
    supervisor = CarteraDataOperationsPanel(
        SimpleNamespace(role="supervisor", auth_source="backend")
    )
    supervisor.resize(1200, 700)
    supervisor.show()
    app.processEvents()

    assert supervisor.isVisible()
    assert supervisor.card_deudores.isVisible()
    assert supervisor.card_gestiones.isVisible()
    assert supervisor.card_exportar.isVisible()
    assert supervisor.btn_distribucion.isEnabled()

    executive = CarteraDataOperationsPanel(
        SimpleNamespace(role="ejecutivo", auth_source="backend")
    )
    assert not executive._authorized
    assert not executive.isVisible()

    supervisor.close()
    executive.close()
