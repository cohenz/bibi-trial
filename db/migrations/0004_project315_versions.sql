-- 0004_project315_versions.sql — spec §28: an import never overwrites an
-- event silently; every distinct raw payload is kept with its diff.

CREATE TABLE ntk.project315_event_versions (
  event_id text NOT NULL REFERENCES ntk.project315_events(id) ON DELETE CASCADE,
  payload_sha256 char(64) NOT NULL,
  raw_payload jsonb NOT NULL,
  mapped jsonb NOT NULL,
  source_version_id text REFERENCES ntk.source_versions(id),
  import_run_id uuid REFERENCES ntk.project315_import_runs(id),
  diff jsonb NOT NULL DEFAULT '{}'::jsonb,
  imported_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, payload_sha256)
);

CREATE INDEX project315_event_versions_time_idx ON ntk.project315_event_versions (event_id, imported_at DESC);
