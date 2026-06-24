# Rapport Codex — Lot 15F : garde-fou brouillon réel metadata-only

## 1. Objectif

Préparer un cadre de gouvernance pour un futur brouillon réel minimal
metadata-only, limité à 1 ou 2 ressources autorisées, sans copier, lire, parser,
ingérer ou indexer aucun document réel.

## 2. Point de départ Git

- branche : `main` ;
- commit de départ : `d32c5da feat: add metadata-only pilot rehearsal` ;
- dépôt propre avant création du lot ;
- `make doctor`, `make project-doctor` et `make test` exécutés avant reprise.

## 3. Fichiers créés ou modifiés

Créés :

- `docs/REAL_MINIMAL_DRAFT_PROTOCOL.md` ;
- `rag_pedago/imports/real_draft_guard.py` ;
- `tests/unit/test_real_draft_guard.py` ;
- `data/fixtures/pilot_math_terminale/real_draft_guard/README.md` ;
- fixtures JSONL synthétiques du garde-fou réel minimal ;
- `data/reports/codex_lot_15F_real_draft_guard.md`.

Modifié :

- `Makefile`.

## 4. Protocole créé

Le protocole décrit le passage futur vers un brouillon réel minimal
metadata-only, avec verrou humain, collecte manuelle des droits, SHA-256 calculé
hors pipeline et interdiction de tout traitement documentaire réel.

## 5. Module de garde-fou

Le module `rag_pedago.imports.real_draft_guard` fournit :

- `validate_candidate_source_uri` ;
- `validate_real_draft_metadata` ;
- `validate_human_unlock_file` ;
- `build_real_draft_guard_report` ;
- `main`.

Il ne lit aucun `source_uri`, ne calcule aucun hash, ne vérifie pas l’existence
des fichiers sources et n’écrit aucun fichier.

## 6. Fixtures synthétiques

Les fixtures sont sous
`data/fixtures/pilot_math_terminale/real_draft_guard/`. Elles utilisent des
`source_uri` synthétiques, sauf une fixture explicitement invalide pour vérifier
le refus d’un chemin `rag-local`.

## 7. Règles contrôlées

- refus de `/srv/nexusreussite/rag-ui` ;
- refus de `/home/alaeddine/Bureau/rag-local` ;
- refus des marqueurs `.env`, `.pem`, `.key`, `gdrive`, `credential`, `secret` ;
- refus de `rights=unknown` ;
- refus de `visibility=public` pour droits internes ou restreints ;
- cohérence `extra.zone=aefe_tunisie` avec `establishment_context_ref=aefe` ;
- cohérence `candidat=scolarise` avec `candidate_status_ref=scolarise` ;
- refus d’une source réglementaire `pending` comme seul appui officiel ;
- présence et forme hexadécimale 64 caractères de `sha256` ;
- présence de `extra.manual_human_review_required=true`.

## 8. Tests ajoutés ou modifiés

Ajout :

- `tests/unit/test_real_draft_guard.py`.

## 9. Tests exécutés

Commandes prévues :

```bash
pytest tests/unit/test_real_draft_guard.py -q
make real-draft-guard-check
make doctor
make project-doctor
make test
```

## 10. Résultats

Résultats observés :

- `pytest tests/unit/test_real_draft_guard.py -q` : 11 passed ;
- `make real-draft-guard-check` : `status=ready_for_human_locked_metadata_validation`, 2 items, 0 issue ;
- scan de sûreté du module : aucune occurrence ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 335 passed.

## 11. Limites volontaires

- aucun document réel ;
- aucun PDF ;
- aucun `data/staging` ;
- aucune lecture `source_uri` ;
- aucun hash calculé ;
- aucune écriture ledger ;
- aucun scraping ;
- aucun Qdrant ;
- aucun changement `schema/document.py` ;
- aucune modification taxonomie officielle.

## 12. Risques restants

- le lot ne valide pas encore de métadonnées réelles ;
- le futur brouillon réel exigera une revue humaine explicite ;
- les droits et SHA-256 réels restent à établir hors pipeline ;
- le contenu pédagogique n’est pas contrôlé par ce garde-fou.

## 13. Verdict

COMMIT_RECOMMANDÉ

## 14. Recommandation pour le lot 15G

Ne démarrer un lot 15G qu’après commit du garde-fou 15F, dépôt propre et
relecture humaine du protocole de brouillon réel minimal. Le prochain lot devra
rester metadata-only et ne pas ajouter de document réel sans validation humaine
explicite.
