from alembic.config import Config
from alembic.script import ScriptDirectory


def test_live_ui_event_migration_is_single_alembic_head() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert scripts.get_heads() == ["0011_live_ui_events"]
