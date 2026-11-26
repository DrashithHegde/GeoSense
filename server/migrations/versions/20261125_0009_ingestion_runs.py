"""Ingestion run tracking table for scheduled Azure Container Apps Jobs.

Revision ID: 20261125_0009
Revises: 20261114_0008
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125_0009"
down_revision: Union[str, Sequence[str], None] = "20261114_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("city", sa.String(32), nullable=False, server_default="mumbai"),
        sa.Column("layer", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=True),
        sa.Column("bundle_blob", sa.String(256), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_ingestion_runs_job_started", "ingestion_runs", ["job_name", "started_at"])
    op.create_index("ix_ingestion_runs_city_layer", "ingestion_runs", ["city", "layer", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_city_layer", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_job_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
