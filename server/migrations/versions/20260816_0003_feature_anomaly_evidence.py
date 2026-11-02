"""Add structured feature and anomaly evidence.

Revision ID: 20260816_0003
Revises: 20260816_0002
Create Date: 2026-08-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260816_0003"
down_revision: Union[str, Sequence[str], None] = "20260816_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "engineered_features",
        sa.Column("feature_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # Backfill from the historical detection time before making this identity field required.
    op.add_column("anomaly_results", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE anomaly_results SET observed_at = detected_at WHERE observed_at IS NULL")
    op.alter_column("anomaly_results", "observed_at", nullable=False)
    op.add_column("anomaly_results", sa.Column("is_anomaly", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column(
        "anomaly_results",
        sa.Column("model_name", sa.String(length=64), nullable=False, server_default=sa.text("'isolation_forest'")),
    )
    op.add_column(
        "anomaly_results",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(op.f("ix_anomaly_results_observed_at"), "anomaly_results", ["observed_at"], unique=False)
    op.create_index(op.f("ix_anomaly_results_is_anomaly"), "anomaly_results", ["is_anomaly"], unique=False)
    op.create_index(op.f("ix_anomaly_results_model_name"), "anomaly_results", ["model_name"], unique=False)
    op.create_unique_constraint(
        "uq_anomaly_results_zone_observed_at_model",
        "anomaly_results",
        ["zone_id", "observed_at", "model_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_anomaly_results_zone_observed_at_model", "anomaly_results", type_="unique")
    op.drop_index(op.f("ix_anomaly_results_model_name"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_is_anomaly"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_observed_at"), table_name="anomaly_results")
    op.drop_column("anomaly_results", "evidence")
    op.drop_column("anomaly_results", "model_name")
    op.drop_column("anomaly_results", "is_anomaly")
    op.drop_column("anomaly_results", "observed_at")
    op.drop_column("engineered_features", "feature_values")
