-- 009_notes_source.sql
-- A meeting he has notes for but no recording of.
--
-- Somebody else's minutes, or a meeting tool's summary, are still a record of
-- something that happened, and belong in Meetings rather than the Library --
-- the Library is context that was already true. What they are not is checkable:
-- there is no audio behind them, so no claim can point at the moment it came
-- from. The interface has to say that rather than let notes and transcripts look
-- alike.

ALTER TABLE recordings ADD COLUMN source_text TEXT;
