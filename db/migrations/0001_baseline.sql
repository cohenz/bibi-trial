-- 0001_baseline.sql — spec v2.1 §25, PostgreSQL 16.
-- Deviation from the spec text (ADR-0003): the retrieval_chunks.embedding
-- column and its HNSW index are created by migration 0003, parameterised by
-- NTK_EMBEDDING_DIM. pgvector's HNSW index supports at most 2,000 dimensions
-- for `vector`; the spec default of 3,072 therefore uses `halfvec` (pgvector
-- >= 0.7, up to 4,000 dimensions). Everything else is the spec baseline.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS ntk;

CREATE TYPE ntk.source_type AS ENUM (
  'indictment','protocol','decision','motion','exhibit',
  'article','recording','regulatory','project315','other'
);

CREATE TYPE ntk.court_record_status AS ENUM (
  'filed','admitted','marked_for_identification','referenced_in_court',
  'excluded','not_filed','external','unknown'
);

CREATE TYPE ntk.review_state AS ENUM (
  'draft','machine_verified','human_review_required','approved','rejected','published','superseded'
);

CREATE TYPE ntk.claim_status AS ENUM (
  'unverified','source_backed','multi_source_supported','court_recognized',
  'court_determined','disputed','partially_supported','weakened',
  'rejected','pending','superseded'
);

CREATE TYPE ntk.evidence_direction AS ENUM ('supports','weakens','contextual','neutral');

CREATE TYPE ntk.judicial_level AS ENUM (
  'question_or_comment','interim_observation','procedural_decision','substantive_ruling'
);

CREATE TYPE ntk.examination_phase AS ENUM (
  'preliminary','direct','cross','redirect','recross','court_questions','argument','unknown'
);

CREATE TYPE ntk.answer_relation AS ENUM (
  'affirms','qualified_affirmation','denies','does_not_know','nonresponsive','ambiguous'
);

CREATE TYPE ntk.outcome_type AS ENUM (
  'verdict','plea_deal','withdrawal','dismissal','pardon_granted',
  'pardon_denied','stay','mistrial','other'
);

CREATE OR REPLACE FUNCTION ntk.stable_id(prefix text, parts text[])
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT prefix || '_' || substr(
    encode(digest(array_to_string(parts, E'\x1f'), 'sha256'), 'hex'), 1, 26
  );
$$;

