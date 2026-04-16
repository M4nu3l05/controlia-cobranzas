"""
reset_users_db.py
=================
Herramienta de mantenimiento para Controlia Cobranzas.
Borra SOLO la base de datos de usuarios (db_auth.sqlite).
Los datos de deudores, conciliaciones y gestiones NO se tocan.

Uso:
    python reset_users_db.py

Ejecutar desde la carpeta raíz del proyecto (donde está main.py).
"""

import os
import sys
import sqlite3

# ── Ubicar la base de datos ────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.paths import get_data_dir
    data_dir = str(get_data_dir())
except Exception:
    # Fallback si no se puede importar el módulo
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    data_dir = os.path.join(appdata, "Controlia Cobranzas", "data")

db_path = os.path.join(data_dir, "db_auth.sqlite")

# ── Mostrar estado actual ──────────────────────────────────────
print("=" * 58)
print("  Controlia Cobranzas — Reset de base de datos de usuarios")
print("=" * 58)
print(f"\n  Ruta del archivo: {db_path}\n")

if not os.path.exists(db_path):
    print("  ℹ️  El archivo no existe. No hay nada que borrar.")
    print("     Al ejecutar main.py se creará un admin nuevo.\n")
    sys.exit(0)

# ── Mostrar usuarios actuales ──────────────────────────────────
try:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT email, username, role, is_active FROM users ORDER BY role"
    ).fetchall()
    con.close()

    if rows:
        print(f"  Usuarios registrados actualmente ({len(rows)}):")
        print()
        for r in rows:
            status = "activo" if r["is_active"] else "inactivo"
            print(f"    • {r['username']:20s}  {r['email']:30s}  [{r['role']}] [{status}]")
    else:
        print("  No hay usuarios registrados.")
except Exception as e:
    print(f"  No se pudo leer la base de datos: {e}")

# ── Confirmar ──────────────────────────────────────────────────
print()
print("  ADVERTENCIA: Esta acción eliminará TODOS los usuarios.")
print("  Los datos de deudores y conciliaciones NO se borran.")
print()

respuesta = input("  ¿Confirmas el reset? Escribe 'SI' para continuar: ").strip()

if respuesta.upper() != "SI":
    print("\n  Operación cancelada. No se realizaron cambios.\n")
    sys.exit(0)

# ── Borrar ─────────────────────────────────────────────────────
try:
    os.remove(db_path)
    print(f"\n  ✅ Base de datos de usuarios eliminada correctamente.")
    print(f"  Al ejecutar main.py se creará el usuario administrador.")

    # Si quedó archivo de credenciales previo, borrarlo también
    cred_path = os.path.join(data_dir, "setup_credentials.txt")
    if os.path.exists(cred_path):
        os.remove(cred_path)
        print(f"  ✅ Archivo setup_credentials.txt anterior eliminado.")

    print()
    print("  Próximo paso:")
    print("  1. (Opcional) Establece CONTROLIA_COBRANZAS_ADMIN_EMAIL si quieres")
    print("     un email diferente a admin@controlia.cl")
    print("  2. Ejecuta: python main.py")
    print("  3. Las credenciales nuevas aparecerán en:")
    print(f"     {os.path.join(data_dir, 'setup_credentials.txt')}")
    print()

except PermissionError:
    print("\n  ❌ Error: el archivo está en uso.")
    print("  Cierra el programa CRM antes de ejecutar este script.\n")
    sys.exit(1)
except Exception as e:
    print(f"\n  ❌ Error inesperado: {e}\n")
    sys.exit(1)