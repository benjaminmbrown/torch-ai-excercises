-- ============================================================
-- Query 6 — Audit Trail (Export & Delete Actions)
-- Compliance-focused query returning all EXPORT and DELETE
-- actions in the past 90 days with analyst and IP attribution.
-- ============================================================

SELECT
    al.logged_at                                      AT TIME ZONE 'UTC' AS logged_utc,
    a.display_name                                    AS analyst,
    a.clearance_level,
    al.action,
    al.table_name,
    al.row_id,
    al.ip_address,
    al.session_id,
    -- Flag if analyst accessed data above their clearance
    CASE
        WHEN (al.old_values ->> 'classification') > a.clearance_level::text
          OR (al.new_values ->> 'classification') > a.clearance_level::text
        THEN TRUE
        ELSE FALSE
    END                                               AS potential_over_access
FROM audit_log al
JOIN analysts a ON a.analyst_id = al.analyst_id
WHERE
    al.action IN ('EXPORT', 'DELETE')
    AND al.logged_at >= NOW() - INTERVAL '90 days'
ORDER BY al.logged_at DESC;
