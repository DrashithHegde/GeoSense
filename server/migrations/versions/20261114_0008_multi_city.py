"""Multi-city: every 300 m cell, history season and station-history row belongs to a city.

Revision ID: 20261114_0008
Revises: 20261109_0007

Additive and safe on an existing database: every existing row is Mumbai (the only city so far),
so the new columns default to 'mumbai'. Season keys such as "2024-pre" are now unique per city.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_0008"
down_revision: Union[str, Sequence[str], None] = "20261109_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spatial_cells", sa.Column("city", sa.String(32), nullable=False, server_default="mumbai"))
    op.create_index("ix_spatial_cells_city", "spatial_cells", ["city"])

    # history_seasons: primary key (season) -> (city, season); cell_history follows
    op.execute("ALTER TABLE cell_history DROP CONSTRAINT IF EXISTS cell_history_season_fkey")
    op.execute("ALTER TABLE history_seasons DROP CONSTRAINT IF EXISTS history_seasons_pkey")
    op.add_column("history_seasons", sa.Column("city", sa.String(32), nullable=False, server_default="mumbai"))
    op.create_primary_key("history_seasons_pkey", "history_seasons", ["city", "season"])
    op.add_column("cell_history", sa.Column("city", sa.String(32), nullable=False, server_default="mumbai"))
    op.create_foreign_key("cell_history_city_season_fkey", "cell_history", "history_seasons",
                          ["city", "season"], ["city", "season"], ondelete="CASCADE")
    op.create_index("ix_cell_history_city_season", "cell_history", ["city", "season"])

    op.execute("ALTER TABLE station_aqi_history DROP CONSTRAINT IF EXISTS uq_station_history_station_season")
    op.add_column("station_aqi_history", sa.Column("city", sa.String(32), nullable=False, server_default="mumbai"))
    op.create_unique_constraint("uq_station_history_city_station_season", "station_aqi_history",
                                ["city", "station_id", "season"])


def downgrade() -> None:
    op.drop_constraint("uq_station_history_city_station_season", "station_aqi_history", type_="unique")
    op.drop_column("station_aqi_history", "city")
    op.create_unique_constraint("uq_station_history_station_season", "station_aqi_history", ["station_id", "season"])
    op.drop_index("ix_cell_history_city_season", table_name="cell_history")
    op.drop_constraint("cell_history_city_season_fkey", "cell_history", type_="foreignkey")
    op.drop_column("cell_history", "city")
    op.drop_constraint("history_seasons_pkey", "history_seasons", type_="primary")
    op.drop_column("history_seasons", "city")
    op.create_primary_key("history_seasons_pkey", "history_seasons", ["season"])
    op.create_foreign_key("cell_history_season_fkey", "cell_history", "history_seasons", ["season"], ["season"],
                          ondelete="CASCADE")
    op.drop_index("ix_spatial_cells_city", table_name="spatial_cells")
    op.drop_column("spatial_cells", "city")
