-- V018: switch the document embedding column to 768 dimensions.
-- The activated embedding model is nomic-embed-text (768-dim) served by a
-- local Ollama instance — no external embedding provider is available
-- (the chat provider, OpenRouter, has no /embeddings endpoint).
-- Safe: applied while zero rows are embedded. Pair with config
--   llm.embedding_dimensions = 768  (read by DocumentStore.EMBED_DIM).

DROP INDEX IF EXISTS ag_brain.idx_docs_embedding;

-- Any 1536-dim vectors (none expected) cannot be converted — clear first.
UPDATE ag_brain.documents SET embedding = NULL WHERE embedding IS NOT NULL;

ALTER TABLE ag_brain.documents
    ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768);

CREATE INDEX idx_docs_embedding ON ag_brain.documents
    USING hnsw (embedding vector_cosine_ops);
