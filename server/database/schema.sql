-- database/schema.sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- Localities table (Mumbai neighborhoods)
CREATE TABLE localities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    geometry GEOMETRY(POLYGON, 4326),
    ward VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Environmental metrics table (includes AQI)
CREATE TABLE environmental_metrics (
    id SERIAL PRIMARY KEY,
    locality_id INT REFERENCES localities(id),
    date DATE,
    -- Satellite indices
    ndvi FLOAT,
    lst FLOAT,
    ndwi FLOAT,
    -- Air quality
    aqi INT,
    pm25 FLOAT,
    pm10 FLOAT,
    no2 FLOAT,
    o3 FLOAT,
    so2 FLOAT,
    co FLOAT,
    -- Weather
    temperature FLOAT,
    humidity FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Anomalies table
CREATE TABLE anomalies (
    id SERIAL PRIMARY KEY,
    locality_id INT REFERENCES localities(id),
    date DATE,
    anomaly_score FLOAT,
    anomaly_type VARCHAR(50), -- 'point', 'temporal', 'trend'
    root_cause TEXT,
    mitigation_suggestion TEXT,
    detected_at TIMESTAMP DEFAULT NOW()
);

-- Feedback table (for Phase 2)
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    anomaly_id INT REFERENCES anomalies(id),
    user_rating BOOLEAN,
    actual_cause TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_metrics_locality_date ON environmental_metrics(locality_id, date);
CREATE INDEX idx_metrics_date ON environmental_metrics(date);
CREATE INDEX idx_anomalies_date ON anomalies(date);
CREATE INDEX idx_anomalies_locality ON anomalies(locality_id);
CREATE INDEX idx_localities_geometry ON localities USING GIST(geometry);