-- 0002_operations.sql — operational tables and additive columns required by
-- the build brief (uploads, staged jobs, audit, model registry, answers,
-- corpus versions, webhooks, dead letters) and immutability guards.
-- All changes are additive; see ADR-0010.

-- ---------------------------------------------------------------- sources
ALTER TABLE ntk.source_documents
  ADD COLUMN default_court_record_status ntk.court_record_status NOT NULL DEFAULT 'unknown',
  ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ntk.source_versions
  ADD COLUMN size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
  ADD COLUMN s3_bucket text,
  ADD COLUMN s3_key text,
  ADD COLUMN s3_version_id text,
  ADD COLUMN s3_etag text,
  ADD COLUMN extractor_version text,
  ADD COLUMN synthetic_lines boolean NOT NULL DEFAULT false,
  ADD COLUMN court_record_status ntk.court_record_status NOT NULL DEFAULT 'unknown',
  ADD COLUMN publication_state text NOT NULL DEFAULT 'draft'
    CHECK (publication_state IN ('draft','published','withdrawn')),
  ADD COLUMN publication_changed_at timestamptz,
  ADD COLUMN publication_changed_by text,
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX source_versions_doc_idx ON ntk.source_versions (document_id, retrieved_at DESC);

-- bytes are immutable: a change of content is a new SourceVersion (spec §24)
CREATE OR REPLACE FUNCTION ntk.forbid_source_version_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
     OR NEW.document_id IS DISTINCT FROM OLD.document_id
     OR NEW.id IS DISTINCT FROM OLD.id THEN
    RAISE EXCEPTION 'source_versions are immutable (id %); create a new version', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER source_versions_immutable
  BEFORE UPDATE ON ntk.source_versions
  FOR EACH ROW EXECUTE FUNCTION ntk.forbid_source_version_mutation();

CREATE OR REPLACE FUNCTION ntk.forbid_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows cannot be deleted', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER source_versions_no_delete BEFORE DELETE ON ntk.source_versions
  FOR EACH ROW EXECUTE FUNCTION ntk.forbid_delete();

-- ---------------------------------------------------------------- units
ALTER TABLE ntk.source_units
  ADD COLUMN turn_key text,
  ADD COLUMN turn_part integer NOT NULL DEFAULT 0 CHECK (turn_part >= 0),
  ADD COLUMN speaker_role text,
  ADD COLUMN speaker_side text,
  ADD COLUMN witness_label text,
  ADD COLUMN synthetic_lines boolean NOT NULL DEFAULT false,
  ADD COLUMN search_terms text[] NOT NULL DEFAULT '{}',
  ADD COLUMN char_ngrams text[] NOT NULL DEFAULT '{}',
  ADD COLUMN normalizer_version text,
  ADD COLUMN flags text[] NOT NULL DEFAULT '{}';

CREATE INDEX source_units_terms_idx ON ntk.source_units USING gin (search_terms);
CREATE INDEX source_units_turn_idx ON ntk.source_units (turn_key, turn_part);
CREATE INDEX source_units_hearing_idx ON ntk.source_units (hearing_id, unit_ordinal);

-- citation location and raw text are immutable; normalisation may be refreshed
CREATE OR REPLACE FUNCTION ntk.forbid_source_unit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.raw_text IS DISTINCT FROM OLD.raw_text
     OR NEW.page_no IS DISTINCT FROM OLD.page_no
     OR NEW.line_start IS DISTINCT FROM OLD.line_start
     OR NEW.line_end IS DISTINCT FROM OLD.line_end
     OR NEW.source_version_id IS DISTINCT FROM OLD.source_version_id
     OR NEW.unit_ordinal IS DISTINCT FROM OLD.unit_ordinal THEN
    RAISE EXCEPTION 'source_units citation fields are immutable (id %)', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER source_units_immutable
  BEFORE UPDATE ON ntk.source_units
  FOR EACH ROW EXECUTE FUNCTION ntk.forbid_source_unit_mutation();

