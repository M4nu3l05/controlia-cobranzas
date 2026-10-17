import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app
from app.schemas.auth import TokenResponse


def test_session_history_endpoints_are_removed():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/auth/logout" not in paths
    assert "/dashboard/sessions" not in paths
    assert "/dashboard/summary" in paths


def test_login_contract_has_no_session_history_id():
    assert "session_history_id" not in TokenResponse.model_fields