CREATE TABLE ntk.cases (
  id text PRIMARY KEY,
  court_case_number text NOT NULL UNIQUE,
  title text NOT NULL,
  court_name text NOT NULL,
  opened_on date,
  closed_on date,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ntk.source_documents (
  id text PRIMARY KEY,
  case_id text REFERENCES ntk.cases(id),
  canonical_title text NOT NULL,
  source_type ntk.source_type NOT NULL,
  authority_tier smallint NOT NULL CHECK (authority_tier BETWEEN 1 AND 5),
  source_owner text NOT NULL,
  source_stance text,
  canonical_url text,
  language text NOT NULL DEFAULT 'he',
  legal_access_notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ntk.source_versions (
  id text PRIMARY KEY,
  document_id text NOT NULL REFERENCES ntk.source_documents(id),
  content_sha256 char(64) NOT NULL,
  retrieved_at timestamptz NOT NULL,
  published_at timestamptz,
  mime_type text NOT NULL,
  object_uri text,
  source_url text,
  parser_version text,
  page_count integer CHECK (page_count IS NULL OR page_count > 0),
  supersedes_id text REFERENCES ntk.source_versions(id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (document_id, content_sha256)
);

CREATE TABLE ntk.hearings (
  id text PRIMARY KEY,
  case_id text NOT NULL REFERENCES ntk.cases(id),
  hearing_date date NOT NULL,
  location text,
  phase text,
  source_version_id text REFERENCES ntk.source_versions(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (case_id, hearing_date, source_version_id)
);

CREATE TABLE ntk.entities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type text NOT NULL CHECK (entity_type IN ('person','organization','place','other')),
  canonical_name text NOT NULL,
  aliases text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE ntk.hearing_roles (
  hearing_id text NOT NULL REFERENCES ntk.hearings(id) ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES ntk.entities(id),
  role_type text NOT NULL,
  side text,
  valid_during tstzrange,
  PRIMARY KEY (hearing_id, entity_id, role_type)
);

CREATE TABLE ntk.source_units (
  id text PRIMARY KEY,
  source_version_id text NOT NULL REFERENCES ntk.source_versions(id),
  hearing_id text REFERENCES ntk.hearings(id),
  unit_ordinal integer NOT NULL CHECK (unit_ordinal >= 0),
  page_no integer NOT NULL CHECK (page_no > 0),
  line_start integer NOT NULL CHECK (line_start > 0),
  line_end integer NOT NULL CHECK (line_end >= line_start),
  speaker_entity_id uuid REFERENCES ntk.entities(id),
  speaker_label text,
  examination_phase ntk.examination_phase NOT NULL DEFAULT 'unknown',
  unit_type text NOT NULL CHECK (unit_type IN ('speech_turn','question','answer','decision','caption','other')),
  raw_text text NOT NULL,
  normalized_text text NOT NULL,
  court_record_status ntk.court_record_status NOT NULL DEFAULT 'unknown',
  parser_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_version_id, page_no, line_start, line_end, unit_ordinal)
);

CREATE INDEX source_units_location_idx
  ON ntk.source_units (source_version_id, page_no, line_start);

CREATE INDEX source_units_trgm_idx
  ON ntk.source_units USING gin (normalized_text gin_trgm_ops);

CREATE TABLE ntk.qa_exchanges (
  id text PRIMARY KEY,
  hearing_id text NOT NULL REFERENCES ntk.hearings(id),
  question_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  answer_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  asker_entity_id uuid REFERENCES ntk.entities(id),
  witness_entity_id uuid REFERENCES ntk.entities(id),
  phase ntk.examination_phase NOT NULL,
  answer_relation ntk.answer_relation NOT NULL,
  interpreted_proposition text,
  confidence numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  UNIQUE (question_unit_id, answer_unit_id)
);

CREATE TABLE ntk.retrieval_chunks (
  id text PRIMARY KEY,
  source_version_id text NOT NULL REFERENCES ntk.source_versions(id),
  chunk_profile text NOT NULL,
  token_count integer NOT NULL CHECK (token_count BETWEEN 1 AND 2000),
  raw_text text NOT NULL,
  normalized_text text NOT NULL,
  hebrew_lemmas text[] NOT NULL DEFAULT '{}',
  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(normalized_text, ''))
  ) STORED,
  -- embedding: added by migration 0003 (ADR-0003)
  embedding_model text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_version_id, id)
);

CREATE TABLE ntk.retrieval_chunk_members (
  chunk_id text NOT NULL REFERENCES ntk.retrieval_chunks(id) ON DELETE CASCADE,
  source_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  position integer NOT NULL CHECK (position >= 0),
  PRIMARY KEY (chunk_id, source_unit_id),
  UNIQUE (chunk_id, position)
);

CREATE INDEX retrieval_chunks_tsv_idx ON ntk.retrieval_chunks USING gin (search_tsv);

CREATE INDEX retrieval_chunks_trgm_idx
  ON ntk.retrieval_chunks USING gin (normalized_text gin_trgm_ops);

-- retrieval_chunks_embedding_idx: created by migration 0003 (ADR-0003)

CREATE TABLE ntk.layer_a_objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type text NOT NULL CHECK (object_type IN ('hearing','witness','topic','decision','timeline')),
  object_key text NOT NULL,
  UNIQUE (object_type, object_key)
);

CREATE TABLE ntk.layer_a_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id uuid NOT NULL REFERENCES ntk.layer_a_objects(id),
  schema_version text NOT NULL,
  short_summary text NOT NULL,
  long_summary text,
  payload jsonb NOT NULL,
  source_unit_ids text[] NOT NULL,
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  model_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  supersedes_id uuid REFERENCES ntk.layer_a_versions(id)
);

