-- 0005_evaluation_runs.sql — server-side evaluation runs (search benchmark,
-- Ask question suites). The worker runs them against the deployed corpus and
-- models; the report is stored here and read through the admin API. Reports
-- are evidence for the pilot report, so rows are never updated after they
-- finish.

CREATE TABLE ntk.evaluation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL CHECK (kind IN ('search_bench', 'ask_suite')),
  suite text NOT NULL,
  options jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  models jsonb,
  summary jsonb,
  report jsonb,
  error jsonb,
  requested_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE INDEX evaluation_runs_created_idx ON ntk.evaluation_runs (created_at DESC);
