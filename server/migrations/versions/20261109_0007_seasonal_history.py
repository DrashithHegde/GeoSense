"""Seasonal history: per-cell satellite statistics and per-station AQI by season.

Kept in their own tables so the existing "latest value" queries on environment_data are
untouched (old seasons can never be mistaken for current values).

Revision ID: 20261109_0007
Revises: 20260925_0006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261109_0007"
down_revision: Union[str, Sequence[str], None] = "20260925_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "history_seasons",
        sa.Column("season", sa.String(32), primary_key=True),          # e.g. 2024-pre
        sa.Column("label", sa.String(64), nullable=False),            # e.g. Pre-monsoon 2024
        sa.Column("kind", sa.String(16), nullable=False),             # pre | post
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("partial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("s2_images", sa.Integer),
        sa.Column("landsat_images", sa.Integer),
        sa.Column("metadata", postgresql.JSONB),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "cell_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cell_id", sa.Integer, sa.ForeignKey("spatial_cells.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.String(32), sa.ForeignKey("history_seasons.season", ondelete="CASCADE"), nullable=False),
        sa.Column("ndvi", sa.Float), sa.Column("veg_frac", sa.Float), sa.Column("built_frac", sa.Float),
        sa.Column("openwater_frac", sa.Float), sa.Column("ndmi_veg", sa.Float), sa.Column("ndbi_land", sa.Float),
        sa.Column("water_frac", sa.Float), sa.Column("wh", sa.Float), sa.Column("lst", sa.Float),
        sa.Column("s2_valid_frac", sa.Float), sa.Column("lst_valid_frac", sa.Float),
        sa.UniqueConstraint("cell_id", "season", name="uq_cell_history_cell_season"),
    )
    op.create_index("ix_cell_history_cell", "cell_history", ["cell_id"])
    op.create_table(
        "station_aqi_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("station_id", sa.Integer, nullable=False),          # OpenAQ location id
        sa.Column("station_name", sa.String(200), nullable=False),
        sa.Column("lat", sa.Float, nullable=False), sa.Column("lon", sa.Float, nullable=False),
        sa.Column("season", sa.String(32), nullable=False),
        sa.Column("days_with_aqi", sa.Integer, nullable=False),
        sa.Column("aqi_median", sa.Float), sa.Column("aqi_p90", sa.Float),
        sa.Column("dominant_pollutant", sa.String(16)),
        sa.Column("sub_index_medians", postgresql.JSONB),
        sa.Column("method", sa.String(300)),
        sa.UniqueConstraint("station_id", "season", name="uq_station_history_station_season"),
    )


def downgrade() -> None:
    op.drop_table("station_aqi_history")
    op.drop_index("ix_cell_history_cell", table_name="cell_history")
    op.drop_table("cell_history")
    op.drop_table("history_seasons")
