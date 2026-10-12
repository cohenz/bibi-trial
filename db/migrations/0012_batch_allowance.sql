-- 0012_batch_allowance.sql — how many more requests of a task the operator approved for the Batch API (12.10.2026).
-- The provider caps the tokens waiting in batches at any time, so a large approval cannot always be sent at once:
-- what the provider accepts is sent now, the rest stays here and is sent as earlier batches finish (beat poll).
-- Never more than approved; an approval of 0 cancels what is left.
CREATE TABLE IF NOT EXISTS ntk.batch_allowance (
  task_type text PRIMARY KEY,
  remaining integer NOT NULL DEFAULT 0 CHECK (remaining >= 0),
  approved_total integer NOT NULL DEFAULT 0,
  approved_by text,
  last_error text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
