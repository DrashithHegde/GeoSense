"""initial GeoSense schema

Revision ID: 20260710_0001
Revises: 
Create Date: 2026-07-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision: str = "20260710_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial GeoSense tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "zones",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("zone_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("ward", sa.String(length=50), nullable=True),
        sa.Column("geometry", Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("zone_code", name="uq_zones_zone_code"),
    )
    op.create_index("ix_zones_geometry", "zones", ["geometry"], unique=False, postgresql_using="gist")
    op.create_index(op.f("ix_zones_name"), "zones", ["name"], unique=False)
    op.create_index(op.f("ix_zones_ward"), "zones", ["ward"], unique=False)

    op.create_table(
        "environment_data",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ndvi", sa.Float(), nullable=True),
        sa.Column("ndwi", sa.Float(), nullable=True),
        sa.Column("lst", sa.Float(), nullable=True),
        sa.Column("aqi", sa.Integer(), nullable=True),
        sa.Column("pm25", sa.Float(), nullable=True),
        sa.Column("pm10", sa.Float(), nullable=True),
        sa.Column("no2", sa.Float(), nullable=True),
        sa.Column("o3", sa.Float(), nullable=True),
        sa.Column("so2", sa.Float(), nullable=True),
        sa.Column("co", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name="fk_environment_data_zone_id_zones", ondelete="CASCADE"),
        sa.UniqueConstraint("zone_id", "observed_at", name="uq_environment_data_zone_observed_at"),
    )
    op.create_index(op.f("ix_environment_data_zone_id"), "environment_data", ["zone_id"], unique=False)
    op.create_index(op.f("ix_environment_data_observed_at"), "environment_data", ["observed_at"], unique=False)

    op.create_table(
        "engineered_features",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column("environment_data_id", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("daily_ndvi_change", sa.Float(), nullable=True),
        sa.Column("daily_ndwi_change", sa.Float(), nullable=True),
        sa.Column("daily_lst_change", sa.Float(), nullable=True),
        sa.Column("daily_aqi_change", sa.Float(), nullable=True),
        sa.Column("rolling_ndvi_avg_7d", sa.Float(), nullable=True),
        sa.Column("rolling_ndwi_avg_7d", sa.Float(), nullable=True),
        sa.Column("rolling_lst_avg_7d", sa.Float(), nullable=True),
        sa.Column("rolling_aqi_avg_7d", sa.Float(), nullable=True),
        sa.Column("pollution_risk_score", sa.Float(), nullable=True),
        sa.Column("heat_stress_score", sa.Float(), nullable=True),
        sa.Column("water_stress_score", sa.Float(), nullable=True),
        sa.Column("vegetation_stress_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["environment_data_id"], ["environment_data.id"], name="fk_engineered_features_environment_data_id_environment_data", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name="fk_engineered_features_zone_id_zones", ondelete="CASCADE"),
        sa.UniqueConstraint("zone_id", "observed_at", name="uq_engineered_features_zone_observed_at"),
    )
    op.create_index(op.f("ix_engineered_features_environment_data_id"), "engineered_features", ["environment_data_id"], unique=False)
    op.create_index(op.f("ix_engineered_features_observed_at"), "engineered_features", ["observed_at"], unique=False)
    op.create_index(op.f("ix_engineered_features_zone_id"), "engineered_features", ["zone_id"], unique=False)

    op.create_table(
        "anomaly_results",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column("environment_data_id", sa.Integer(), nullable=True),
        sa.Column("engineered_feature_id", sa.Integer(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("anomaly_type", sa.String(length=50), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("mitigation_suggestion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["engineered_feature_id"], ["engineered_features.id"], name="fk_anomaly_results_engineered_feature_id_engineered_features", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_data_id"], ["environment_data.id"], name="fk_anomaly_results_environment_data_id_environment_data", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name="fk_anomaly_results_zone_id_zones", ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_anomaly_results_anomaly_type"), "anomaly_results", ["anomaly_type"], unique=False)
    op.create_index(op.f("ix_anomaly_results_detected_at"), "anomaly_results", ["detected_at"], unique=False)
    op.create_index(op.f("ix_anomaly_results_engineered_feature_id"), "anomaly_results", ["engineered_feature_id"], unique=False)
    op.create_index(op.f("ix_anomaly_results_environment_data_id"), "anomaly_results", ["environment_data_id"], unique=False)
    op.create_index(op.f("ix_anomaly_results_zone_id"), "anomaly_results", ["zone_id"], unique=False)


def downgrade() -> None:
    """Drop the initial GeoSense tables."""

    op.drop_index("ix_zones_geometry", table_name="zones")
    op.drop_index(op.f("ix_anomaly_results_zone_id"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_environment_data_id"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_engineered_feature_id"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_detected_at"), table_name="anomaly_results")
    op.drop_index(op.f("ix_anomaly_results_anomaly_type"), table_name="anomaly_results")
    op.drop_table("anomaly_results")

    op.drop_index(op.f("ix_engineered_features_zone_id"), table_name="engineered_features")
    op.drop_index(op.f("ix_engineered_features_observed_at"), table_name="engineered_features")
    op.drop_index(op.f("ix_engineered_features_environment_data_id"), table_name="engineered_features")
    op.drop_table("engineered_features")

    op.drop_index(op.f("ix_environment_data_observed_at"), table_name="environment_data")
    op.drop_index(op.f("ix_environment_data_zone_id"), table_name="environment_data")
    op.drop_table("environment_data")

    op.drop_index(op.f("ix_zones_ward"), table_name="zones")
    op.drop_index(op.f("ix_zones_name"), table_name="zones")
    op.drop_table("zones")