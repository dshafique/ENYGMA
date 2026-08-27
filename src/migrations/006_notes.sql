-- 006_notes.sql
-- A non-fatal remark about a recording.
--
-- 'failure' means the recording is unusable. There was no way to say "this
-- worked, and here is something you need to know about how" -- so a truncated
-- transcript had to be either a total failure or silently incomplete, and
-- silently incomplete is the worse of the two.

ALTER TABLE recordings ADD COLUMN note TEXT;
