-- Initial schema for the Legal AI Hub on Azure Database for PostgreSQL.
--
-- Replaces the on-disk Chroma stores (chromadb/, vector_store/) that lived on
-- the VM in Milestone 3. Every chunk embedding now lives in `chunks`, and
-- every uploaded file has a row in `uploads` pointing at its blob.
--
-- The `vector` extension must be allow-listed on the server first
-- (server parameter azure.extensions = VECTOR).

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per logical index: a feature's seed corpus (e.g. contracts_db) or
-- one uploaded file (upload_<name>_<hash>).
CREATE TABLE collections (
    id              BIGSERIAL   PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,
    embedding_model TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per text chunk. Embeddings are all-MiniLM-L6-v2 (384 dimensions,
-- L2-normalised), searched with cosine distance.
CREATE TABLE chunks (
    collection_id BIGINT      NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    chunk_id      TEXT        NOT NULL,
    filename      TEXT        NOT NULL,
    page          INTEGER,
    content       TEXT        NOT NULL,
    metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    embedding     vector(384) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, chunk_id)
);

-- Every search is scoped to one collection and usually to a set of files.
-- The corpora are small enough that an exact scan within that scope is
-- faster to keep correct than an approximate index with filters.
CREATE INDEX chunks_collection_filename_idx ON chunks (collection_id, filename);

-- Ledger of files uploaded through the app. The bytes live in Blob Storage
-- at `blob_name`; the parsed chunks live in `collection_name`.
CREATE TABLE uploads (
    id              BIGSERIAL   PRIMARY KEY,
    feature         TEXT        NOT NULL,
    filename        TEXT        NOT NULL,
    blob_name       TEXT        NOT NULL UNIQUE,
    content_type    TEXT,
    size_bytes      BIGINT      NOT NULL CHECK (size_bytes >= 0),
    sha256          CHAR(64)    NOT NULL,
    collection_name TEXT        NOT NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX uploads_feature_uploaded_at_idx ON uploads (feature, uploaded_at DESC);
