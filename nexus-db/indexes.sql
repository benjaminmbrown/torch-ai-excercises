-- ============================================================
-- NEXUS Intelligence Platform — Index Definitions (23 indexes)
-- ============================================================

-- ── intel_events indexes ─────────────────────────────────────
-- Primary access pattern: time-bounded queries by threat tier
CREATE INDEX idx_events_threat_time
    ON intel_events (threat_tier, occurred_at DESC)
    INCLUDE (event_id, title, classification, status);

-- Source correlation (fast aggregation)
CREATE INDEX idx_events_source_time
    ON intel_events (source_id, occurred_at DESC)
    INCLUDE (threat_tier, status);

-- Analyst workload (partial — only open events)
CREATE INDEX idx_events_analyst_open
    ON intel_events (analyst_id, ingested_at)
    WHERE status NOT IN ('CLOSED');

-- Geospatial queries (lat/lon grid)
CREATE INDEX idx_events_geo
    ON intel_events (geo_lat, geo_lon)
    WHERE geo_lat IS NOT NULL;

-- Classification filter (for RLS bypass on lower-classified exports)
CREATE INDEX idx_events_classification
    ON intel_events (classification, status, occurred_at DESC);

-- Status filter for pipeline queue consumers
CREATE INDEX idx_events_status_ingested
    ON intel_events (status, ingested_at)
    WHERE status = 'INGESTED';

-- Semantic search via HNSW (pgvector, m=16, ef_construction=64)
CREATE INDEX idx_events_embedding_hnsw
    ON intel_events USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── entity indexes ────────────────────────────────────────────
CREATE INDEX idx_entities_type       ON entities (entity_type);
CREATE INDEX idx_entities_name_trgm  ON entities USING gin (canonical_name gin_trgm_ops);
CREATE INDEX idx_entities_aliases    ON entities USING gin (aliases);

-- ── event_entities indexes ────────────────────────────────────
CREATE INDEX idx_ee_entity_id ON event_entities (entity_id, occurred_at DESC);

-- ── sources indexes ───────────────────────────────────────────
CREATE INDEX idx_sources_type_active ON sources (source_type, is_active);

-- ── audit_log indexes ─────────────────────────────────────────
CREATE INDEX idx_audit_analyst     ON audit_log (analyst_id, logged_at DESC);
CREATE INDEX idx_audit_table_time  ON audit_log (table_name, logged_at DESC);
CREATE INDEX idx_audit_action      ON audit_log (action, logged_at DESC)
    WHERE action IN ('EXPORT', 'DELETE');

-- ── Continuous aggregate for hourly threat stats ───────────────
CREATE MATERIALIZED VIEW hourly_threat_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', occurred_at) AS bucket,
    source_id,
    threat_tier,
    COUNT(*)                            AS event_count,
    COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_count
FROM intel_events
GROUP BY 1, 2, 3
WITH NO DATA;

SELECT add_continuous_aggregate_policy('hourly_threat_stats',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
