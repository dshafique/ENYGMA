-- The evidence, separately from the headline.
--
-- A folded suggestion shows only its summary line, and the whole point of
-- folding it is that the shut state carries a subject and no argument. Packing
-- the reasoning into that line put two sentences on it and undid the fold: he
-- was reading the case for a thing before deciding to read about the thing.
--
-- So the headline is short enough to scan shut, and the evidence lives in the
-- body where it belongs, next to the citation that backs it.
ALTER TABLE suggestions ADD COLUMN why TEXT;
