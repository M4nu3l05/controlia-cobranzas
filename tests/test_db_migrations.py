import sqlite3

from core.db_migrations import Migration, apply_migrations, current_version


def test_apply_migrations_tracks_version():
    con = sqlite3.connect(":memory:")
    migrations = [
        Migration(1, "create sample", lambda c: c.execute("CREATE TABLE sample(id INTEGER)")),
        Migration(2, "add index", lambda c: c.execute("CREATE INDEX idx_sample_id ON sample(id)")),
    ]
    applied = apply_migrations(con, migrations)
    assert applied == 2
    assert current_version(con) == 2
