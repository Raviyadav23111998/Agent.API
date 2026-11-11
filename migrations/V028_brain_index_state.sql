-- V028_brain_index_state.sql
-- ════════════════════════════════════════════════════════════════════════════
-- Per-document, per-pillar indexing state for the brain ingestion pipeline.
--
-- Problem this fixes: ingestion did sequential BEST-EFFORT writes to the
-- optional pillars (Elasticsearch, Neo4j, pgvector) and swallowed failures. If a
-- pillar was down or misconfigured at ingest time (e.g. the embedding endpoint
-- not yet wired, or an empty Neo4j password), the document was silently left
-- incomplete forever — no record, no retry, no visibility. (Audit: of 116 docs,
-- only 6 had vector embeddings and 7 reached ES.)
--
-- Fix: make multi-store ingestion EVENTUALLY CONSISTENT + self-healing. Each
-- pillar write records ok/failed/skipped here; a background reconciler re-runs
-- anything not 'ok' (idempotent upserts) with backoff. The back-catalogue heals
-- on deploy, and any future outage heals when the service returns.
--
-- The Postgres document store + full-text (fts_vector) are written ATOMICALLY
-- with the document row, so they are never tracked here — only the optional,
-- separately-written pillars are.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ag_brain.document_index_state (
    doc_id        BIGINT      NOT NULL,                       -- FK → ag_brain.documents.doc_id (bigint)
    pillar        TEXT        NOT NULL,                       -- 'lexical' | 'graph' | 'vector'
    state         TEXT        NOT NULL DEFAULT 'pending',     -- pending | ok | failed | skipped
    attempts      INTEGER     NOT NULL DEFAULT 0,
    last_error    TEXT,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, pillar),
    CONSTRAINT fk_dis_doc FOREIGN KEY (doc_id)
        REFERENCES ag_brain.documents (doc_id) ON DELETE CASCADE
);

-- The reconciler's hot path: rows that need work, ordered by when they are due.
-- Partial index keeps it tiny once most rows are 'ok'/'skipped'.
CREATE INDEX IF NOT EXISTS idx_dis_due
    ON ag_brain.document_index_state (next_retry_at)
    WHERE state IN ('pending', 'failed');

-- ── Seed the existing back-catalogue so the reconciler heals it ──────────────
-- vector: 'ok' where an embedding already exists, else 'pending'.
-- lexical/graph: 'pending' for every doc — re-indexing is an idempotent upsert
-- (ES _id = doc_id; Neo4j MERGE by doc_id), so re-running them is safe even for
-- docs already present in those stores. The reconciler converges them to 'ok'.
-- Guarded: a control/stub DB may have ag_brain.documents without the pgvector
-- `embedding` column — there we still create the table but skip the seed.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'ag_brain' AND table_name = 'documents'
                 AND column_name = 'embedding') THEN
        INSERT INTO ag_brain.document_index_state (doc_id, pillar, state)
        SELECT d.doc_id, p.pillar,
               CASE WHEN p.pillar = 'vector' AND d.embedding IS NOT NULL
                    THEN 'ok' ELSE 'pending' END
        FROM ag_brain.documents d
        CROSS JOIN (VALUES ('lexical'), ('graph'), ('vector')) AS p(pillar)
        ON CONFLICT (doc_id, pillar) DO NOTHING;
    END IF;
END $$;
