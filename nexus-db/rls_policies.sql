-- ============================================================
-- NEXUS Intelligence Platform — Row-Level Security Policies
-- Clearance-gated access + immutable audit trigger
-- ============================================================

-- Enable RLS on sensitive tables
ALTER TABLE intel_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE intel_events FORCE ROW LEVEL SECURITY;

-- Analysts can only read events at or below their clearance level
CREATE POLICY analyst_read_clearance ON intel_events
    FOR SELECT
    TO nexus_analyst
    USING (
        classification <= (
            SELECT clearance_level
            FROM analysts
            WHERE analyst_id = current_setting('app.analyst_id')::uuid
        )
    );

-- Analysts can only update events they own and that are not yet CLOSED
CREATE POLICY analyst_update_own ON intel_events
    FOR UPDATE
    TO nexus_analyst
    USING (
        analyst_id = current_setting('app.analyst_id')::uuid
        AND status != 'CLOSED'
        AND classification <= (
            SELECT clearance_level FROM analysts
            WHERE analyst_id = current_setting('app.analyst_id')::uuid
        )
    );

-- Ingestion service bypasses RLS (trusted internal role)
CREATE POLICY ingest_service_bypass ON intel_events
    FOR ALL
    TO nexus_ingest_service
    USING (TRUE);

-- ── Audit trigger (fires on INSERT/UPDATE/DELETE) ─────────────
CREATE OR REPLACE FUNCTION fn_audit_trigger()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (
        analyst_id, action, table_name, row_id,
        old_values, new_values, ip_address, session_id
    ) VALUES (
        current_setting('app.analyst_id')::uuid,
        TG_OP,
        TG_TABLE_NAME,
        CASE WHEN TG_OP = 'DELETE' THEN OLD.event_id::text
             ELSE NEW.event_id::text END,
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN TO_JSONB(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN TO_JSONB(NEW) ELSE NULL END,
        inet_client_addr(),
        current_setting('app.session_id', TRUE)
    );
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trig_audit_intel_events
    AFTER INSERT OR UPDATE OR DELETE ON intel_events
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();