CREATE TRIGGER source_units_no_delete BEFORE DELETE ON ntk.source_units
  FOR EACH ROW EXECUTE FUNCTION ntk.forbid_delete();

-- ---------------------------------------------------------------- hearings / entities
ALTER TABLE ntk.hearings
  ADD COLUMN judges text[] NOT NULL DEFAULT '{}',
  ADD COLUMN witnesses text[] NOT NULL DEFAULT '{}',
  ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ntk.entities
  ADD COLUMN role_types text[] NOT NULL DEFAULT '{}',
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ADD CONSTRAINT entities_type_name_uq UNIQUE (entity_type, canonical_name);

CREATE INDEX entities_aliases_idx ON ntk.entities USING gin (aliases);

-- ---------------------------------------------------------------- exchanges
ALTER TABLE ntk.qa_exchanges
  ADD COLUMN asker_label text,
  ADD COLUMN asker_side text,
  ADD COLUMN witness_label text,
  ADD COLUMN public_wording text,
  ADD COLUMN flags text[] NOT NULL DEFAULT '{}',
  ADD COLUMN rule text,
  ADD COLUMN parser_version text,
  ADD COLUMN relation_model_run_id uuid REFERENCES ntk.model_runs(id);

CREATE INDEX qa_exchanges_hearing_idx ON ntk.qa_exchanges (hearing_id);

-- ---------------------------------------------------------------- chunks
ALTER TABLE ntk.retrieval_chunks
  ADD COLUMN hearing_id text REFERENCES ntk.hearings(id),
  ADD COLUMN search_terms text[] NOT NULL DEFAULT '{}',
  ADD COLUMN char_ngrams text[] NOT NULL DEFAULT '{}',
  ADD COLUMN examination_phases text[] NOT NULL DEFAULT '{}',
  ADD COLUMN speakers text[] NOT NULL DEFAULT '{}',
  ADD COLUMN court_record_status ntk.court_record_status NOT NULL DEFAULT 'unknown',
  ADD COLUMN embedded_at timestamptz;

CREATE INDEX retrieval_chunks_terms_idx ON ntk.retrieval_chunks USING gin (search_terms);
CREATE INDEX retrieval_chunks_ngrams_idx ON ntk.retrieval_chunks USING gin (char_ngrams);
CREATE INDEX retrieval_chunk_members_unit_idx ON ntk.retrieval_chunk_members (source_unit_id);

-- ---------------------------------------------------------------- claims / evidence
ALTER TABLE ntk.claims
  ADD COLUMN slug text UNIQUE,
  ADD COLUMN thesis_code text,
  ADD COLUMN sensitivity text[] NOT NULL DEFAULT '{}';

ALTER TABLE ntk.claim_versions
  ADD COLUMN claim_type text,
  ADD COLUMN disclosure text,
  ADD COLUMN created_by text;

ALTER TABLE ntk.evidence_items
  ADD COLUMN attribution text,
  ADD COLUMN exchange_id text REFERENCES ntk.qa_exchanges(id),
  ADD COLUMN model_run_id uuid REFERENCES ntk.model_runs(id);

ALTER TABLE ntk.judicial_statements
  ADD COLUMN statement_date date,
  ADD COLUMN classifier_model_run_id uuid REFERENCES ntk.model_runs(id),
  ADD COLUMN candidate_source text,
  ADD COLUMN reviewed_by text,
  ADD COLUMN reviewed_at timestamptz;

ALTER TABLE ntk.case_events
  ADD COLUMN external_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN created_by text;