CREATE TABLE ntk.claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id text NOT NULL REFERENCES ntk.cases(id),
  canonical_question text NOT NULL,
  claim_type text NOT NULL,
  originator_entity_id uuid REFERENCES ntk.entities(id),
  stance text,
  parent_claim_id uuid REFERENCES ntk.claims(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ntk.claim_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id uuid NOT NULL REFERENCES ntk.claims(id),
  title text NOT NULL,
  claim_text text NOT NULL,
  editorial_priority integer NOT NULL DEFAULT 0,
  confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  source_unit_ids text[] NOT NULL DEFAULT '{}',
  valid_during tstzrange NOT NULL,
  recorded_during tstzrange NOT NULL DEFAULT tstzrange(now(), NULL, '[)'),
  created_at timestamptz NOT NULL DEFAULT now(),
  supersedes_id uuid REFERENCES ntk.claim_versions(id)
);

CREATE TABLE ntk.claim_status_periods (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id uuid NOT NULL REFERENCES ntk.claims(id),
  status ntk.claim_status NOT NULL,
  rationale text,
  source_unit_ids text[] NOT NULL DEFAULT '{}',
  valid_during tstzrange NOT NULL,
  recorded_during tstzrange NOT NULL DEFAULT tstzrange(now(), NULL, '[)'),
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ntk.claim_status_periods ADD CONSTRAINT claim_status_no_current_overlap
  EXCLUDE USING gist (claim_id WITH =, valid_during WITH &&)
  WHERE (upper(recorded_during) IS NULL);

CREATE TABLE ntk.evidence_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id text NOT NULL REFERENCES ntk.cases(id),
  evidence_type text NOT NULL,
  summary text NOT NULL,
  event_date date,
  person_entity_id uuid REFERENCES ntk.entities(id),
  court_record_status ntk.court_record_status NOT NULL DEFAULT 'unknown',
  admissibility_note text,
  contested boolean NOT NULL DEFAULT false,
  contest_reason text,
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ntk.evidence_sources (
  evidence_id uuid NOT NULL REFERENCES ntk.evidence_items(id) ON DELETE CASCADE,
  source_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  relation text NOT NULL CHECK (relation IN ('supports_description','quotes','context','contradicts')),
  PRIMARY KEY (evidence_id, source_unit_id, relation)
);

CREATE TABLE ntk.claim_evidence (
  claim_id uuid NOT NULL REFERENCES ntk.claims(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES ntk.evidence_items(id) ON DELETE CASCADE,
  direction ntk.evidence_direction NOT NULL,
  weight numeric(4,3) CHECK (weight BETWEEN 0 AND 1),
  rationale text NOT NULL,
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  PRIMARY KEY (claim_id, evidence_id)
);

CREATE TABLE ntk.judicial_statements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  judge_entity_id uuid REFERENCES ntk.entities(id),
  level ntk.judicial_level NOT NULL,
  quote_text text,
  summary text NOT NULL,
  related_claim_ids uuid[] NOT NULL DEFAULT '{}',
  classifier_confidence numeric(4,3) CHECK (classifier_confidence BETWEEN 0 AND 1),
  review_state ntk.review_state NOT NULL DEFAULT 'human_review_required',
  UNIQUE (source_unit_id, level)
);

CREATE TABLE ntk.project315_events (
  id text PRIMARY KEY,
  external_event_id text NOT NULL UNIQUE,
  indictment_reference text,
  date_or_range daterange,
  requester text,
  recipient text,
  subject text,
  requested_action text,
  prosecution_description text,
  project315_classification text,
  project315_reasoning_summary text,
  netanyahu_involvement text CHECK (
    netanyahu_involvement IN ('direct','inferred','staff','third_party','unknown')
  ),
  independent_verification_status text NOT NULL DEFAULT 'unreviewed',
  project315_page_url text NOT NULL,
  source_version_id text REFERENCES ntk.source_versions(id),
  imported_at timestamptz NOT NULL DEFAULT now(),
  raw_payload jsonb NOT NULL
);

CREATE TABLE ntk.project315_event_sources (
  event_id text NOT NULL REFERENCES ntk.project315_events(id) ON DELETE CASCADE,
  url text NOT NULL,
  source_document_id text REFERENCES ntk.source_documents(id),
  source_unit_id text REFERENCES ntk.source_units(id),
  court_record_status ntk.court_record_status NOT NULL DEFAULT 'external',
  PRIMARY KEY (event_id, url)
);

CREATE TABLE ntk.case_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id text NOT NULL REFERENCES ntk.cases(id),
  event_type text NOT NULL,
  occurred_at timestamptz NOT NULL,
  outcome ntk.outcome_type,
  title text NOT NULL,
  description text,
  source_unit_ids text[] NOT NULL DEFAULT '{}',
  valid_during tstzrange NOT NULL,
  recorded_during tstzrange NOT NULL DEFAULT tstzrange(now(), NULL, '[)'),
  review_state ntk.review_state NOT NULL DEFAULT 'draft'
);

