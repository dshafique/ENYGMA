-- 008_action_states.sql
-- An action item is not a checkbox.
--
-- done_at could say only "finished" or "not finished", so everything that was
-- consciously turned down and everything nobody had got to yet looked identical
-- to everything still waiting. A list where declining something and ignoring it
-- are the same gesture is a list that stops being read.
--
-- done_at stays, and stays in step: it is what every existing query reads, and
-- migrations here are additive.

ALTER TABLE recordings ADD COLUMN library_note TEXT;

ALTER TABLE action_items ADD COLUMN state TEXT NOT NULL DEFAULT 'open';
                                        -- open | pending | done | rejected
ALTER TABLE action_items ADD COLUMN state_at TEXT;
ALTER TABLE action_items ADD COLUMN state_note TEXT;

UPDATE action_items SET state = 'done', state_at = done_at WHERE done_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_actions_state ON action_items(state);
