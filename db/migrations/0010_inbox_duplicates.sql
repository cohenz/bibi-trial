-- 0010_inbox_duplicates.sql — duplicate handling in the intake (operator request 11.10.2026).
-- * 'removed': an intake copy that was deleted from inbox/ because the same bytes are already stored under sources/.
-- * 'possible_duplicate': different bytes but (almost) the same text as a document already in the system; it is held
--   (not copied to sources/, not ingested) until the operator deletes the copy or says it is a different document.
-- * document_fingerprints: text fingerprints of ingested source versions (pages 1, 2 and the last page).
DO $$
DECLARE c text;
BEGIN
  SELECT conname INTO c FROM pg_constraint
   WHERE conrelid = 'ntk.inbox_items'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%discovered%';
  IF c IS NOT NULL THEN
    EXECUTE format('ALTER TABLE ntk.inbox_items DROP CONSTRAINT %I', c);
  END IF;
END $$;
ALTER TABLE ntk.inbox_items ADD CONSTRAINT inbox_items_status_check CHECK (status IN (
  'discovered', 'classified', 'duplicate', 'possible_duplicate', 'removed', 'foreign_case', 'unsupported', 'failed',
  'queued', 'ingested', 'ingest_failed', 'skipped'));
ALTER TABLE ntk.inbox_items ADD COLUMN IF NOT EXISTS removed_at timestamptz;
ALTER TABLE ntk.inbox_items ADD COLUMN IF NOT EXISTS removed_by text;
ALTER TABLE ntk.inbox_items ADD COLUMN IF NOT EXISTS similarity real;

CREATE TABLE IF NOT EXISTS ntk.document_fingerprints (
  source_version_id text PRIMARY KEY REFERENCES ntk.source_versions(id),
  page_count integer NOT NULL,
  fingerprint bigint[] NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_fingerprints_pages_idx ON ntk.document_fingerprints (page_count);
