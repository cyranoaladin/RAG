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

ALTER TABLE ingestion_control.resource_candidates
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ingestion_control.artifacts
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
