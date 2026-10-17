-- 0013_curated_questions.sql — the questions the editor shows on the questions page, and how other wordings were
-- matched to them (17.10.2026: a visitor asking an approved question in other words gets the approved answer).
CREATE TABLE IF NOT EXISTS ntk.curated_questions (
  answer_id text PRIMARY KEY,
  question text NOT NULL,
  normalized text NOT NULL,
  embedding jsonb,
  embedding_model text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ntk.question_matches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  normalized text NOT NULL,
  question text NOT NULL,
  answer_id text NOT NULL,
  similarity real,
  decision text NOT NULL CHECK (decision IN ('same', 'related', 'rejected')),
  decided_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (normalized, answer_id)
);
CREATE INDEX IF NOT EXISTS question_matches_normalized ON ntk.question_matches (normalized);
