-- ════════════════════════════════════════════════════════════════════════
-- V027 — Per-tenant service connections (Multi-Tenancy Phase 0)
-- ════════════════════════════════════════════════════════════════════════
-- ADDITIVE ONLY. Introduces ag_system.service_connections — the per-tenant
-- registry that tells THIS tenant's runtime where its separate backing stores
-- live (Elasticsearch index, Neo4j graph, Redis namespace, embeddings).
--
-- This is the "config lives inside the tenant Postgres DB" piece of the
-- SMSystem-style design (see MULTITENANT_MASTER_PLAN.md §4 / D8).
--
--   service_key   'elastic' | 'neo4j' | 'redis' | 'embeddings'
--   config_json   non-secret coordinates (url, index, db, namespace, model)
--   secret_enc    Fernet-encrypted secret (api_key / password), nullable
--   is_enabled    arm on/off (brain degrades gracefully when disabled)
--
-- Seeds the CURRENT shared infra as the 'default' tenant so single-tenant
-- behaviour is unchanged (backward compatible — Phase 0 has no runtime wiring).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS ag_system.service_connections (
    service_key   VARCHAR(40)  PRIMARY KEY,
    config_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    secret_enc    TEXT,
    is_enabled    BOOLEAN      NOT NULL DEFAULT TRUE,
    status        VARCHAR(20)  NOT NULL DEFAULT 'unverified',
    description   TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ag_system.service_connections IS
  'Per-tenant backing-store coordinates (ES index, Neo4j, Redis, embeddings). '
  'One row per service. Secrets Fernet-encrypted in secret_enc.';

-- Seed the existing shared infra as this (default) tenant's stores.
-- ON CONFLICT DO NOTHING keeps re-runs and pre-seeded tenants safe.
INSERT INTO ag_system.service_connections (service_key, config_json, is_enabled, description)
VALUES
    ('elastic',
     '{"url": "http://localhost:9200", "index": "brain"}'::jsonb,
     TRUE,  'Lexical/BM25 — separate index per tenant (brain_<id>); default uses "brain".'),
    ('neo4j',
     '{"uri": "bolt://localhost:7687", "db": "neo4j", "user": "neo4j", "scheme": "shared"}'::jsonb,
     TRUE,  'Graph — Community shared graph keyed by tenant_id (Mode C).'),
    ('redis',
     '{"url": "redis://localhost:6379/0", "namespace": "ag:default"}'::jsonb,
     TRUE,  'Cross-worker primitives — namespaced ag:<id>:*.'),
    ('embeddings',
     '{"provider": "ollama", "model": "nomic-embed-text", "endpoint": "http://localhost:11434"}'::jsonb,
     TRUE,  'Dense vectors stored in this tenant''s Postgres (pgvector); compute shared.')
ON CONFLICT (service_key) DO NOTHING;

COMMIT;

-- Verify (manual):
--   SELECT service_key, config_json->>'index' AS idx, config_json->>'namespace' AS ns,
--          is_enabled FROM ag_system.service_connections ORDER BY service_key;
