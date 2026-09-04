-- What he attached to a message.
--
-- Separate from made_documents, which is what ENYGMA produced. These are what
-- he brought: a photograph of a board, a stack trace, a datasheet. The
-- distinction matters at read time, because his own files are evidence and the
-- app's are output.
--
-- Bytes on disk under data/, like everything else the service writes: the unit
-- grants exactly two writable paths and a sibling directory is read-only at the
-- kernel level however its permissions look.
CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE,
    message_id  INTEGER REFERENCES chat_messages(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'file',   -- image | file
    path        TEXT NOT NULL,                  -- relative to the data directory
    bytes       INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT,
    extracted   TEXT,                           -- text pulled out of a document
    library_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_attachments_thread ON attachments(thread_id, id);
