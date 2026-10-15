import json
from types import SimpleNamespace

from auth import auth_service


def test_import_sends_assignment_overrides_in_the_same_request(monkeypatch, tmp_path):
    captured = {}

    def fake_multipart(path, token, *, data, files, timeout=120):
        captured["path"] = path
        captured["token"] = token
        captured["data"] = dict(data)
        captured["filename"] = files["file"][0]
        captured["content"] = files["file"][1].read()
        return {"asignaciones_aplicadas": 1, "deudores_sin_asignar": 1}

    monkeypatch.setattr(auth_service, "_http_multipart_auth", fake_multipart)
    source = tmp_path / "base.xlsx"
    source.write_bytes(b"excel de prueba")
    session = SimpleNamespace(access_token="token-prueba")

    result, error = auth_service.backend_import_deudores(
        session,
        empresa="Consalud",
        excel_path=str(source),
        expected_file_sha256="abc123",
        assignment_overrides={"maria perez gonzalez": 42, "usuario por crear": 0},
    )

    assert error == ""
    assert result == {"asignaciones_aplicadas": 1, "deudores_sin_asignar": 1}
    assert captured["path"] == "/deudores/import"
    assert captured["token"] == "token-prueba"
    assert captured["filename"] == "base.xlsx"
    assert captured["content"] == b"excel de prueba"
    assert json.loads(captured["data"]["assignment_overrides_json"]) == {
        "maria perez gonzalez": 42,
        "usuario por crear": 0,
    }
    assert "overrides_json" not in captured["data"]
