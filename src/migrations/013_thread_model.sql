-- Which model answers in this thread.
--
-- Per thread rather than per message, because Chat has memory: half a
-- conversation reasoned by one model and half by another is a conversation
-- neither of them is really having.
--
-- Nullable on purpose. NULL means "whatever the default is now", so changing
-- ENYGMA_CHAT_DEFAULT moves every thread he never expressed an opinion about,
-- and leaves alone every one he did.
ALTER TABLE chat_threads ADD COLUMN model TEXT;
