-- Threat Density Anomaly Detection
-- Groups events into 1-hour buckets using TimescaleDB time_bucket(),
-- computes a Z-score relative to each source's 7-day rolling baseline,
-- and returns buckets exceeding 2 standard deviations from normal.

WITH hourly_counts AS (
    SELECT
        time_bucket('1 hour', event_time)   AS bucket,
        source_id,
        int_type,
        threat_tier,
        COUNT(*)                              AS event_count,
        AVG(COUNT(*)) OVER (
            PARTITION BY source_id
            ORDER BY time_bucket('1 hour', event_time)
            ROWS BETWEEN 168 PRECEDING AND CURRENT ROW  -- 7-day rolling avg
        )                                     AS rolling_avg,
        STDDEV(COUNT(*)) OVER (
            PARTITION BY source_id
            ORDER BY time_bucket('1 hour', event_time)
            ROWS BETWEEN 168 PRECEDING AND CURRENT ROW
        )                                     AS rolling_stddev
    FROM   intel_events
    WHERE  event_time >= NOW() - INTERVAL '7 days'
    GROUP BY 1, 2, 3, 4
),
zscored AS (
    SELECT
        bucket,
        source_id,
        int_type,
        threat_tier,
        event_count,
        rolling_avg,
        rolling_stddev,
        CASE
            WHEN rolling_stddev > 0
            THEN (event_count - rolling_avg) / rolling_stddev
            ELSE 0
        END                                   AS z_score,
        LAG(event_count) OVER (
            PARTITION BY source_id
            ORDER BY bucket
        )                                     AS prev_hour_count
    FROM hourly_counts
)
SELECT
    bucket,
    source_id,
    int_type,
    threat_tier,
    event_count,
    ROUND(rolling_avg::numeric, 1)           AS rolling_avg,
    ROUND(z_score::numeric, 2)               AS z_score,
    event_count - prev_hour_count            AS delta_vs_prev_hour,
    CASE
        WHEN z_score > 3  THEN 'CRITICAL_SPIKE'
        WHEN z_score > 2  THEN 'HIGH_ANOMALY'
        WHEN z_score > 1  THEN 'ELEVATED'
        ELSE                   'NORMAL'
    END                                      AS anomaly_level
FROM   zscored
WHERE  z_score > 2                           -- anomalies only
ORDER BY z_score DESC, bucket DESC
LIMIT  100;
