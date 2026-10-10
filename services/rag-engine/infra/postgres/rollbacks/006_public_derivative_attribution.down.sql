-- Refuser la perte d'une attribution effectivement publiée.
LOCK TABLE public.rag_artifacts IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.rag_artifacts
        WHERE is_text_derivative OR licensor IS NOT NULL OR licence_id IS NOT NULL
           OR source_updated_at IS NOT NULL OR derivative_notice IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_006_PUBLIC_ATTRIBUTION_PRESENT';
    END IF;
END
$nexus$;

ALTER TABLE public.rag_artifacts
    DROP CONSTRAINT rag_artifacts_public_attribution_complete_check,
    DROP COLUMN licensor,
    DROP COLUMN licence_id,
    DROP COLUMN source_updated_at,
    DROP COLUMN derivative_notice,
    DROP COLUMN is_text_derivative;