-- ---------------------------------------------------------------- Project 315
ALTER TABLE ntk.project315_events
  ADD COLUMN description text,
  ADD COLUMN persons text[] NOT NULL DEFAULT '{}',
  ADD COLUMN court_record_status ntk.court_record_status NOT NULL DEFAULT 'external',
  ADD COLUMN in_court_record boolean GENERATED ALWAYS AS (
    court_record_status IN ('filed','admitted','marked_for_identification','referenced_in_court')
  ) STORED,
  ADD COLUMN raw_payload_sha256 char(64),
  ADD COLUMN parser_version text,
  ADD COLUMN import_source text,
  ADD COLUMN synthetic boolean NOT NULL DEFAULT false,
  ADD COLUMN previous_payload_sha256 char(64),
  ADD CONSTRAINT p315_verification_ck CHECK (
    independent_verification_status IN ('unreviewed','source_checked','transcript_confirmed','contradicted','inconclusive')
  );

CREATE TABLE ntk.project315_event_mentions (
  id bigserial PRIMARY KEY,
  event_id text NOT NULL REFERENCES ntk.project315_events(id) ON DELETE CASCADE,
  mention_type text NOT NULL CHECK (mention_type IN ('court','witness')),
  source_unit_id text REFERENCES ntk.source_units(id),
  entity_id uuid REFERENCES ntk.entities(id),
  note text,
  CHECK (source_unit_id IS NOT NULL OR entity_id IS NOT NULL),
  UNIQUE NULLS NOT DISTINCT (event_id, mention_type, source_unit_id, entity_id)
);

CREATE TABLE ntk.project315_import_runs (
  id uuid PRIMARY KEY,
  source text NOT NULL,
  payload_sha256 char(64) NOT NULL,
  parser_version text NOT NULL,
  imported_count integer NOT NULL DEFAULT 0,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (payload_sha256, parser_version)
);

-- ---------------------------------------------------------------- uploads (S3 presign)
CREATE TABLE ntk.uploads (
  id uuid PRIMARY KEY,
  s3_bucket text NOT NULL,
  s3_key text NOT NULL UNIQUE,
  filename text NOT NULL,
  mime_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  expected_sha256 char(64) NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','uploaded','consumed','expired','rejected')),
  requested_by text NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- jobs
ALTER TABLE ntk.ingestion_jobs
  ADD COLUMN document_id text REFERENCES ntk.source_documents(id),
  ADD COLUMN upload_id uuid REFERENCES ntk.uploads(id),
  ADD COLUMN requested_by text,
  ADD COLUMN attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN dead_lettered boolean NOT NULL DEFAULT false,
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN target_stages text[] NOT NULL DEFAULT '{}';

CREATE TABLE ntk.ingestion_job_stages (
  job_id uuid NOT NULL REFERENCES ntk.ingestion_jobs(id) ON DELETE CASCADE,
  stage text NOT NULL,
  seq integer NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','succeeded','failed','skipped')),
  attempts integer NOT NULL DEFAULT 0,
  checkpoint jsonb,
  output jsonb,
  error jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  PRIMARY KEY (job_id, stage)
);

CREATE TABLE ntk.dead_letters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid REFERENCES ntk.ingestion_jobs(id),
  task_name text NOT NULL,
  payload jsonb NOT NULL,
  error jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

-- ---------------------------------------------------------------- models
ALTER TABLE ntk.model_runs
  ADD COLUMN role text,
  ADD COLUMN temperature numeric(4,3),
  ADD COLUMN status text NOT NULL DEFAULT 'succeeded'
    CHECK (status IN ('succeeded','invalid_output','provider_error','rejected_by_gate')),
  ADD COLUMN validation_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN output_hash char(64),
  ADD COLUMN input_source_ids text[] NOT NULL DEFAULT '{}',
  ADD COLUMN duration_ms integer,
  ADD COLUMN error jsonb,
  ADD COLUMN registry_id text;

CREATE INDEX model_runs_cache_idx ON ntk.model_runs (task_type, prompt_version, model_version, input_hash);

CREATE TABLE ntk.model_registry (
  id text PRIMARY KEY,
  role text NOT NULL CHECK (role IN ('extractor','mapper','judicial_classifier','verifier','writer','qa_relation','embedder')),
  provider text NOT NULL,
  model_family text NOT NULL,
  model_id text NOT NULL,
  model_version text,
  context_limit integer,
  price_snapshot jsonb,
  benchmark jsonb,
  is_lite boolean NOT NULL DEFAULT false,
  allowed_for_final boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT (is_lite AND allowed_for_final))
);

