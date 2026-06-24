# Politique qualite des manifests

La politique qualite decide si un lot de manifests peut etre importe dans le
ledger ou doit rester bloque avant toute ingestion documentaire.

## Pourquoi une politique qualite

Les manifests peuvent contenir des erreurs de metadonnees sans que les documents
sources soient lus. Les bloquer tot evite de polluer le ledger avec des
documents ambigus, non retrievables ou mal classes.

## Severites

- `info` : information non bloquante ;
- `warning` : probleme a corriger mais import possible selon politique ;
- `error` : probleme bloquant ;
- `critical` : probleme bloquant critique.

## Problemes bloquants par defaut

- lignes invalides ;
- conflit de payload pour un meme `doc_id` ;
- meme `source_uri` avec plusieurs `doc_id` ;
- absence de `programme_version` pour documents pedagogiques ;
- absence de `niveau` pour documents pedagogiques ;
- absence d'`epreuve` pour documents d'examen.

## Warnings par defaut

- doublon exact de `doc_id` avec payload identique ;
- meme `sha256` avec plusieurs `doc_id` ;
- `rights=unknown`.

`rights=unknown` peut devenir bloquant avec le mode strict.

## Dry-run et import reel

En dry-run, la politique est evaluee et un rapport est genere sans creer de DB,
run, document, etat ou erreur. Si la qualite bloque, le statut devient
`dry_run_blocked`.

En import reel, `quality_blocked` empeche toute ecriture ledger. Un rapport
global explique la decision.

## Mode strict

Le CLI `import_manifest_dir` accepte `--strict`. Ce mode bloque notamment les
droits inconnus. L'option `--allow-unknown-rights` autorise explicitement ces
droits en warning, meme en mode strict.

## Doublons

- `duplicate_doc_id_exact` : meme `doc_id`, meme hash et payload identique ;
- `duplicate_doc_id_conflict` : meme `doc_id`, hash ou payload different ;
- `duplicate_source_uri` : meme source avec plusieurs `doc_id` ;
- `duplicate_sha256` : meme hash avec plusieurs `doc_id`.

## Limites avant ingestion

La politique qualite ne lit pas les `source_uri`, ne parse aucun PDF et ne fait
aucun appel reseau. Elle ne prouve donc pas que les fichiers sources existent ;
elle valide uniquement les metadonnees de manifests.

## Références officielles

Le lot 10 ajoute des contrôles contre `data/reference/` :

- documents officiels : `official_level_ref`, `official_subject_ref` et source ou claim vérifiée ;
- documents d'examen : `official_exam_ref` et `candidate_status_ref` ;
- documents réglementaires : `official_claim_refs` vérifiées ;
- cohérence croisée niveau/sujet et niveau/examen.

Les refs inconnues sont bloquantes. `candidate_status_ref=aefe` est un warning
par défaut car AEFE est un contexte d'établissement ; il devient bloquant en
mode strict.
