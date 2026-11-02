"""Add water health fields to environment_data and engineered_features.

Revision ID: 20260905_0005
Revises: 20260816_0004
Create Date: 2026-09-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260905_0005"
down_revision: Union[str, Sequence[str], None] = "20260816_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("environment_data", sa.Column("mndwi", sa.Float(), nullable=True))
    op.add_column("environment_data", sa.Column("ndci", sa.Float(), nullable=True))
    op.add_column("environment_data", sa.Column("turbidity_proxy", sa.Float(), nullable=True))
    op.add_column("environment_data", sa.Column("water_extent_m2", sa.Float(), nullable=True))
    op.add_column("environment_data", sa.Column("water_health_score", sa.Float(), nullable=True))
    op.add_column("environment_data", sa.Column("water_health_status", sa.String(length=32), nullable=True))

    op.add_column("engineered_features", sa.Column("daily_mndwi_change", sa.Float(), nullable=True))
    op.add_column("engineered_features", sa.Column("daily_water_extent_change", sa.Float(), nullable=True))
    op.add_column("engineered_features", sa.Column("rolling_mndwi_avg_7d", sa.Float(), nullable=True))
    op.add_column("engineered_features", sa.Column("rolling_water_extent_avg_7d", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("engineered_features", "rolling_water_extent_avg_7d")
    op.drop_column("engineered_features", "rolling_mndwi_avg_7d")
    op.drop_column("engineered_features", "daily_water_extent_change")
    op.drop_column("engineered_features", "daily_mndwi_change")

    op.drop_column("environment_data", "water_health_status")
    op.drop_column("environment_data", "water_health_score")
    op.drop_column("environment_data", "water_extent_m2")
    op.drop_column("environment_data", "turbidity_proxy")
    op.drop_column("environment_data", "ndci")
    op.drop_column("environment_data", "mndwi")