-- Migration 006 : colonne payload JSONB sur resource_candidates et
-- artifacts (LOT44f, ADR-0029 — reprise multi-claims).
--
-- Les colonnes typées de 002 suffisent aux contraintes/index mais ne
-- couvrent pas tous les champs de ResourceCandidate/ArtifactRecord
-- (nexus_contracts.ingestion) — ex. title, publisher, language,
-- relevance_evidence, license, rights_status, pages_count, version,
-- extracted_text_ref. Plutôt que d'ajouter une colonne typée par champ
-- (fragile à chaque évolution de contrat, LOT44a restant gelé), ce payload
-- porte le contrat complet sérialisé (même motif que jobs.payload,
-- migration 004) : les colonnes typées restent la source de vérité pour
-- les contraintes/index déjà en place, le payload permet une reconstruction
-- fidèle de l'objet Python complet lors d'une reprise après crash
-- (LOT44e runner.py), sans jamais réinterpréter ce JSON au niveau SQL.
--
-- Idempotent : IF NOT EXISTS partout, sûr à rejouer.
--
-- Remédiation revue PR#90 (Cubic P1) : sur une base déjà peuplée (aucune
-- à ce jour dans ce dépôt — jamais déployé en production, cf. ADR-0031 —
-- mais une future ré-application contre un volume existant y serait
-- exposée), chaque ligne préexistante recevrait ce DEFAULT '{}'::jsonb,
-- un JSON qui ne valide jamais comme ResourceCandidate/ArtifactRecord
-- complet (colonnes typées de 002 insuffisantes : title/publisher/
-- language/relevance_evidence/license/rights_status/pages_count/version/
-- extracted_text_ref n'y sont pas portés, cf. commentaire ci-dessus) —
-- une reprise après crash sur une telle ligne échouerait à
-- model_validate() au lieu de récupérer l'enregistrement persisté.
--
-- Plutôt qu'une reconstruction partielle silencieuse (produirait un objet
-- qui semble valide mais dont plusieurs champs seraient devinés), cette
-- migration échoue explicitement si la table contient déjà des lignes au
-- moment où la colonne est ajoutée pour la première fois — un opérateur
-- doit alors backfill ou mettre en quarantaine ces lignes délibérément
-- avant de rejouer. Ne bloque jamais un rejeu idempotent sur une base où
-- la colonne existe déjà (replay après succès, aucune donnée davantage
-- exposée).
DO $nexus$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ingestion_control' AND table_name = 'resource_candidates'
          AND column_name = 'payload'
    ) AND EXISTS (SELECT 1 FROM ingestion_control.resource_candidates) THEN
        RAISE EXCEPTION 'MIGRATION_006_PREEXISTING_ROWS_resource_candidates: cannot '
            'add a required payload column with an unreconstructable default on a '
            'non-empty table — backfill or quarantine existing rows first';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ingestion_control' AND table_name = 'artifacts'
          AND column_name = 'payload'
    ) AND EXISTS (SELECT 1 FROM ingestion_control.artifacts) THEN
        RAISE EXCEPTION 'MIGRATION_006_PREEXISTING_ROWS_artifacts: cannot add a '
            'required payload column with an unreconstructable default on a '
            'non-empty table — backfill or quarantine existing rows first';
    END IF;
END
$nexus$;

ALTER TABLE ingestion_control.resource_candidates
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ingestion_control.artifacts
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
