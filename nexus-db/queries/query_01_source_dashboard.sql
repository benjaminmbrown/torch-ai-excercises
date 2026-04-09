-- ============================================================
-- Query 1 — Source Performance Dashboard
-- Top sources by event volume with threat tier breakdown
-- over a configurable lookback window.
-- ============================================================

WITH source_stats AS (
    SELECT
        s.source_id,
        s.source_name,
        s.source_type,
        s.reliability,
        COUNT(*) AS total_events,
        COUNT(*) FILTER (WHERE e.threat_tier = 'CRITICAL')     AS critical_count,
        COUNT(*) FILTER (WHERE e.threat_tier = 'HIGH')         AS high_count,
        COUNT(*) FILTER (WHERE e.threat_tier = 'MEDIUM')       AS medium_count,
        COUNT(*) FILTER (WHERE e.status = 'CLOSED')            AS closed_count,
        AVG(EXTRACT(EPOCH FROM (e.resolved_at - e.ingested_at)) / 3600)
            FILTER (WHERE e.resolved_at IS NOT NULL)           AS avg_resolution_hrs,
        ROUND(
            COUNT(*) FILTER (WHERE e.status = 'CLOSED') * 100.0
            / NULLIF(COUNT(*), 0), 1
        )                                                       AS closure_pct
    FROM sources s
    JOIN intel_events e ON e.source_id = s.source_id
    WHERE
        e.occurred_at >= NOW() - INTERVAL '30 days'
        AND s.is_active = TRUE
    GROUP BY s.source_id, s.source_name, s.source_type, s.reliability
)
SELECT
    source_name,
    source_type,
    reliability,
    total_events,
    critical_count,
    high_count,
    medium_count,
    ROUND(avg_resolution_hrs, 1)  AS avg_resolution_hrs,
    closure_pct                    AS pct_closed,
    RANK() OVER (ORDER BY total_events DESC)   AS volume_rank,
    RANK() OVER (ORDER BY critical_count DESC) AS criticality_rank
FROM source_stats
ORDER BY total_events DESC
LIMIT 20;
