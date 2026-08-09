-- Rollback 004 : ne retire que le modèle additif, et seulement s'il ne porte
-- plus aucune donnée gouvernée. Refuser vaut mieux que supprimer un corpus.

-- Le verrou doit précéder la garde de vacuité. Sans lui, une publication
-- concurrente peut committer après les SELECT ci-dessous mais avant les DROP,
-- et ses lignes seraient alors supprimées sans jamais avoir été observées.
-- L'ordre suit celui du publisher (artefact -> placements -> chunks) afin de
-- ne pas créer un cycle de verrous avec une transaction de publication déjà
-- engagée. PostgreSQL conserve ces verrous jusqu'au commit/rollback du runner,
-- qui exécute ce fichier dans une transaction unique.
LOCK TABLE public.rag_artifacts, public.rag_artifact_placements,
    public.rag_chunks IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.rag_chunks WHERE artifact_id IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM public.rag_artifact_placements
    ) OR EXISTS (
        SELECT 1 FROM public.rag_artifacts
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_004_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP INDEX public.idx_rag_artifact_placements_artifact_id;
DROP INDEX public.idx_rag_artifact_placements_audience;
DROP INDEX public.idx_rag_artifact_placements_scope_active;
DROP INDEX public.idx_rag_chunks_artifact_id;
DROP INDEX public.idx_rag_chunks_artifact_chunk_index_unique;

ALTER TABLE public.rag_chunks
    DROP CONSTRAINT rag_chunks_governed_identity_check,
    DROP CONSTRAINT rag_chunks_artifact_id_fkey,
    DROP COLUMN artifact_id;

DROP TABLE public.rag_artifact_placements;
DROP TABLE public.rag_artifacts;
