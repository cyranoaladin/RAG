-- Migration 013 : LOT42-V2 — revue de publication liée à l'attribution.
-- ADR-0035, remédiation du constat F3 de la review Codex 4904995785.
--
-- **Le problème résolu ici.** Un artefact de revue LOT42-V1 ne nommait
-- nulle part les quatre faits d'attribution (``source_label``,
-- ``official``, ``source_kind``, ``type_doc``) qui seraient effectivement
-- publiés. L'humain approuvait donc une publication sans jamais relire sa
-- provenance : la migration 012 scelle bien ces faits *après* attestation,
-- mais rien ne prouvait que la valeur scellée était celle qu'un humain
-- avait vue. LOT42-V2 place le digest d'attribution dans les octets
-- canoniques relus, et cette migration rend le schéma capable de
-- représenter — et d'exiger — cette liaison.
--
-- **Ce que cette migration ne fait pas, délibérément.**
--   * Elle ne fabrique aucun digest pour une ligne V1. Une attestation V1
--     n'a jamais lié d'attribution ; lui en attribuer une rétroactivement
--     serait exactement le mensonge que tout ce lot cherche à empêcher.
--   * Elle ne supprime, ne réécrit et ne réétiquette aucune ligne
--     historique. Les lignes V1 restent lisibles pour l'audit.
--   * Elle ne fait pas du refus des *nouvelles* écritures V1 une affaire
--     de CHECK : une contrainte ne distingue pas une ligne ancienne d'une
--     ligne neuve. La coexistence est donc autorisée par le schéma et
--     interdite par l'application (``require_publication_review_v2``).
--
-- **Ce que la base garantit après 013.**
--   * ``protocol_version`` ∈ {LOT42-V1, LOT42-V2} — rien d'autre.
--   * V2 ⇒ ``attributed_facts_digest`` présent et hexadécimal 64.
--   * V1 ⇒ ``attributed_facts_digest`` absent (NULL).
-- La colonne elle-même reste nullable : c'est le couple
-- (version, digest) qui porte l'invariant, pas la colonne seule. Une
-- ``NOT NULL`` sur la colonne serait fausse — elle rendrait les lignes V1
-- historiques invalides et ferait échouer la migration sur une base
-- peuplée.
--
-- Idempotent : chaque objet est créé sous condition d'absence, chaque
-- contrainte est remplacée par DROP IF EXISTS + ADD. Sûr à rejouer.

-- ---------------------------------------------------------------------
-- 1. publication_attestations : accepter V2, exiger le digest pour V2,
--    l'interdire pour V1.
-- ---------------------------------------------------------------------

-- La contrainte 008 n'acceptait que 'LOT42-V1'. Elle est remplacée, pas
-- assouplie : l'ensemble reste fermé et énuméré.
ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_protocol_version_valid;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_protocol_version_valid
    CHECK (protocol_version IN ('LOT42-V1', 'LOT42-V2'));

-- Invariant propre à V2 : le digest d'attribution n'est pas optionnel.
-- Invariant propre à V1 : il est interdit. Une ligne V1 ne peut donc
-- jamais *sembler* porter une revue d'attribution qu'elle n'a pas eue.
ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_attribution_digest_matches_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_attribution_digest_matches_protocol
    CHECK (
        (protocol_version = 'LOT42-V2' AND attributed_facts_digest IS NOT NULL)
        OR
        (protocol_version = 'LOT42-V1' AND attributed_facts_digest IS NULL)
    );

-- ---------------------------------------------------------------------
-- 2. publication_commit_pins : même ouverture à V2.
--    Cette table ne porte pas de digest d'attribution — elle épingle le
--    commit produit à une attestation, qui, elle, porte le digest. Ajouter
--    ici une copie du digest créerait une seconde source de vérité
--    susceptible de diverger ; la clé étrangère vers l'attestation suffit.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_commit_pins
    DROP CONSTRAINT IF EXISTS publication_commit_pins_publication_protocol_valid;

ALTER TABLE ingestion_control.publication_commit_pins
    ADD CONSTRAINT publication_commit_pins_publication_protocol_valid
    CHECK (publication_protocol_version IN ('LOT42-V1', 'LOT42-V2'));
