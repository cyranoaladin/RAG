# Rapport Codex — Lot 15G : verrou humain avant brouillon réel metadata-only

## 1. Objectif

Créer un verrou humain explicite avant tout futur brouillon réel metadata-only.
Le lot reste un lot de gouvernance : il ne crée aucun brouillon réel, ne
référence aucun vrai PDF et ne prépare aucun import.

## 2. Point de départ Git

- branche : `main` ;
- commit de départ : `1f266bb feat: add real draft metadata guard` ;
- dépôt propre avant création du lot ;
- `make doctor`, `make project-doctor` et `make test` exécutés avant reprise.

## 3. Fichiers créés ou modifiés

Créés :

- `docs/HUMAN_UNLOCK_PROTOCOL.md` ;
- `docs/templates/human_unlock/README.md` ;
- `docs/templates/human_unlock/human_unlock.template.json` ;
- `data/fixtures/pilot_math_terminale/human_unlock/README.md` ;
- fixtures synthétiques d’autorisation humaine ;
- `rag_pedago/imports/human_unlock_guard.py` ;
- `tests/unit/test_human_unlock_guard.py` ;
- `data/reports/codex_lot_15G_human_unlock_guard.md`.

Modifié :

- `Makefile`.

## 4. Protocole d’autorisation humaine

Le protocole précise que l’autorisation humaine ne donne pas le droit de parser,
copier, ingérer ou indexer un document. Elle autorise seulement un futur lot
metadata-only strictement borné.

## 5. Template d’autorisation

Le template JSON versionné contient les champs requis avec placeholders
`A_REMPLIR`. Il reste volontairement bloqué tant qu’un humain ne produit pas une
autorisation explicite dans un futur lot.

## 6. Fixtures synthétiques

Les fixtures sous `data/fixtures/pilot_math_terminale/human_unlock/` couvrent :

- une autorisation valide synthétique ;
- placeholder non rempli ;
- décision rejetée ;
- plus de 2 items ;
- parsing autorisé ;
- zone incohérente ;
- marqueur sensible synthétique.

La fixture `human_unlock.invalid_secret_marker.json` est un faux positif attendu
pour les scans de noms de fichiers sensibles : le nom est imposé par le lot et
son contenu ne contient aucun secret réel.

## 7. Module de validation

Le module `rag_pedago.imports.human_unlock_guard` lit uniquement le JSON
d’autorisation passé en argument. Il ne lit pas de `source_uri`, n’ouvre aucun
PDF, ne calcule aucun hash, n’écrit aucun fichier et ne touche pas au ledger.

## 8. Règles contrôlées

- refus des placeholders `A_REMPLIR` et `A_CONFIRMER` ;
- `decision=approved` obligatoire ;
- `scope=real_minimal_metadata_only_draft` obligatoire ;
- `max_items <= 2` ;
- droits et SHA-256 vérifiés hors pipeline ;
- absence de données personnelles ;
- absence de document réel copié ;
- interdiction d’ouverture de `source_uri` ;
- interdiction de parsing, embedding, Qdrant, scraping, `data/staging` et ledger permanent ;
- cohérence matière, niveau, voie, enseignement, zone AEFE Tunisie et candidat scolarisé ;
- refus des chemins `rag-ui`, `rag-local` et marqueurs sensibles.

## 9. Tests ajoutés ou modifiés

Ajout :

- `tests/unit/test_human_unlock_guard.py`.

## 10. Tests exécutés

Commandes prévues :

```bash
pytest tests/unit/test_human_unlock_guard.py -q
make human-unlock-check
make real-draft-guard-check
make doctor
make project-doctor
make test
```

## 11. Résultats

Résultats observés :

- `pytest tests/unit/test_human_unlock_guard.py -q` : 13 passed ;
- `make human-unlock-check` : `status=approved_for_metadata_only_next_step`, 0 issue ;
- `make real-draft-guard-check` : OK ;
- scan de sûreté du module : aucune occurrence ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 348 passed.

## 12. Limites volontaires

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
- aucun brouillon réel créé.

## 13. Risques restants

- le verrou ne valide pas le contenu pédagogique ;
- une autorisation humaine réelle devra être relue manuellement ;
- le futur lot metadata-only devra encore rester sans document réel ;
- le nom de fixture `human_unlock.invalid_secret_marker.json` déclenche un faux positif de scan par nom.

## 14. Verdict

COMMIT_RECOMMANDÉ

## 15. Recommandation pour le lot 15H

Ne pas démarrer 15H avant commit dédié du lot 15G et relecture humaine du
protocole d’autorisation. Le lot suivant devra rester metadata-only tant qu’une
autorisation humaine réelle n’a pas été produite et validée hors pipeline.
