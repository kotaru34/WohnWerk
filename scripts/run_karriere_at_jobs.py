from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Source

SOURCE_NAME = "karriere.at"


def disable_source() -> None:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is not None and source.enabled:
            source.enabled = False
            source.config = {
                **(source.config or {}),
                "disabled_reason": (
                    "karriere.at Nutzungsbedingungen prohibit automated evaluation of the platform"
                ),
                "automated_acquisition_allowed": False,
            }
            session.commit()


def main() -> None:
    disable_source()
    raise SystemExit(
        "karriere.at automated acquisition is disabled: its Nutzungsbedingungen prohibit "
        "automated evaluation of the platform. Use the site manually instead."
    )


if __name__ == "__main__":
    main()
