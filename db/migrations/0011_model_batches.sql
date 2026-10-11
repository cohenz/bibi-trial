-- 0011_model_batches.sql — model calls sent through the provider's Batch API (half price, results within 24 hours).
-- Each item's key is "<task>|<run id>": when the batch is done the result is saved as that model run, and the regular
-- builder then finds it in the run store instead of calling the model again.
CREATE TABLE IF NOT EXISTS ntk.model_batches (
  name text PRIMARY KEY,
  task_type text NOT NULL,
  model_id text NOT NULL,
  state text NOT NULL DEFAULT 'submitted',
  items jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  result jsonb,
  error jsonb
);
CREATE INDEX IF NOT EXISTS model_batches_open_idx ON ntk.model_batches (state) WHERE finished_at IS NULL;
