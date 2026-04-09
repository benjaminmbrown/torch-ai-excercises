-- ============================================================
-- NEXUS Intelligence Platform Database Schema
-- PostgreSQL 16 + TimescaleDB + pgvector
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "timescaledb";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Classification levels (ordered enum)
CREATE TYPE classification_level AS ENUM (
    'UNCLASSIFIED', 'CUI', 'SECRET', 'TOP_SECRET', 'TS_SCI'
);

CREATE TYPE threat_tier AS ENUM (
    'INFORMATIONAL', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
);

CREATE TYPE event_status AS ENUM (
    'INGESTED', 'PROCESSING', 'ENRICHED', 'REVIEWED', 'CLOSED'
);

-- ── 1. sources ───────────────────────────────────────────────
CREATE TABLE sources (
    source_id       UUID                  PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name     VARCHAR(120)          NOT NULL UNIQUE,
    source_type     VARCHAR(40)           NOT NULL,   -- OSINT | SIGINT | HUMINT | GEOINT | FININT
    reliability     SMALLINT              NOT NULL CHECK (reliability BETWEEN 1 AND 5),
    classification  classification_level  NOT NULL DEFAULT 'UNCLASSIFIED',
    is_active       BOOLEAN               NOT NULL DEFAULT TRUE,
    api_endpoint    TEXT,
    ingest_schema   JSONB,
    created_at      TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ           NOT NULL DEFAULT NOW()
);

-- ── 2. analysts ──────────────────────────────────────────────
CREATE TABLE analysts (
    analyst_id      UUID                  PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(60)           NOT NULL UNIQUE,
    display_name    VARCHAR(120)          NOT NULL,
    clearance_level classification_level  NOT NULL DEFAULT 'UNCLASSIFIED',
    team_id         UUID,
    is_active       BOOLEAN               NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ           NOT NULL DEFAULT NOW()
);

-- ── 3. intel_events (hypertable — time-partitioned) ──────────
CREATE TABLE intel_events (
    event_id        UUID                  NOT NULL DEFAULT uuid_generate_v4(),
    occurred_at     TIMESTAMPTZ           NOT NULL,
    ingested_at     TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    source_id       UUID                  NOT NULL REFERENCES sources(source_id),
    analyst_id      UUID                  REFERENCES analysts(analyst_id),
    title           TEXT                  NOT NULL,
    summary         TEXT,
    raw_payload     JSONB,
    classification  classification_level  NOT NULL DEFAULT 'UNCLASSIFIED',
    threat_tier     threat_tier           NOT NULL DEFAULT 'INFORMATIONAL',
    status          event_status          NOT NULL DEFAULT 'INGESTED',
    geo_lat         NUMERIC(9,6),
    geo_lon         NUMERIC(9,6),
    geo_region      VARCHAR(80),
    embedding       VECTOR(1024),         -- BGE-large-en-v1.5
    resolved_at     TIMESTAMPTZ,
    PRIMARY KEY (event_id, occurred_at)   -- composite PK for hypertable
);

-- Convert to TimescaleDB hypertable (partition by month)
SELECT create_hypertable(
    'intel_events',
    'occurred_at',
    chunk_time_interval => INTERVAL '1 month'
);

-- ── 4. entities (named entities extracted from events) ────────
CREATE TABLE entities (
    entity_id       UUID                  PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name  TEXT                  NOT NULL,
    entity_type     VARCHAR(40)           NOT NULL,  -- PERSON | ORG | LOCATION | VESSEL | AIRCRAFT
    aliases         TEXT[],
    metadata        JSONB,
    created_at      TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    UNIQUE (canonical_name, entity_type)
);

-- ── 5. event_entities (M:N junction) ─────────────────────────
CREATE TABLE event_entities (
    event_id        UUID                  NOT NULL,
    occurred_at     TIMESTAMPTZ           NOT NULL,
    entity_id       UUID                  NOT NULL REFERENCES entities(entity_id),
    role            VARCHAR(40),           -- SUBJECT | ACTOR | LOCATION | VICTIM
    confidence      NUMERIC(4,3)          CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (event_id, occurred_at, entity_id),
    FOREIGN KEY (event_id, occurred_at) REFERENCES intel_events(event_id, occurred_at)
);

-- ── 6. tags ───────────────────────────────────────────────────
CREATE TABLE tags (
    tag_id          UUID                  PRIMARY KEY DEFAULT uuid_generate_v4(),
    tag_name        VARCHAR(80)           NOT NULL UNIQUE,
    tag_category    VARCHAR(40)           NOT NULL   -- TTPs | DOMAIN | ACTOR | CAMPAIGN
);

CREATE TABLE event_tags (
    event_id        UUID                  NOT NULL,
    occurred_at     TIMESTAMPTZ           NOT NULL,
    tag_id          UUID                  NOT NULL REFERENCES tags(tag_id),
    PRIMARY KEY (event_id, occurred_at, tag_id),
    FOREIGN KEY (event_id, occurred_at) REFERENCES intel_events(event_id, occurred_at)
);

-- ── 7. audit_log ──────────────────────────────────────────────
CREATE TABLE audit_log (
    log_id          BIGINT                GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    logged_at       TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    analyst_id      UUID                  NOT NULL,
    action          VARCHAR(30)           NOT NULL,  -- SELECT | INSERT | UPDATE | DELETE | EXPORT
    table_name      VARCHAR(60)           NOT NULL,
    row_id          TEXT,
    old_values      JSONB,
    new_values      JSONB,
    ip_address      INET,
    session_id      TEXT
);
