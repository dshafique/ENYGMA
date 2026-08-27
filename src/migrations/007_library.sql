-- 007_library.sql
-- The library: documents and notes ENYGMA can draw on when it answers.
--
-- A meeting is a record of something that happened. A document is context that
-- was already true: a spec, a runbook, an onboarding note, a paper. Chat answered
-- only from the glossary and whatever the model already knew, which meant it knew
-- nothing about the operator's own material.
--
-- Retrieval is SQLite's own full-text index rather than vector embeddings. For
-- one person with tens of documents, keyword search with stemming finds the right
-- passage, costs nothing per query, needs no API key, works when the model is
-- unreachable, and can be reasoned about when it returns the wrong thing.
-- Embeddings are the upgrade if recall ever proves the weak link.

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'note',   -- note | file
    source_name   TEXT,
    mime          TEXT,
    sha256        TEXT,
    bytes         INTEGER,
    body          TEXT NOT NULL,
    words         INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    added_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256)
    WHERE sha256 IS NOT NULL;

-- Passages, not whole documents. An answer should be able to point at the
-- paragraph it came from, and a whole document is too much to put in a prompt.
CREATE TABLE IF NOT EXISTS document_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    text          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id, idx);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(
    text,
    content='document_chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- The index follows the table rather than being rebuilt by hand.
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO chunk_search(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON document_chunks BEGIN
    INSERT INTO chunk_search(chunk_search, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO chunk_search(chunk_search, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunk_search(rowid, text) VALUES (new.id, new.text);
END;
