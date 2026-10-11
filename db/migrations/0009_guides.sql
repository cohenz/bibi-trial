-- 0009_guides.sql — reader entry points (ADR-0015): indictment overview, one guide per case (1000/2000/4000) and per
-- witness are stored as generated artifacts of type 'guide'. They pass the same gates and are approved once by a person.
DO $$
DECLARE c text;
BEGIN
  SELECT conname INTO c FROM pg_constraint
   WHERE conrelid = 'ntk.generated_artifacts'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%artifact_type%';
  IF c IS NOT NULL THEN
    EXECUTE format('ALTER TABLE ntk.generated_artifacts DROP CONSTRAINT %I', c);
  END IF;
END $$;
ALTER TABLE ntk.generated_artifacts ADD CONSTRAINT generated_artifacts_artifact_type_check
  CHECK (artifact_type IN ('summary', 'claim_card', 'answer', 'seo_excerpt', 'guide'));
