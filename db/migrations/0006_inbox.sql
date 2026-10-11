-- 0006_inbox.sql — bulk/daily intake from the object-store inbox (inbox/ prefix).
-- Every object found there gets one row per (key, etag); the row records what the
-- document was classified as, whether it duplicates an existing source, and the
-- ingestion job that processed it. Rows are the audit trail of the intake.

ALTER TYPE ntk.source_type ADD VALUE IF NOT EXISTS 'response';
ALTER TYPE ntk.source_type ADD VALUE IF NOT EXISTS 'notice';
ALTER TYPE ntk.source_type ADD VALUE IF NOT EXISTS 'affidavit';

CREATE TABLE ntk.inbox_items (
  id uuid PRIMARY KEY,
  object_key text NOT NULL,
  etag text NOT NULL DEFAULT '',
  size_bytes bigint NOT NULL,
  last_modified timestamptz,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  scan_id uuid,
  status text NOT NULL DEFAULT 'discovered' CHECK (status IN (
    'discovered', 'classified', 'duplicate', 'foreign_case', 'unsupported', 'failed',
    'queued', 'ingested', 'ingest_failed', 'skipped')),
  content_sha256 char(64),
  source_key text,
  doc_kind text,
  classification jsonb NOT NULL DEFAULT '{}'::jsonb,
  duplicate_of text,
  job_id uuid REFERENCES ntk.ingestion_jobs(id),
  error jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (object_key, etag)
);

CREATE INDEX inbox_items_status_idx ON ntk.inbox_items (status, doc_kind);
CREATE INDEX inbox_items_sha_idx ON ntk.inbox_items (content_sha256);

CREATE TABLE ntk.inbox_scans (
  id uuid PRIMARY KEY,
  trigger text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  stats jsonb NOT NULL DEFAULT '{}'::jsonb,
  error jsonb
);
