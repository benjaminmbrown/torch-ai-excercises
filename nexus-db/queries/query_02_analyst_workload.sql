-- ============================================================
-- Query 2 — Analyst Workload & Resolution Time
-- Analyst performance metrics: open queue depth, average
-- time-to-close, and clearance utilization.
-- ============================================================

SELECT
    a.display_name                                              AS analyst,
    a.clearance_level,
    COUNT(*) FILTER (WHERE e.status NOT IN ('CLOSED'))         AS open_events,
    COUNT(*) FILTER (WHERE e.status = 'CLOSED'
        AND e.occurred_at >= NOW() - INTERVAL '7 days')        AS closed_last_7d,
    COUNT(*) FILTER (WHERE e.threat_tier IN ('HIGH','CRITICAL')
        AND e.status NOT IN ('CLOSED'))                        AS open_high_critical,
    PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (e.resolved_at - e.ingested_at))
    ) FILTER (WHERE e.resolved_at IS NOT NULL) / 3600          AS median_resolution_hrs,
    PERCENTILE_CONT(0.95) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (e.resolved_at - e.ingested_at))
    ) FILTER (WHERE e.resolved_at IS NOT NULL) / 3600          AS p95_resolution_hrs,
    COUNT(*) FILTER (WHERE
        e.classification::text > a.clearance_level::text)      AS clearance_violations  -- should be 0
FROM analysts a
LEFT JOIN intel_events e ON e.analyst_id = a.analyst_id
WHERE a.is_active = TRUE
GROUP BY a.analyst_id, a.display_name, a.clearance_level
HAVING COUNT(*) > 0
ORDER BY open_high_critical DESC, open_events DESC;
