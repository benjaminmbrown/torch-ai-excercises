-- ============================================================
-- Query 4 — Time-Series Threat Density (Window Functions)
-- Rolling 24-hour threat density using TimescaleDB time_bucket
-- with window functions for trend and anomaly analysis.
-- ============================================================

WITH hourly_buckets AS (
    SELECT
        time_bucket('1 hour', occurred_at)                      AS bucket,
        threat_tier,
        COUNT(*)                                               AS event_count,
        COUNT(*) FILTER (WHERE classification >= 'SECRET')    AS classified_count
    FROM intel_events
    WHERE occurred_at >= NOW() - INTERVAL '7 days'
    GROUP BY 1, 2
),
pivoted AS (
    SELECT
        bucket,
        SUM(event_count) FILTER (WHERE threat_tier = 'CRITICAL') AS critical,
        SUM(event_count) FILTER (WHERE threat_tier = 'HIGH')     AS high,
        SUM(event_count) FILTER (WHERE threat_tier = 'MEDIUM')   AS medium,
        SUM(event_count) FILTER (WHERE threat_tier = 'LOW')      AS low,
        SUM(event_count)                                          AS total
    FROM hourly_buckets
    GROUP BY bucket
)
SELECT
    bucket,
    COALESCE(critical, 0) AS critical,
    COALESCE(high, 0)     AS high,
    COALESCE(medium, 0)   AS medium,
    COALESCE(low, 0)      AS low,
    COALESCE(total, 0)    AS total,
    -- 24-hour rolling sum
    SUM(total) OVER (
        ORDER BY bucket
        ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
    )                          AS rolling_24h_total,
    -- Z-score anomaly detection (3σ threshold)
    (total - AVG(total) OVER ()) / NULLIF(STDDEV(total) OVER (), 0)
                               AS z_score,
    -- Percent change vs prior hour
    ROUND(
        (total - LAG(total, 1) OVER (ORDER BY bucket)) * 100.0
        / NULLIF(LAG(total, 1) OVER (ORDER BY bucket), 0), 1
    )                          AS pct_change_vs_prior_hour
FROM pivoted
ORDER BY bucket DESC;
