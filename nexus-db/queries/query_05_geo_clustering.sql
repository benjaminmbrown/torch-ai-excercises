-- ============================================================
-- Query 5 — Geospatial Cluster Analysis
-- Groups events into 1° lat/lon grid cells to identify
-- geographic hotspots. Returns cells with 3+ critical/high events.
-- ============================================================

SELECT
    FLOOR(geo_lat) AS lat_grid,
    FLOOR(geo_lon) AS lon_grid,
    geo_region,
    COUNT(*)                                           AS total_events,
    COUNT(*) FILTER (WHERE threat_tier = 'CRITICAL')   AS critical,
    COUNT(*) FILTER (WHERE threat_tier = 'HIGH')       AS high,
    ROUND(AVG(geo_lat)::numeric, 4)                    AS centroid_lat,
    ROUND(AVG(geo_lon)::numeric, 4)                    AS centroid_lon,
    MIN(occurred_at)                                   AS first_seen,
    MAX(occurred_at)                                   AS last_seen,
    ARRAY_AGG(DISTINCT source_id::text) FILTER (
        WHERE threat_tier IN ('HIGH','CRITICAL')
    )                                                  AS high_threat_sources
FROM intel_events
WHERE
    geo_lat  IS NOT NULL
    AND geo_lon IS NOT NULL
    AND occurred_at >= NOW() - INTERVAL '30 days'
GROUP BY FLOOR(geo_lat), FLOOR(geo_lon), geo_region
HAVING
    COUNT(*) FILTER (WHERE threat_tier IN ('CRITICAL','HIGH')) >= 3
ORDER BY critical DESC, total_events DESC;
