-- 0007_review_policy.sql — operator decision 11.10.2026: a person is never asked to approve protocol lines one by
-- one, and failures are not review items. Open tasks of those kinds are cancelled (kept for the record).
UPDATE ntk.review_tasks
   SET status = 'cancelled', decided_by = 'policy:2026-10-11', updated_at = now(), completed_at = now(),
       notes = coalesce(notes || ' | ', '') || 'cancelled by review policy 2026-10-11 (no per-line or failure tasks)'
 WHERE status = 'open' AND object_type IN ('qa_exchange', 'hearing_digest_failure', 'claim_build_failure');
