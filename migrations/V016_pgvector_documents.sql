-- V016: Dense vector retrieval (pgvector) for the brain — roadmap section C.
--
-- Adds a semantic embedding column to ag_brain.documents so retrieval can do
-- vector (cosine) search and fuse it with the existing BM25/FTS ranking via
-- Reciprocal Rank Fusion. Dormant until an embedding model is configured
-- (llm.embedding_model / llm.embedding_base_url / llm.embedding_api_key) —
-- the column simply stays NULL and retrieval falls back to FTS, so this
-- migration is safe to apply before embeddings are switched on.
--
-- DIMENSION: 1536 matches text-embedding-3-small (and 3-large truncated).
-- Changing to a model with a different dimension requires a new migration
-- to ALTER the column type; the embedding writer guards against length
-- mismatches and skips (logs) rather than erroring.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE ag_brain.documents
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

ALTER TABLE ag_brain.documents
    ADD COLUMN IF NOT EXISTS embedding_model varchar(100);

-- HNSW index for fast approximate cosine KNN. Built on the (initially empty)
-- column; fills in as rows are embedded. cosine ops match the <=> operator
-- used by DocumentStore.search_vector.
CREATE INDEX IF NOT EXISTS idx_docs_embedding
    ON ag_brain.documents
    USING hnsw (embedding vector_cosine_ops);
