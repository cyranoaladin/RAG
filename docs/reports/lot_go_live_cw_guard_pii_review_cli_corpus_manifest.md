# Lot CW-garde — le CLI de revue PII n'écrase plus l'empreinte du corpus

- Branche : `go-live/pii-review-cli-corpus-manifest-guard`
- Base : `d7611667daef6af45c62e67afcd1db0fd5b3dc5d`
- Lot lié : `docs/reports/lot_go_live_cw_profile_gate_v3_pii_decisions.md`
  (jeu de décisions V3, PR distincte : ce correctif ne déplace pas son head)

## Défaut mesuré

Campagne `pii-review-2026-09-22-profile-gate-v3` : le brouillon créé par
`sceller_decisions_pii.py brouillon` portait `corpus_manifest_sha256 =
5ce13fac…96df7`, l'empreinte des octets du fichier d'autorité, celle que le
producteur (`corpus_manifest_authority_file_sha256()`) exige. L'import par
`revue_pii_cli.py` a réécrit ce champ, sans condition, avec la valeur par
défaut de `--corpus-manifest-sha256` : `d7e5caa5…4cc1e`, l'autorité que ce
fichier DÉCLARE. Le jeu scellé aurait été refusé par la projection du
producteur (« the decisions describe another corpus »).

## Correction

`services/rag-pedago/scripts/revue_pii_cli.py` :

- plus de valeur par défaut pour `--corpus-manifest-sha256` ; un nouveau
  brouillon exige une valeur explicite de 64 hex ;
- un brouillon qui porte déjà une empreinte la garde : un argument différent
  est refusé, le fichier n'est pas réécrit ;
- la valeur est vérifiée contre l'empreinte des octets de
  `--corpus-manifest-authority` (par défaut, le fichier que le producteur lie :
  `data/releases/prerentree_2026_2027/profile_gate/corpus_manifest_authority.json`) ;
  la confusion déclarée/empreinte est nommée dans le refus ;
- le fichier d'autorité doit déclarer une `authority_sha256` valide, vérifiée
  avant l'empreinte (constat Codex P2 sur #248) : un fichier quelconque dont on
  fournit l'empreinte n'est pas accepté comme autorité.

Aucun autre contrat nommé `corpus_manifest_sha256` n'est modifié :
`CORPUS_MANIFEST_AUTHORITY = d7e5…` reste correcte là où la release embarque
l'autorité déclarée.

## Preuves

- TDD : 7 tests ajoutés à `tests/test_revue_pii_cli.py`, rouges avant la
  correction, verts après ; `test_revue_pii_cli.py` + `test_sceller_decisions_pii.py` : 20 réussis ;
- `ruff` et `mypy` propres sur le script ;
- sur les brouillons réels (hors dépôt, lecture seule) : le brouillon corrigé
  est accepté (`5ce13fac…`) ; le brouillon avant correction est refusé
  (« c'est la valeur qu'il DÉCLARE, pas son empreinte ») ; un réimport avec
  `d7e5…` sur le brouillon corrigé est refusé sans écriture.

## Rapport de service

`services/rag-pedago/data/reports/codex_lot_cw_guard_pii_review_cli_corpus_manifest.md`
(exigé par `services/rag-pedago/AGENTS.md`, constat Codex P1 sur #248).

## CI

CI de référence : les checks GitHub Actions requis sur le head de la PR #248
(environnement propre ; `services/rag-pedago` y rejoue lint, mypy et la suite
complète). Premier head `b6307830` : tous verts. La CI locale complète a été
exécutée sur le lot jumeau #249 ; ses deux rouges (seuil disque) sont
environnementaux et tracés dans `docs/reports/lot_go_live_cw_dettes.md`.
