from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import (
    SMTP_PRESETS,
    cargar_config,
    guardar_config,
    guardar_sesion_smtp,
)
from .ui_components import Card
from .worker import probar_conexion


class TabConfig(QWidget):
    config_guardada = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        outer.addWidget(scroll)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        scroll.setWidget(inner)

        card = Card("Configuración del servidor de correo", "Ingresa los datos de tu cuenta SMTP.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(list(SMTP_PRESETS.keys()))
        self.cmb_preset.currentTextChanged.connect(self._on_preset)
        form.addRow("Proveedor:", self.cmb_preset)

        self.txt_host = QLineEdit()
        form.addRow("Servidor SMTP:", self.txt_host)

        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(587)
        form.addRow("Puerto:", self.spn_port)

        self.chk_tls = QCheckBox("Usar STARTTLS")
        self.chk_tls.setChecked(True)
        form.addRow("Seguridad:", self.chk_tls)

        self.txt_usuario = QLineEdit()
        form.addRow("Usuario / Email:", self.txt_usuario)

        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setPlaceholderText("Se solicita por sesión; no se guarda en disco")
        form.addRow("Contraseña:", self.txt_pass)

        self.txt_nombre = QLineEdit()
        form.addRow("Nombre remitente:", self.txt_nombre)

        card.body.addLayout(form)

        btn_row = QHBoxLayout()

        self.btn_test = QPushButton("🔌  Probar conexión")
        self.btn_test.clicked.connect(self._probar)

        self.btn_save = QPushButton("💾  Guardar configuración")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._guardar)

        btn_row.addWidget(self.btn_test)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_save)
        card.body.addLayout(btn_row)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setObjectName("StatusLabel")
        self.lbl_estado.setWordWrap(True)
        card.body.addWidget(self.lbl_estado)

        layout.addWidget(card)
        layout.addStretch(1)

        self._cargar_config()
        self._on_preset(self.cmb_preset.currentText())

    def _on_preset(self, preset: str):
        datos = SMTP_PRESETS.get(preset, {})
        if datos.get("host"):
            self.txt_host.setText(datos["host"])
        self.spn_port.setValue(datos.get("port", 587))
        self.chk_tls.setChecked(datos.get("tls", True))

    def _cargar_config(self):
        cfg = cargar_config()
        if not cfg:
            return

        idx = self.cmb_preset.findText(cfg.get("preset", "Outlook / Hotmail"))
        if idx >= 0:
            self.cmb_preset.setCurrentIndex(idx)

        self.txt_host.setText(cfg.get("host", ""))
        self.spn_port.setValue(int(cfg.get("port", 587)))
        self.chk_tls.setChecked(cfg.get("tls", True))
        self.txt_usuario.setText(cfg.get("usuario", ""))
        self.txt_nombre.setText(cfg.get("nombre_remitente", ""))
        self.txt_pass.clear()

    def _probar(self):
        self.lbl_estado.setText("Conectando…")
        self.btn_test.setEnabled(False)
        QTimer.singleShot(100, self._hacer_test)

    def _hacer_test(self):
        host = self.txt_host.text().strip()
        port = self.spn_port.value()
        tls = self.chk_tls.isChecked()
        usuario = self.txt_usuario.text().strip()
        password = self.txt_pass.text()
        nombre_remitente = self.txt_nombre.text().strip() or "Controlia Cobranzas"

        ok, msg = probar_conexion(host, port, tls, usuario, password)

        if ok:
            # Guardar sesión SMTP viva en memoria para reutilizarla en otros módulos
            guardar_sesion_smtp({
                "host": host,
                "port": port,
                "tls": tls,
                "usuario": usuario,
                "password": password,
                "nombre_remitente": nombre_remitente,
            })
            self.lbl_estado.setText(f"✅ {msg}\nSesión SMTP activa para esta sesión de la app.")
        else:
            self.lbl_estado.setText(msg)

        self.btn_test.setEnabled(True)

    def _guardar(self):
        host = self.txt_host.text().strip()
        port = self.spn_port.value()
        tls = self.chk_tls.isChecked()
        usuario = self.txt_usuario.text().strip()
        password = self.txt_pass.text()
        nombre_remitente = self.txt_nombre.text().strip() or "Controlia Cobranzas"

        guardar_config({
            "preset": self.cmb_preset.currentText(),
            "host": host,
            "port": port,
            "tls": tls,
            "usuario": usuario,
            "nombre_remitente": nombre_remitente,
        })

        # Si el usuario escribió contraseña, dejamos además la sesión activa en memoria
        if str(password).strip():
            guardar_sesion_smtp({
                "host": host,
                "port": port,
                "tls": tls,
                "usuario": usuario,
                "password": password,
                "nombre_remitente": nombre_remitente,
            })
            self.lbl_estado.setText("✅ Configuración guardada y sesión SMTP activa para esta sesión de la app.")
        else:
            self.lbl_estado.setText("✅ Configuración guardada. La contraseña no se almacena en disco.")

        QMessageBox.information(
            self,
            "Configuracion guardada",
            "La configuracion SMTP se guardo correctamente.",
        )
        self.config_guardada.emit()

    def get_config(self) -> dict:
        return {
            "host": self.txt_host.text().strip(),
            "port": self.spn_port.value(),
            "tls": self.chk_tls.isChecked(),
            "usuario": self.txt_usuario.text().strip(),
            "password": self.txt_pass.text(),
            "nombre_remitente": self.txt_nombre.text().strip() or "Controlia Cobranzas",
        }
