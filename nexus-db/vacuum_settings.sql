-- ============================================================
-- NEXUS Intelligence Platform — Vacuum, Compression & Retention
-- Tuned for high-write TimescaleDB hypertable workload
-- ============================================================

-- intel_events is append-heavy (TimescaleDB) — reduce vacuum overhead
ALTER TABLE intel_events
    SET (autovacuum_vacuum_scale_factor = 0.01,
         autovacuum_analyze_scale_factor = 0.005,
         autovacuum_vacuum_cost_delay = 2);

-- audit_log is insert-only — disable vacuum on hot path
ALTER TABLE audit_log
    SET (autovacuum_enabled = FALSE);    -- partitioned retention handles this

-- Retention policy: drop chunks older than 2 years
SELECT add_retention_policy('intel_events', INTERVAL '2 years');

-- Compression policy: compress chunks older than 7 days
ALTER TABLE intel_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source_id, threat_tier',
    timescaledb.compress_orderby   = 'occurred_at DESC'
);
SELECT add_compression_policy('intel_events', INTERVAL '7 days');

-- ── PGBouncer pool settings (reference) ───────────────────────
-- max_client_conn = 1000
-- default_pool_size = 25
-- reserve_pool_size = 5
-- pool_mode = transaction
-- server_idle_timeout = 600

-- ── Monitoring queries ─────────────────────────────────────────
-- Active connections per database
-- SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- Long-running queries (> 5 seconds)
-- SELECT pid, query_start, NOW() - query_start AS duration, query
-- FROM pg_stat_activity
-- WHERE state = 'active' AND NOW() - query_start > INTERVAL '5s';
