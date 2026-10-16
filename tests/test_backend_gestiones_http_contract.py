from __future__ import annotations

import sys
from pathlib import Path

import pytest

from auth import auth_service
from auth.auth_service import (
    UserSession,
    backend_clear_all_gestiones_con_estado,
    backend_create_gestion_con_estado,
)


RENDER_BACKEND_URL = "https://crm-backend-4712.onrender.com"


class _JsonResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def json(self) -> dict:
        return self._payload


def _backend_session() -> UserSession:
    return UserSession(
        user_id=7,
        email="supervisor@example.test",
        username="Supervisora",
        role="supervisor",
        is_active=True,
        must_change_password=False,
        access_token="token-de-prueba",
        auth_source="backend",
    )


def test_desktop_create_gestion_uses_render_contract(monkeypatch):
    calls: list[dict] = []

    def request(**kwargs):
        calls.append(kwargs)
        return _JsonResponse({"id": 81})

    monkeypatch.setattr(auth_service, "get_backend_base_url", lambda: RENDER_BACKEND_URL)
    monkeypatch.setattr(auth_service._HTTP_SESSION, "request", request)

    data, error, offline = backend_create_gestion_con_estado(
        _backend_session(),
        rut="12.345.678-K",
        empresa="Empresa de prueba",
        nombre_afiliado="Persona ficticia",
        tipo_gestion="Llamada",
        estado="Contactado",
        fecha_gestion="16/10/2026",
        observacion="Dato ficticio",
        client_operation_id="10000000-0000-4000-8000-000000000001",
    )

    assert (data, error, offline) == ({"id": 81}, "", False)
    assert calls == [
        {
            "method": "POST",
            "url": f"{RENDER_BACKEND_URL}/deudores/12.345.678-K/gestiones",
            "json": {
                "empresa": "Empresa de prueba",
                "nombre_afiliado": "Persona ficticia",
                "tipo_gestion": "Llamada",
                "estado": "Contactado",
                "fecha_gestion": "16/10/2026",
                "observacion": "Dato ficticio",
                "origen": "manual",
                "assigned_to_user_id": None,
                "client_operation_id": "10000000-0000-4000-8000-000000000001",
            },
            "params": None,
            "timeout": auth_service.DEFAULT_TIMEOUT,
            "headers": {"Authorization": "Bearer token-de-prueba"},
        }
    ]


def test_desktop_clear_gestiones_uses_render_contract(monkeypatch):
    calls: list[dict] = []

    def request(**kwargs):
        calls.append(kwargs)
        return _JsonResponse({"message": "Gestiones eliminadas."})

    monkeypatch.setattr(auth_service, "get_backend_base_url", lambda: RENDER_BACKEND_URL)
    monkeypatch.setattr(auth_service._HTTP_SESSION, "request", request)

    message, error = backend_clear_all_gestiones_con_estado(_backend_session())

    assert (message, error) == ("Gestiones eliminadas.", "")
    assert calls == [
        {
            "method": "DELETE",
            "url": f"{RENDER_BACKEND_URL}/gestiones",
            "json": None,
            "params": None,
            "timeout": 600,
            "headers": {"Authorization": "Bearer token-de-prueba"},
        }
    ]


def test_local_backend_openapi_matches_desktop_gestiones_contract():
    pytest.importorskip("sqlalchemy")
    backend_root = Path(__file__).resolve().parents[1] / "CRM_Backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.main import app

    schema = app.openapi()
    paths = schema["paths"]
    assert "post" in paths["/deudores/{rut}/gestiones"]
    assert "delete" in paths["/gestiones"]

    request_schema = paths["/deudores/{rut}/gestiones"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    schema_name = request_schema["$ref"].rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][schema_name]["properties"]
    assert "client_operation_id" in properties
