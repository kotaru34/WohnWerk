"""Add source-backed hospital access and candidate distance policy.

Revision ID: 0015_hospital_access
Revises: 0014_candidate_workplace
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = "0015_hospital_access"
down_revision = "0014_candidate_workplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hospital_dataset_states",
        sa.Column("source_name", sa.String(length=80), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("coverage_status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("facility_count", sa.Integer(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_hospital_dataset_states_country_code",
        "hospital_dataset_states",
        ["country_code"],
    )

    op.create_table(
        "hospital_facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_name",
            sa.String(length=80),
            sa.ForeignKey("hospital_dataset_states.source_name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("state_code", sa.String(length=8)),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("street", sa.String(length=500)),
        sa.Column("postal_code", sa.String(length=10)),
        sa.Column("city", sa.String(length=200)),
        sa.Column("facility_url", sa.String(length=1200)),
        sa.Column("carrier_type", sa.String(length=160)),
        sa.Column("is_children_hospital", sa.Boolean()),
        sa.Column("assurance_contract", sa.Boolean()),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        ),
        sa.Column("emergency_level", sa.Integer()),
        sa.Column("emergency_level_not_agreed", sa.Boolean()),
        sa.Column("severe_injury_care", sa.Boolean()),
        sa.Column("children_emergency_level", sa.Integer()),
        sa.Column("specialist_emergency_care", sa.Boolean()),
        sa.Column("stroke_unit", sa.Boolean()),
        sa.Column("chest_pain_unit", sa.Boolean()),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source_name",
            "source_id",
            name="uq_hospital_facility_source_id",
        ),
    )
    op.create_index(
        "ix_hospital_facilities_country_source",
        "hospital_facilities",
        ["country_code", "source_name"],
    )
    op.create_index(
        "ix_hospital_facilities_emergency",
        "hospital_facilities",
        ["country_code", "emergency_level"],
    )
    op.create_index("ix_hospital_facilities_postal_code", "hospital_facilities", ["postal_code"])
    op.create_index("ix_hospital_facilities_city", "hospital_facilities", ["city"])

    op.add_column(
        "candidate_house_policies",
        sa.Column("max_hospital_distance_km", sa.Numeric(precision=6, scale=2)),
    )
    op.add_column(
        "candidate_house_policies",
        sa.Column(
            "hospital_distance_fail_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_house_policies", "hospital_distance_fail_closed")
    op.drop_column("candidate_house_policies", "max_hospital_distance_km")
    op.drop_index("ix_hospital_facilities_city", table_name="hospital_facilities")
    op.drop_index("ix_hospital_facilities_postal_code", table_name="hospital_facilities")
    op.drop_index("ix_hospital_facilities_emergency", table_name="hospital_facilities")
    op.drop_index("ix_hospital_facilities_country_source", table_name="hospital_facilities")
    op.drop_table("hospital_facilities")
    op.drop_index(
        "ix_hospital_dataset_states_country_code",
        table_name="hospital_dataset_states",
    )
    op.drop_table("hospital_dataset_states")
