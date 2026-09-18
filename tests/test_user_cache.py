from types import SimpleNamespace

from auth import auth_service


def _session():
    return auth_service.UserSession(
        user_id=1,
        email="admin@example.test",
        username="Admin",
        role="admin",
        is_active=True,
        must_change_password=False,
        access_token="test-token",
        auth_source="backend",
    )


def test_users_cache_reuses_response_and_can_be_invalidated(monkeypatch):
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return [{"id": 2, "username": "Ejecutiva", "email": "e@example.test", "role": "ejecutivo", "is_active": True}]

    monkeypatch.setattr(auth_service, "_http_request_auth", fake_request)
    session = _session()

    assert auth_service.list_users(session)
    assert auth_service.list_users(session)
    assert len(calls) == 1

    auth_service.invalidate_users_cache(session)
    assert auth_service.list_users(session)
    assert len(calls) == 2


def test_user_mutation_invalidates_cache(monkeypatch):
    session = _session()
    session._users_cache = [{"id": 2}]
    session._users_cache_at = 999999999.0
    monkeypatch.setattr(auth_service, "_http_request_auth", lambda *args, **kwargs: {})

    assert auth_service.admin_update_user(session, 2, role="supervisor") == []
    assert session._users_cache is None
