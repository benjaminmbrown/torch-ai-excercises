-- Entity Network Analysis — Co-occurrence & Jaccard Similarity
-- Finds entity pairs that appear together across HIGH/CRITICAL events
-- in the last 30 days, with Jaccard similarity as correlation strength.

WITH entity_events AS (
    SELECT
        ee.event_id,
        ee.entity_id,
        e.name          AS entity_name,
        e.entity_type,
        ee.role,
        ie.event_time,
        ie.int_type,
        ie.threat_tier
    FROM       event_entities ee
    JOIN       entities        e   ON e.id  = ee.entity_id
    JOIN       intel_events    ie  ON ie.id = ee.event_id
    WHERE      ie.event_time >= NOW() - INTERVAL '30 days'
      AND      ie.threat_tier IN ('HIGH', 'CRITICAL')
),
pairs AS (
    SELECT
        a.entity_name                          AS entity_a,
        b.entity_name                          AS entity_b,
        a.entity_type                          AS type_a,
        b.entity_type                          AS type_b,
        COUNT(DISTINCT a.event_id)             AS shared_events,
        MIN(a.event_time)                      AS first_seen,
        MAX(a.event_time)                      AS last_seen,
        ARRAY_AGG(DISTINCT a.int_type)         AS source_types,
        ARRAY_AGG(DISTINCT a.threat_tier)      AS threat_tiers
    FROM       entity_events a
    JOIN       entity_events b
        ON  b.event_id = a.event_id
        AND b.entity_id > a.entity_id   -- avoid self-pairs and duplicates
    GROUP BY   a.entity_name, b.entity_name, a.entity_type, b.entity_type
    HAVING     COUNT(DISTINCT a.event_id) >= 3  -- minimum co-occurrence threshold
)
SELECT
    entity_a,
    entity_b,
    type_a,
    type_b,
    shared_events,
    ROUND(
        shared_events::numeric /
        NULLIF(
            (SELECT COUNT(DISTINCT event_id)
             FROM   entity_events x
             WHERE  x.entity_name IN (entity_a, entity_b)),
            0
        ), 4
    )                                         AS jaccard_similarity,
    first_seen,
    last_seen,
    source_types,
    threat_tiers
FROM   pairs
ORDER BY shared_events DESC, jaccard_similarity DESC
LIMIT  50;
