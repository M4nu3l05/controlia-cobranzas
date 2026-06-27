import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Configuracion exclusivamente desechable para pruebas del backend. Evita que
# cualquier import de la aplicacion pueda resolver el servicio productivo.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-production")
os.environ.setdefault("FIRST_ADMIN_PASSWORD", "TestOnly1234")
