-- Source Reliability Scoring
-- Grades intelligence sources A-D based on 90-day corroboration rate,
-- refutation rate, and average confidence score.

WITH source_stats AS (
    SELECT
        s.id                                 AS source_id,
        s.source_name,
        s.source_type,
        s.classification_level,
        COUNT(ie.id)                         AS total_events,
        COUNT(ie.id) FILTER (
            WHERE ie.corroborated_by IS NOT NULL
        )                                    AS corroborated_events,
        COUNT(ie.id) FILTER (
            WHERE ie.status = 'REFUTED'
        )                                    AS refuted_events,
        AVG(ie.confidence_score)             AS avg_confidence,
        MAX(ie.event_time)                   AS last_report_time
    FROM   sources        s
    JOIN   intel_events   ie  ON ie.source_id = s.id
    WHERE  ie.event_time >= NOW() - INTERVAL '90 days'
    GROUP BY s.id, s.source_name, s.source_type, s.classification_level
)
SELECT
    source_name,
    source_type,
    total_events,
    corroborated_events,
    refuted_events,
    ROUND(
        corroborated_events::numeric / NULLIF(total_events, 0) * 100, 1
    )                                        AS corroboration_pct,
    ROUND(avg_confidence::numeric, 3)        AS avg_confidence,
    CASE
        WHEN corroborated_events::numeric / NULLIF(total_events, 0) > 0.8
             AND refuted_events < 5         THEN 'A'  -- highly reliable
        WHEN corroborated_events::numeric / NULLIF(total_events, 0) > 0.6
                                             THEN 'B'  -- generally reliable
        WHEN refuted_events > total_events * 0.3
                                             THEN 'D'  -- questionable
        ELSE                                      'C'  -- usually reliable
    END                                      AS reliability_grade,
    last_report_time
FROM   source_stats
ORDER BY corroboration_pct DESC, total_events DESC;
