-- Rollback 005 : restaure exactement les définitions 004, et seulement si
-- aucun placement n'est enregistré comme instantané officiel.
--
-- Refuser vaut mieux que réécrire : requalifier une ligne `official_snapshot`
-- en `current` affirmerait une identité d'octets jamais prouvée, et la
-- supprimer retirerait un contenu servi. Le rollback échoue donc fermé ; la
-- décision de retirer ces placements appartient à une publication
-- gouvernée, pas à un rollback de schéma.
--
-- Le verrou précède la garde : sans lui, une publication concurrente
-- pourrait committer un `official_snapshot` après la garde et avant la
-- redéfinition. Seule la table redéfinie est verrouillée, ce qui ne crée
-- aucun cycle avec l'ordre artefact -> placements -> chunks du publisher.
-- PostgreSQL conserve ce verrou jusqu'au commit/rollback du runner, qui
-- exécute ce fichier dans une transaction unique : ce fichier ne porte ni
-- BEGIN ni COMMIT.
LOCK TABLE public.rag_artifact_placements IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.rag_artifact_placements
        WHERE currentness = 'official_snapshot'
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_005_OFFICIAL_SNAPSHOT_PRESENT';
    END IF;
END
$nexus$;

DROP INDEX public.idx_rag_artifact_placements_scope_active;

ALTER TABLE public.rag_artifact_placements
    DROP CONSTRAINT rag_artifact_placements_currentness_check,
    ADD CONSTRAINT rag_artifact_placements_currentness_check
        CHECK (currentness IN ('current', 'archive', 'review_required'));

CREATE INDEX idx_rag_artifact_placements_scope_active
    ON public.rag_artifact_placements (
        collection, tenant, niveau, voie, matiere, statut_enseignement,
        candidat, school_year, programme_version, artifact_id
    )
    WHERE placement_status = 'active'
      AND currentness = 'current'
      AND review_status = 'reviewed';
