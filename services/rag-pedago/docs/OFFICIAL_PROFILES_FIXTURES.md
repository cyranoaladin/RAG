# Fixtures official profiles

`data/fixtures/manifests/batch_official_profiles_clean/` est un batch de
manifests synthétiques destiné à valider les cas réglementaires utiles à Nexus
avant toute ingestion documentaire.

## Fixtures

- `troisieme_dnb_scolaire_clean.jsonl` : DNB candidat scolarisé.
- `troisieme_dnb_candidat_individuel_clean.jsonl` : DNB candidat individuel,
  incluant la langue vivante étrangère spécifique.
- `seconde_gt_clean.jsonl` : seconde générale et technologique.
- `premiere_generale_eaf_eam_clean.jsonl` : EAF et épreuve anticipée de
  mathématiques.
- `terminale_generale_bac_clean.jsonl` : spécialités, philosophie et Grand
  oral.
- `candidat_individuel_bac_clean.jsonl` : candidat individuel au bac avec
  claim de carte d'examen.
- `aefe_scolarise_clean.jsonl` : élève AEFE scolarisé.
- `double_cursus_warning.jsonl` : contexte double cursus.

## Statut attendu

Le batch doit produire :

- readiness : `ready` ;
- coverage : `coverage_ok` ;
- gate : `ready_for_controlled_import` ;
- controlled import : `imported`.

`batch_001` reste volontairement problématique et doit rester bloqué.

## AEFE

AEFE est un contexte d'établissement, pas un statut candidat d'examen.

Valide :

- `candidate_status_ref=scolarise` ;
- `establishment_context_ref=aefe`.

Déprécié :

- `candidate_status_ref=aefe`.

Le cas déprécié produit un warning par défaut et bloque en mode strict.

## Double cursus

`establishment_context_ref=double_cursus` est accepté comme contexte. Il ne
suffit pas à déterminer les épreuves applicables : la carte d'examen,
l'inscription et la convocation doivent trancher.

## Candidat individuel

Les fixtures candidat individuel utilisent `candidate_status_ref` =
`candidat_individuel` et s'appuient sur une claim vérifiée de carte d'examen.
Le manifest ne remplace pas l'`ExamProfile` concret d'un élève.

## Garanties

- aucun `source_uri` n'est ouvert ;
- aucun appel réseau n'est effectué ;
- aucune ingestion documentaire n'est réalisée ;
- aucun PDF n'est lu ou parsé ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Limites

Ces fixtures contrôlent les métadonnées et le référentiel officiel. Elles ne
valident pas le contenu réel d'un sujet, corrigé, barème ou programme.
