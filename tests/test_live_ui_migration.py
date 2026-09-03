from alembic.config import Config
from alembic.script import ScriptDirectory


def test_database_migrations_have_one_expected_alembic_head() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert scripts.get_heads() == ["0012_de_postal_codes"]
