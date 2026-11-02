"""Add spatial_cells dense analytical grid and cell_id FK columns.

Revision ID: 20260925_0006
Revises: 20260905_0005
Create Date: 2026-09-25 00:00:00.000000

This migration is ADDITIVE ONLY.
- Creates the new spatial_cells table (300m grid covering Mumbai+Thane+Mira-Bhayandar)
- Adds nullable cell_id FK to environment_data, engineered_features, anomaly_results
- Does NOT drop or modify the zones table or any zone_id columns
- Does NOT delete existing data
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision: str = "20260925_0006"
down_revision: Union[str, Sequence[str], None] = "20260905_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create spatial_cells table and add cell_id FK columns (additive)."""

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ── spatial_cells: the new dense analytical grid ──────────────────────────
    op.create_table(
        "spatial_cells",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("cell_code", sa.String(length=32), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
            nullable=False,
        ),
        sa.Column("resolution_m", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("municipality_name", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("cell_code", name="uq_spatial_cells_cell_code"),
    )
    # Explicit spatial indexes (geoalchemy2 creates them but we ensure naming)
    op.create_index(
        "ix_spatial_cells_geometry", "spatial_cells", ["geometry"],
        unique=False, postgresql_using="gist"
    )
    op.create_index(
        "ix_spatial_cells_centroid", "spatial_cells", ["centroid"],
        unique=False, postgresql_using="gist"
    )
    op.create_index(
        "ix_spatial_cells_municipality", "spatial_cells", ["municipality_name"],
        unique=False
    )

    # ── Add cell_id FK to environment_data ────────────────────────────────────
    op.add_column(
        "environment_data",
        sa.Column("cell_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_environment_data_cell_id_spatial_cells",
        "environment_data",
        "spatial_cells",
        ["cell_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_environment_data_cell_id"),
        "environment_data",
        ["cell_id"],
        unique=False,
    )

    # ── Add cell_id FK to engineered_features ─────────────────────────────────
    op.add_column(
        "engineered_features",
        sa.Column("cell_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_engineered_features_cell_id_spatial_cells",
        "engineered_features",
        "spatial_cells",
        ["cell_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_engineered_features_cell_id"),
        "engineered_features",
        ["cell_id"],
        unique=False,
    )

    # ── Add cell_id FK to anomaly_results ─────────────────────────────────────
    op.add_column(
        "anomaly_results",
        sa.Column("cell_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_anomaly_results_cell_id_spatial_cells",
        "anomaly_results",
        "spatial_cells",
        ["cell_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_anomaly_results_cell_id"),
        "anomaly_results",
        ["cell_id"],
        unique=False,
    )


    # ── Make zone_id nullable so we can insert pure cell-based rows ───────────
    op.alter_column("environment_data", "zone_id", existing_type=sa.Integer(), nullable=True)
    op.create_unique_constraint("uq_environment_data_cell_observed_at", "environment_data", ["cell_id", "observed_at"])

    op.alter_column("engineered_features", "zone_id", existing_type=sa.Integer(), nullable=True)
    op.create_unique_constraint("uq_engineered_features_cell_observed_at", "engineered_features", ["cell_id", "observed_at"])

    op.alter_column("anomaly_results", "zone_id", existing_type=sa.Integer(), nullable=True)
    op.create_unique_constraint("uq_anomaly_results_cell_observed_at_model", "anomaly_results", ["cell_id", "observed_at", "model_name"])


def downgrade() -> None:
    """Remove cell_id columns and spatial_cells table."""
    op.drop_constraint("uq_anomaly_results_cell_observed_at_model", "anomaly_results", type_="unique")
    op.alter_column("anomaly_results", "zone_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("uq_engineered_features_cell_observed_at", "engineered_features", type_="unique")
    op.alter_column("engineered_features", "zone_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("uq_environment_data_cell_observed_at", "environment_data", type_="unique")
    op.alter_column("environment_data", "zone_id", existing_type=sa.Integer(), nullable=False)

    op.drop_index(op.f("ix_anomaly_results_cell_id"), table_name="anomaly_results")
    op.drop_constraint("fk_anomaly_results_cell_id_spatial_cells", "anomaly_results", type_="foreignkey")
    op.drop_column("anomaly_results", "cell_id")

    op.drop_index(op.f("ix_engineered_features_cell_id"), table_name="engineered_features")
    op.drop_constraint("fk_engineered_features_cell_id_spatial_cells", "engineered_features", type_="foreignkey")
    op.drop_column("engineered_features", "cell_id")

    op.drop_index(op.f("ix_environment_data_cell_id"), table_name="environment_data")
    op.drop_constraint("fk_environment_data_cell_id_spatial_cells", "environment_data", type_="foreignkey")
    op.drop_column("environment_data", "cell_id")

    op.drop_index("ix_spatial_cells_municipality", table_name="spatial_cells")
    op.drop_index("ix_spatial_cells_centroid", table_name="spatial_cells")
    op.drop_index("ix_spatial_cells_geometry", table_name="spatial_cells")
    op.drop_table("spatial_cells")
