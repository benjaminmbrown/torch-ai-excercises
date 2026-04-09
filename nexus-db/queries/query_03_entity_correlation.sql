-- ============================================================
-- Query 3 — Cross-Source Entity Co-occurrence
-- Finds entity pairs that appear together across multiple
-- independent sources — a key indicator of corroborated intel.
-- ============================================================

WITH entity_events AS (
    -- Entities with their events and originating source
    SELECT
        ee.entity_id,
        en.canonical_name,
        en.entity_type,
        ie.event_id,
        ie.occurred_at,
        ie.source_id,
        ie.threat_tier
    FROM event_entities ee
    JOIN entities      en ON en.entity_id   = ee.entity_id
    JOIN intel_events  ie ON ie.event_id   = ee.event_id
                          AND ie.occurred_at = ee.occurred_at
    WHERE ie.occurred_at >= NOW() - INTERVAL '90 days'
),
co_occurrence AS (
    -- Self-join: find entity pairs sharing the same event
    SELECT
        a.canonical_name AS entity_a,
        b.canonical_name AS entity_b,
        a.entity_type    AS type_a,
        b.entity_type    AS type_b,
        COUNT(DISTINCT a.event_id)           AS shared_events,
        COUNT(DISTINCT a.source_id)          AS corroborating_sources,
        MAX(a.occurred_at)                   AS most_recent,
        COUNT(*) FILTER (
            WHERE a.threat_tier IN ('HIGH','CRITICAL')
        )                                    AS high_threat_events
    FROM entity_events a
    JOIN entity_events b
        ON  b.event_id    = a.event_id
        AND b.occurred_at = a.occurred_at
        AND b.entity_id  > a.entity_id  -- deduplicate pairs
    GROUP BY a.canonical_name, b.canonical_name, a.entity_type, b.entity_type
)
SELECT
    entity_a,
    entity_b,
    type_a,
    type_b,
    shared_events,
    corroborating_sources,
    high_threat_events,
    most_recent,
    -- Confidence score: more sources = higher confidence
    ROUND(
        (1.0 - EXP(-corroborating_sources * 0.7)) *
        (1.0 - EXP(-shared_events * 0.3)), 4
    ) AS correlation_confidence
FROM co_occurrence
WHERE corroborating_sources >= 2
ORDER BY corroborating_sources DESC, shared_events DESC
LIMIT 50;
