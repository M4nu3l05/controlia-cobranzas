import hashlib

import pytest

from core import updater


SETUP_BYTES = b"instalador ficticio" * 100
SETUP_NAME = "ControliaCobranzas_Setup_9.9.9.exe"


def _payload(**overrides):
    payload = {
        "tag_name": "v9.9.9",
        "draft": False,
        "prerelease": False,
        "body": "Notas de prueba",
        "assets": [
            {
                "name": SETUP_NAME,
                "browser_download_url": "https://example.test/setup.exe",
                "size": len(SETUP_BYTES),
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.test/SHA256SUMS.txt",
                "size": 100,
            },
        ],
    }
    payload.update(overrides)
    return payload


class _FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self._content = content
        self.headers = {"Content-Length": str(len(content))} if content else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise updater.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i : i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release():
    return updater.parse_release(_payload())


def _fake_get(checksums_text):
    def fake_get(url, **kwargs):
        if url.endswith("SHA256SUMS.txt"):
            return _FakeResponse(text=checksums_text)
        return _FakeResponse(content=SETUP_BYTES)

    return fake_get


@pytest.mark.parametrize(
    "remote, local, expected",
    [
        ("2.4.15", "2.4.9", True),
        ("v2.5.0", "2.4.15", True),
        ("2.4.15", "2.4.15", False),
        ("2.4", "2.4.0", False),
        ("2.4.1", "2.4", True),
        ("2.3.99", "2.4.0", False),
        ("basura", "2.4.0", False),
    ],
)
def test_is_newer(remote, local, expected):
    assert updater.is_newer(remote, local) is expected


def test_parse_release_ok():
    release = updater.parse_release(_payload())
    assert release.version == "9.9.9"
    assert release.setup_name == SETUP_NAME
    assert release.notes == "Notas de prueba"


@pytest.mark.parametrize(
    "overrides",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "ultima"},
        {"assets": []},
        {"assets": [{"name": SETUP_NAME, "browser_download_url": "x", "size": 1}]},
    ],
)
def test_parse_release_rechaza_releases_incompletas(overrides):
    assert updater.parse_release(_payload(**overrides)) is None


def test_find_update_sin_releases(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResponse(status_code=404))
    assert updater.find_update() is None


def test_find_update_devuelve_release_mas_nueva(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResponse(json_data=_payload()))
    assert updater.find_update().version == "9.9.9"


def test_find_update_ignora_version_igual(monkeypatch):
    payload = _payload(tag_name=f"v{updater.APP_VERSION}")
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _FakeResponse(json_data=payload))
    assert updater.find_update() is None


def test_expected_sha256_formatos():
    digest = "a" * 64
    assert updater.expected_sha256(f"{digest}  {SETUP_NAME}\n", SETUP_NAME) == digest
    assert updater.expected_sha256(f"{digest} *{SETUP_NAME}\n", SETUP_NAME) == digest
    with pytest.raises(updater.UpdateError):
        updater.expected_sha256(f"{digest}  otro.exe\n", SETUP_NAME)


def test_download_update_verifica_hash(monkeypatch, tmp_path):
    digest = hashlib.sha256(SETUP_BYTES).hexdigest()
    monkeypatch.setattr(updater.requests, "get", _fake_get(f"{digest}  {SETUP_NAME}\n"))
    progress = []

    path = updater.download_update(_release(), progress_cb=lambda d, t: progress.append((d, t)), dest_dir=tmp_path)

    assert path.read_bytes() == SETUP_BYTES
    assert progress[-1] == (len(SETUP_BYTES), len(SETUP_BYTES))
    assert not list(tmp_path.glob("*.part"))


def test_download_update_descarta_hash_incorrecto(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.requests, "get", _fake_get(f"{'0' * 64}  {SETUP_NAME}\n"))

    with pytest.raises(updater.UpdateError):
        updater.download_update(_release(), dest_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_update_cancelada(monkeypatch, tmp_path):
    digest = hashlib.sha256(SETUP_BYTES).hexdigest()
    monkeypatch.setattr(updater.requests, "get", _fake_get(f"{digest}  {SETUP_NAME}\n"))

    with pytest.raises(updater.UpdateCancelled):
        updater.download_update(_release(), is_cancelled=lambda: True, dest_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_launch_installer_no_corre_en_desarrollo(monkeypatch, tmp_path):
    monkeypatch.delattr(updater.sys, "frozen", raising=False)
    llamado = []
    monkeypatch.setattr(updater.os, "startfile", lambda *a: llamado.append(a), raising=False)

    with pytest.raises(updater.UpdateError):
        updater.launch_installer(tmp_path / "setup.exe")
    assert llamado == []
