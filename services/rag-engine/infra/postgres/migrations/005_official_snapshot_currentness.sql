-- Migration 005 : l'instantané officiel est enregistré pour ce qu'il est
-- (ADR-0059 § 2).
--
-- `official_snapshot` désigne un instantané officiel ADR-0055 dont
-- l'actualité réseau n'a pas pu être établie. `current` reste réservé à
-- l'identité d'octets prouvée. Le retrieval sert les deux, jamais `archive`
-- ni `review_required`.
--
-- Strictement additive : la contrainte est élargie sous le même nom et
-- l'index partiel des placements servis couvre les deux valeurs servies.
-- Aucune ligne n'est lue pour être réécrite ; les lignes existantes, toutes
-- dans l'ancien domaine, sont revalidées telles quelles par PostgreSQL.
--
-- Le contrôle de transaction appartient au runner, qui exécute ce fichier,
-- l'enregistrement et les validateurs dans une transaction unique : ce
-- fichier ne porte ni BEGIN ni COMMIT.

ALTER TABLE public.rag_artifact_placements
    DROP CONSTRAINT rag_artifact_placements_currentness_check,
    ADD CONSTRAINT rag_artifact_placements_currentness_check
        CHECK (currentness IN ('current', 'official_snapshot', 'archive', 'review_required'));

DROP INDEX public.idx_rag_artifact_placements_scope_active;

CREATE INDEX idx_rag_artifact_placements_scope_active
    ON public.rag_artifact_placements (
        collection, tenant, niveau, voie, matiere, statut_enseignement,
        candidat, school_year, programme_version, artifact_id
    )
    WHERE placement_status = 'active'
      AND currentness IN ('current', 'official_snapshot')
      AND review_status = 'reviewed';
