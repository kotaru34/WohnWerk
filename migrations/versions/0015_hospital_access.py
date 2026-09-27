"""Add Bundes-Klinik-Atlas hospital access data and policy fields.

Revision ID: 0015_hospital_access
Revises: 0014_candidate_workplace
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision = "0015_hospital_access"
down_revision = "0014_candidate_workplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_house_policies",
        sa.Column("hospital_max_distance_km", sa.Numeric(6, 2)),
    )
    op.add_column(
        "candidate_house_policies",
        sa.Column(
            "hospital_fail_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "hospital_facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_facility_id", sa.String(length=32), nullable=False),
        sa.Column("source_snapshot_date", sa.Date(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("region_code", sa.String(length=8)),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("street", sa.String(length=500)),
        sa.Column("postal_code", sa.String(length=5)),
        sa.Column("city", sa.String(length=160)),
        sa.Column("website_url", sa.String(length=1200)),
        sa.Column("operator_type", sa.String(length=120)),
        sa.Column("children_hospital", sa.Boolean()),
        sa.Column("security_mandate", sa.Boolean()),
        sa.Column(
            "location",
            Geography(
                geometry_type="POINT",
                srid=4326,
                spatial_index=True,
            ),
        ),
        sa.Column("emergency_level", sa.Integer()),
        sa.Column("emergency_level_unagreed", sa.Boolean()),
        sa.Column("severe_trauma", sa.Boolean()),
        sa.Column("pediatric_emergency_level", sa.Integer()),
        sa.Column("special_emergency", sa.Boolean()),
        sa.Column("stroke_unit", sa.Boolean()),
        sa.Column("chest_pain_unit", sa.Boolean()),
        sa.Column(
            "source_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source",
            "source_facility_id",
            name="uq_hospital_facilities_source_facility",
        ),
    )
    op.create_index(
        "ix_hospital_facilities_country",
        "hospital_facilities",
        ["country_code"],
    )
    op.create_index(
        "ix_hospital_facilities_postal_code",
        "hospital_facilities",
        ["postal_code"],
    )
    op.create_index(
        "ix_hospital_facilities_city",
        "hospital_facilities",
        ["city"],
    )


def downgrade() -> None:
    op.drop_index("ix_hospital_facilities_city", table_name="hospital_facilities")
    op.drop_index("ix_hospital_facilities_postal_code", table_name="hospital_facilities")
    op.drop_index("ix_hospital_facilities_country", table_name="hospital_facilities")
    op.drop_table("hospital_facilities")

    op.drop_column("candidate_house_policies", "hospital_fail_closed")
    op.drop_column("candidate_house_policies", "hospital_max_distance_km")
