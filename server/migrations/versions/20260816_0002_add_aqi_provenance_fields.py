"""Add AQI provenance fields to environment_data.

Revision ID: 20260816_0002
Revises: 20260710_0001
Create Date: 2026-08-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260816_0002"
down_revision: Union[str, Sequence[str], None] = "20260710_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("environment_data", sa.Column("aqi_source_type", sa.String(length=20), nullable=True))
    op.add_column("environment_data", sa.Column("aqi_nearest_station_distance_m", sa.Float(), nullable=True))
    op.create_index(op.f("ix_environment_data_aqi_source_type"), "environment_data", ["aqi_source_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_environment_data_aqi_source_type"), table_name="environment_data")
    op.drop_column("environment_data", "aqi_nearest_station_distance_m")
    op.drop_column("environment_data", "aqi_source_type")
