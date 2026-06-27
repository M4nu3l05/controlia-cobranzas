import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic_settings")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_credentials_and_debug():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            app_debug=True,
            database_url="postgresql://localhost/controlia",
            jwt_secret_key="short",
            first_admin_password="Admin1234",
        )


def test_staging_accepts_explicit_non_production_configuration():
    settings = Settings(
        app_env="staging",
        app_debug=False,
        database_url="postgresql://localhost/controlia_staging",
        jwt_secret_key="staging-only",
        first_admin_password="staging-only",
    )
    assert settings.app_env == "staging"
