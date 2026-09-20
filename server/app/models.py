from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    ward: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    environment_data: Mapped[list[EnvironmentData]] = relationship(
        back_populates="zone",
        cascade="all, delete-orphan",
    )
    engineered_features: Mapped[list[EngineeredFeature]] = relationship(
        back_populates="zone",
        cascade="all, delete-orphan",
    )
    anomaly_results: Mapped[list[AnomalyResult]] = relationship(
        back_populates="zone",
        cascade="all, delete-orphan",
    )


class EnvironmentData(Base):
    __tablename__ = "environment_data"
    __table_args__ = (
        UniqueConstraint("zone_id", "observed_at", name="uq_environment_data_zone_observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndwi: Mapped[float | None] = mapped_column(Float, nullable=True)
    mndwi: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndci: Mapped[float | None] = mapped_column(Float, nullable=True)
    turbidity_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_extent_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_health_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    lst: Mapped[float | None] = mapped_column(Float, nullable=True)
    aqi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pm25: Mapped[float | None] = mapped_column(Float, nullable=True)
    pm10: Mapped[float | None] = mapped_column(Float, nullable=True)
    no2: Mapped[float | None] = mapped_column(Float, nullable=True)
    o3: Mapped[float | None] = mapped_column(Float, nullable=True)
    so2: Mapped[float | None] = mapped_column(Float, nullable=True)
    co: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    aqi_source_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    aqi_nearest_station_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="environment_data")
    engineered_features: Mapped[list[EngineeredFeature]] = relationship(
        back_populates="environment_data",
        cascade="all, delete-orphan",
    )
    anomaly_results: Mapped[list[AnomalyResult]] = relationship(
        back_populates="environment_data",
        cascade="all, delete-orphan",
    )


class EngineeredFeature(Base):
    __tablename__ = "engineered_features"
    __table_args__ = (
        UniqueConstraint("zone_id", "observed_at", name="uq_engineered_features_zone_observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_data_id: Mapped[int | None] = mapped_column(
        ForeignKey("environment_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    daily_ndvi_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_ndwi_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_mndwi_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_water_extent_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_lst_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_aqi_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_ndvi_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_ndwi_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_mndwi_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_water_extent_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_lst_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_aqi_avg_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    pollution_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    heat_stress_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_stress_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vegetation_stress_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feature_values: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="engineered_features")
    environment_data: Mapped[EnvironmentData | None] = relationship(back_populates="engineered_features")
    anomaly_results: Mapped[list[AnomalyResult]] = relationship(
        back_populates="engineered_feature",
        cascade="all, delete-orphan",
    )


class AnomalyResult(Base):
    __tablename__ = "anomaly_results"
    __table_args__ = (
        UniqueConstraint("zone_id", "observed_at", "model_name", name="uq_anomaly_results_zone_observed_at_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_data_id: Mapped[int | None] = mapped_column(
        ForeignKey("environment_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    engineered_feature_id: Mapped[int | None] = mapped_column(
        ForeignKey("engineered_features.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, server_default="isolation_forest", index=True)
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    mitigation_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="anomaly_results")
    environment_data: Mapped[EnvironmentData | None] = relationship(back_populates="anomaly_results")
    engineered_feature: Mapped[EngineeredFeature | None] = relationship(back_populates="anomaly_results")