CREATE TABLE ntk.ingestion_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key text NOT NULL UNIQUE,
  source_version_id text REFERENCES ntk.source_versions(id),
  stage text NOT NULL,
  status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  parser_version text,
  prompt_version text,
  model_version text,
  input jsonb NOT NULL,
  output jsonb,
  error jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ntk.model_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_type text NOT NULL,
  provider text NOT NULL,
  model_family text NOT NULL,
  model_version text NOT NULL,
  prompt_version text NOT NULL,
  schema_version text NOT NULL,
  corpus_version text NOT NULL,
  input_hash char(64) NOT NULL,
  input jsonb NOT NULL,
  output jsonb NOT NULL,
  usage jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ntk.layer_a_versions
  ADD CONSTRAINT layer_a_model_run_fk FOREIGN KEY (model_run_id) REFERENCES ntk.model_runs(id);

CREATE TABLE ntk.generated_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_type text NOT NULL CHECK (artifact_type IN ('summary','claim_card','answer','seo_excerpt')),
  object_type text NOT NULL,
  object_id text NOT NULL,
  schema_version text NOT NULL,
  payload jsonb NOT NULL,
  review_state ntk.review_state NOT NULL DEFAULT 'draft',
  model_run_id uuid REFERENCES ntk.model_runs(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  supersedes_id uuid REFERENCES ntk.generated_artifacts(id)
);

CREATE TABLE ntk.artifact_citations (
  artifact_id uuid NOT NULL REFERENCES ntk.generated_artifacts(id) ON DELETE CASCADE,
  assertion_path text NOT NULL,
  source_unit_id text NOT NULL REFERENCES ntk.source_units(id),
  quote_start integer,
  quote_end integer,
  PRIMARY KEY (artifact_id, assertion_path, source_unit_id)
);

CREATE TABLE ntk.review_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type text NOT NULL,
  object_id text NOT NULL,
  risk_flags text[] NOT NULL DEFAULT '{}',
  assigned_to text,
  decision text CHECK (decision IN ('approve','reject','revise') OR decision IS NULL),
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE TABLE ntk.publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL REFERENCES ntk.generated_artifacts(id),
  slug text NOT NULL,
  canonical_url text NOT NULL,
  knowledge_version text NOT NULL,
  published_at timestamptz NOT NULL DEFAULT now(),
  unpublished_at timestamptz,
  UNIQUE (slug, knowledge_version)
);

CREATE INDEX claim_status_asof_idx
  ON ntk.claim_status_periods USING gist (claim_id, valid_during, recorded_during);

CREATE INDEX case_events_asof_idx
  ON ntk.case_events USING gist (case_id, valid_during, recorded_during);

CREATE INDEX artifact_object_idx
  ON ntk.generated_artifacts (object_type, object_id, review_state, created_at DESC);

CREATE INDEX publications_live_idx
  ON ntk.publications (slug) WHERE unpublished_at IS NULL;
