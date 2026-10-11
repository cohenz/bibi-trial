-- 0008_reparse.sql — re-parsing a source version with a newer parser.
-- Citation units are immutable and never deleted (published citations must keep resolving), so a re-parse marks the
-- units and Q/A exchanges it no longer produces as superseded. Lookups by id still find them; listings, search,
-- transcripts and new AI layers use only current rows. Chunks are derived data and are simply rebuilt.
ALTER TABLE ntk.source_units ADD COLUMN superseded_at timestamptz;
ALTER TABLE ntk.qa_exchanges ADD COLUMN superseded_at timestamptz;
CREATE INDEX source_units_current_idx ON ntk.source_units (source_version_id, unit_ordinal) WHERE superseded_at IS NULL;
CREATE INDEX qa_exchanges_current_idx ON ntk.qa_exchanges (hearing_id) WHERE superseded_at IS NULL;

CREATE OR REPLACE VIEW ntk.public_source_units AS
  SELECT su.*
  FROM ntk.source_units su
  JOIN ntk.source_versions sv ON sv.id = su.source_version_id
  WHERE sv.publication_state = 'published' AND su.superseded_at IS NULL;
