-- V020: parent-child chunking for precise dense retrieval.
-- Each document is split into small overlapping child chunks; the chunk
-- embedding is what vector search matches, then we return the PARENT document
-- for full context. Dimension matches V018 (768, nomic-embed-text).

CREATE TABLE IF NOT EXISTS ag_brain.document_chunks (
    chunk_id     BIGSERIAL PRIMARY KEY,
    doc_id       BIGINT NOT NULL REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    content      TEXT NOT NULL,
    token_count  INT NOT NULL DEFAULT 0,
    embedding    vector(768),
    embedding_model VARCHAR(100),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE (doc_id, chunk_index)
);

-- HNSW cosine index for fast KNN over chunk embeddings.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON ag_brain.document_chunks USING hnsw (embedding vector_cosine_ops);

-- Fast parent lookup + scoped deletes/backfill.
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON ag_brain.document_chunks(doc_id);
