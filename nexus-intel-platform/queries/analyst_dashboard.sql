-- Analyst Workload & Throughput Dashboard
-- 30-day performance metrics per analyst including response time percentiles
-- and throughput rank relative to peers.

SELECT
    a.id                                          AS analyst_id,
    a.username,
    a.clearance_level,
    COUNT(ie.id)                                  AS events_reviewed_30d,
    COUNT(ie.id) FILTER (WHERE ie.threat_tier = 'CRITICAL') AS critical_events,
    COUNT(ie.id) FILTER (WHERE ie.status     = 'ACTIONED')  AS actioned_count,
    ROUND(
        AVG(
            EXTRACT(epoch FROM
                (ie.actioned_at - ie.assigned_at))
        ) / 60, 1
    )                                             AS avg_response_min,
    PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(epoch FROM (ie.actioned_at - ie.assigned_at)) / 60
    )                                             AS median_response_min,
    RANK() OVER (
        ORDER BY COUNT(ie.id) DESC
    )                                             AS throughput_rank
FROM   analysts       a
JOIN   intel_events   ie  ON ie.assigned_analyst = a.id
WHERE  ie.event_time >= NOW() - INTERVAL '30 days'
GROUP BY  a.id, a.username, a.clearance_level
ORDER BY  events_reviewed_30d DESC;
