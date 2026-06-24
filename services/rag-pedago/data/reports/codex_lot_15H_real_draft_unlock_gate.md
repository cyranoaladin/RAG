# Rapport Codex — Lot 15H : gate combiné human unlock + real draft metadata

## 1. Objectif

Créer un gate combiné metadata-only qui vérifie simultanément une autorisation
humaine, un brouillon metadata-only candidat et la cohérence stricte entre les
deux périmètres.

## 2. Point de départ Git

- branche : `main` ;
- commit de départ : `c629b5c feat: add human unlock guard` ;
- dépôt propre avant création du lot ;
- `make doctor`, `make project-doctor` et `make test` exécutés avant reprise.

## 3. Fichiers créés ou modifiés

Créés :

- `docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md` ;
- `data/fixtures/pilot_math_terminale/real_draft_unlock_gate/README.md` ;
- fixtures synthétiques du gate combiné ;
- `rag_pedago/imports/real_draft_unlock_gate.py` ;
- `tests/unit/test_real_draft_unlock_gate.py` ;
- `data/reports/codex_lot_15H_real_draft_unlock_gate.md`.

Modifié :

- `Makefile`.

## 4. Protocole de gate combiné

Le protocole précise que le gate combiné ne donne toujours pas le droit de
parser, copier, ingérer ou indexer des documents. Il vérifie uniquement la
cohérence entre un fichier human unlock JSON et un brouillon metadata-only JSONL.

## 5. Module de gate combiné

Le module `rag_pedago.imports.real_draft_unlock_gate` réutilise :

- `rag_pedago.imports.human_unlock_guard` ;
- `rag_pedago.imports.real_draft_guard`.

Il lit uniquement les fichiers JSON/JSONL de métadonnées fournis en entrée,
produit un rapport en mémoire et ne crée aucun fichier.

## 6. Fixtures synthétiques

Les fixtures sous
`data/fixtures/pilot_math_terminale/real_draft_unlock_gate/` couvrent :

- couple unlock + draft valide ;
- autorisation rejetée ;
- matière hors périmètre ;
- niveau hors périmètre ;
- zone hors périmètre ;
- nombre d’items supérieur au maximum ;
- validation humaine manquante ;
- droits inconnus.

Toutes les fixtures restent synthétiques et utilisent uniquement des
`source_uri` en `synthetic://`.

## 7. Règles contrôlées

- autorisation human unlock valide ;
- brouillon real draft metadata valide ;
- `item_count <= max_items` ;
- cohérence matière, niveau, voie, enseignement, zone et statut candidat ;
- présence de `extra.manual_human_review_required=true` ;
- cohérence de `batch_id` si le champ est présent ;
- refus indirect par les garde-fous existants de droits inconnus, chemins
  interdits, marqueurs sensibles et source `pending` seule.

## 8. Tests ajoutés ou modifiés

Ajout :

- `tests/unit/test_real_draft_unlock_gate.py`.

## 9. Tests exécutés

Commandes prévues :

```bash
pytest tests/unit/test_real_draft_unlock_gate.py -q
make real-draft-unlock-gate-check
make human-unlock-check
make real-draft-guard-check
make doctor
make project-doctor
make test
```

## 10. Résultats

Résultats observés :

- `pytest tests/unit/test_real_draft_unlock_gate.py -q` : 11 passed ;
- `make real-draft-unlock-gate-check` : `status=approved_for_real_metadata_draft_preparation`, 2 items, 0 issue ;
- `make human-unlock-check` : OK ;
- `make real-draft-guard-check` : OK ;
- scan de sûreté du module : aucune occurrence ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 359 passed.

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
- aucune modification taxonomie officielle ;
- aucun brouillon réel créé ;
- aucun manifest réel prêt pour import.

## 12. Risques restants

- le gate ne valide pas le contenu pédagogique ;
- les futures autorisations et métadonnées réelles devront être relues par un humain ;
- le passage à un vrai brouillon metadata-only devra rester limité au périmètre autorisé ;
- le fichier 15G `human_unlock.invalid_secret_marker.json` reste un faux positif connu au scan par nom.

## 13. Verdict

COMMIT_RECOMMANDÉ

## 14. Recommandation pour le lot 15I

Ne pas démarrer 15I avant commit dédié du gate combiné 15H et relecture humaine
du protocole. Le lot suivant devra rester metadata-only tant qu’un brouillon
réel minimal n’a pas été explicitement autorisé.
