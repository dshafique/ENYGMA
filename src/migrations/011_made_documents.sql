-- Files ENYGMA made, as opposed to files he gave it.
--
-- Separate from `documents` (the Library) on purpose. A Library entry is text
-- to be searched and quoted; this is a real .docx or .pdf on disk with bytes
-- and a mime type, and the two have almost nothing in common beyond a title.
-- The link between them is library_document_id: the file is stored here, its
-- prose is added to the Library, and asking about it next month finds it.
--
-- Bytes live on disk rather than in the row. A slide deck is megabytes, SQLite
-- would carry it in every SELECT that touched the table, and the backup script
-- already copies the data directory.
CREATE TABLE IF NOT EXISTS made_documents (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id            INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE,
    message_id           INTEGER REFERENCES chat_messages(id) ON DELETE SET NULL,
    format               TEXT NOT NULL,          -- md | html | docx | pptx | xlsx | pdf
    style                TEXT NOT NULL DEFAULT 'plain',
    title                TEXT NOT NULL,
    filename             TEXT NOT NULL,
    mime                 TEXT NOT NULL,
    path                 TEXT NOT NULL,          -- relative to the data directory
    bytes                INTEGER NOT NULL DEFAULT 0,
    sha256               TEXT,
    brief                TEXT,                   -- what he actually asked for
    structure            TEXT,                   -- the JSON it was built from
    library_document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_made_documents_thread
    ON made_documents(thread_id, id);