-- ---------------------------------------------------------------- artifacts / review / publication
ALTER TABLE ntk.generated_artifacts
  ADD COLUMN content_sha256 char(64),
  ADD COLUMN verifier_run_id uuid REFERENCES ntk.model_runs(id),
  ADD COLUMN gate_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN risk_flags text[] NOT NULL DEFAULT '{}',
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX generated_artifacts_content_uq
  ON ntk.generated_artifacts (artifact_type, object_type, object_id, content_sha256);

ALTER TABLE ntk.review_tasks
  ADD COLUMN status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','approved','rejected','changes_requested','cancelled')),
  ADD COLUMN reason text,
  ADD COLUMN decided_by text,
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX review_tasks_open_uq ON ntk.review_tasks (object_type, object_id) WHERE status = 'open';

CREATE TABLE ntk.corpus_versions (
  seq bigserial PRIMARY KEY,
  id text NOT NULL UNIQUE,
  reason text NOT NULL,
  actor text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO ntk.corpus_versions (id, reason, actor) VALUES ('cv-000001', 'initial empty corpus', 'migration');

-- ---------------------------------------------------------------- answers (Ask the Trial)
CREATE TABLE ntk.answers (
  id uuid PRIMARY KEY,
  slug text NOT NULL UNIQUE,
  question text NOT NULL,
  normalized_question text NOT NULL,
  locale text NOT NULL DEFAULT 'he',
  as_of timestamptz NOT NULL,
  corpus_version text NOT NULL,
  prompt_version text NOT NULL,
  model_version text NOT NULL,
  answer_status text NOT NULL,
  envelope jsonb NOT NULL,
  retrieval_ids text[] NOT NULL DEFAULT '{}',
  gate_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  model_run_id uuid REFERENCES ntk.model_runs(id),
  client_request_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (normalized_question, as_of, corpus_version, prompt_version, model_version, locale)
);

CREATE INDEX answers_question_idx ON ntk.answers (normalized_question, created_at DESC);

-- ---------------------------------------------------------------- audit (append-only)
CREATE TABLE ntk.audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  object_type text NOT NULL,
  object_id text,
  request_id text,
  ip_hash text,
  details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX audit_events_object_idx ON ntk.audit_events (object_type, object_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION ntk.audit_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON ntk.audit_events
  FOR EACH ROW EXECUTE FUNCTION ntk.audit_append_only();

-- ---------------------------------------------------------------- webhooks (outbox)
CREATE TABLE ntk.webhook_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered','failed')),
  attempts integer NOT NULL DEFAULT 0,
  last_error text,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz
);

CREATE INDEX webhook_outbox_pending_idx ON ntk.webhook_outbox (next_attempt_at) WHERE status = 'pending';

-- ---------------------------------------------------------------- public read models
-- Everything the public API and the public retriever may read goes through
-- these views; they encode the publication boundary in one place.
CREATE VIEW ntk.public_source_units AS
  SELECT su.*
  FROM ntk.source_units su
  JOIN ntk.source_versions sv ON sv.id = su.source_version_id
  WHERE sv.publication_state = 'published';

CREATE VIEW ntk.public_chunks AS
  SELECT rc.*
  FROM ntk.retrieval_chunks rc
  JOIN ntk.source_versions sv ON sv.id = rc.source_version_id
  WHERE sv.publication_state = 'published';

CREATE VIEW ntk.public_artifacts AS
  SELECT ga.*, p.slug, p.canonical_url, p.knowledge_version, p.published_at, p.id AS publication_id
  FROM ntk.generated_artifacts ga
  JOIN ntk.publications p ON p.artifact_id = ga.id AND p.unpublished_at IS NULL
  WHERE ga.review_state = 'published';
