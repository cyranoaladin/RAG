# Rapport Codex — Lot 15D : compilateur offline de brouillon manifest

## 1. Objectif

Ajouter une etape offline qui prend un brouillon YAML de manifest pilote rempli,
le valide strictement, puis produit un JSONL compatible manifest.

Le lot reste metadata-only :

- aucun document reel ;
- aucun PDF ;
- aucun parsing ;
- aucune ingestion documentaire ;
- aucun scraping ;
- aucun reseau ;
- aucun Qdrant ;
- aucun changement de schema ;
- aucune modification de taxonomie officielle.

## 2. Point de depart Git

Le lot demarre apres le commit valide :

```text
dbb4236 feat: add offline pilot manifest preparation kit
```

Le depot etait propre au depart. Les validations initiales `make doctor`,
`make project-doctor` et `make test` etaient OK.

## 3. Fichiers crees ou modifies

Fichiers crees :

- `data/fixtures/pilot_math_terminale/filled_drafts/README.md`
- `data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml`
- `data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.invalid_placeholder.yml`
- `data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.invalid_unknown_rights.yml`
- `data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.invalid_forbidden_source.yml`
- `rag_pedago/imports/pilot_manifest_compiler.py`
- `tests/unit/test_pilot_manifest_compiler.py`
- `data/reports/codex_lot_15D_offline_manifest_compiler.md`

Fichier modifie :

- `Makefile`

## 4. Brouillons remplis synthetiques

Le brouillon valide contient 7 documents synthetiques :

- reference de programme ;
- cours suites et limites ;
- fiche methode recurrence ;
- exercices corriges probabilites conditionnelles et loi binomiale ;
- sujet type bac ;
- bareme ;
- ressource algorithmique Python.

Les brouillons invalides couvrent :

- placeholder restant ;
- `rights=unknown` ;
- `source_uri` pointant vers un chemin interdit.

Tous les `source_uri` du brouillon valide utilisent `synthetic://pilot/maths-terminale/...`.

## 5. Compilateur offline

Le module `rag_pedago.imports.pilot_manifest_compiler` fournit :

- `load_filled_draft(path)` ;
- `iter_filled_items(data)` ;
- `validate_filled_item(item)` ;
- `validate_filled_draft(path)` ;
- `compile_filled_draft_to_jsonl_text(path)` ;
- `build_compile_report(path)` ;
- `main()`.

La CLI supporte :

```bash
python -m rag_pedago.imports.pilot_manifest_compiler data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml --check
python -m rag_pedago.imports.pilot_manifest_compiler data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml --emit-jsonl
```

La cible Makefile non destructive ajoutee :

```bash
make pilot-compile-check
```

## 6. Regles de validation

Le compilateur refuse :

- tout placeholder `A_REMPLIR` ou `A_CONFIRMER` ;
- `rights=unknown` ;
- les chemins `/srv/nexusreussite/rag-ui` ;
- les chemins `/home/alaeddine/Bureau/rag-local` ;
- les marqueurs de secrets dans `source_uri` ;
- l'incoherence `extra.zone=aefe_tunisie` sans `establishment_context_ref=aefe` ;
- l'incoherence `establishment_context_ref=aefe` sans `extra.zone=aefe_tunisie` ;
- l'incoherence `candidat=scolarise` avec `candidate_status_ref` different de `scolarise` ;
- tout item qui ne valide pas `DocumentMeta`.

Le JSONL produit est compact, trie par `doc_id` et avec cles JSON triees.

## 7. Chaine validee en dry-run

Les tests executent la chaine sur le JSONL compile dans un `tmp_path` :

- `import_manifest_directory(..., dry_run=True)` ;
- readiness ;
- coverage avec `taxonomy/maths/terminale_specialite.yml` ;
- gate ;
- review package.

Resultat attendu et observe dans les tests cibles :

- directory dry-run : `dry_run_success` ;
- readiness : `ready` ;
- coverage : `coverage_ok` ;
- gate : `ready_for_controlled_import` ;
- review package : `ready_for_review`.

## 8. Tests ajoutes ou modifies

Ajout :

- `tests/unit/test_pilot_manifest_compiler.py`

Les tests couvrent :

- existence et taille du brouillon valide ;
- statut `ready` ;
- compilation JSONL ;
- validation `DocumentMeta` de chaque ligne ;
- dry-run manifest directory ;
- readiness, coverage, gate et review ;
- rejets placeholder, `rights=unknown` et chemin interdit ;
- absence d'ouverture de `source_uri` ;
- absence de `data/staging` et de documents reels ;
- CLI `--check` et `--emit-jsonl` ;
- scan des fixtures contre secrets ;
- isolation vis-a-vis de `rag-local`.

## 9. Tests executes

Commandes executees pendant le lot :

```bash
pytest tests/unit/test_pilot_manifest_compiler.py -q
make pilot-compile-check
python -m rag_pedago.imports.pilot_manifest_compiler data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml --emit-jsonl
make doctor
make project-doctor
make test
```

## 10. Resultats

Resultats intermediaires :

```text
pytest tests/unit/test_pilot_manifest_compiler.py -q : 16 passed
make pilot-compile-check : status ready, 7 items, 0 issue
make doctor : OK
make project-doctor : OK
make test : 316 passed
```

## 11. Limites volontaires

- Aucun fichier source n'est lu.
- Aucun `source_uri` n'est ouvert.
- Aucun hash n'est calcule automatiquement.
- Aucun PDF ou document reel n'est cree.
- Aucun dossier `data/staging` n'est cree.
- Aucun import reel dans le ledger n'est lance.
- Aucun parsing, embedding, Qdrant, PostgreSQL ou LLM runtime n'est utilise.

## 12. Controles de surete

Le scan demande sur le module compilateur ne detecte aucun motif :

- `requests`, `httpx`, `urllib`, `socket` ;
- `subprocess` ;
- `qdrant`, `psycopg`, `docker` ;
- `open(` ;
- `read_bytes`, `write_bytes` ;
- `Path(...source_uri` ;
- `exists(`.

Les fixtures et templates sont verifiees contre les fichiers sensibles et documents reels.

## 13. Risques restants

- Le brouillon rempli reste synthetique.
- Un futur brouillon reel devra etre renseigne manuellement et repasser tous les controles.
- Le compilateur ne prouve pas la qualite pedagogique du contenu reel.
- Le parsing documentaire reste interdit tant qu'un lot dedie n'est pas valide.

## 14. Verdict

COMMIT_RECOMMANDÉ

## 15. Recommandation pour le lot 15E

Preparer un lot de validation humaine d'un brouillon reel minimal, toujours metadata-only,
avec compilation offline, gate, review package et approbation, sans lecture de document source
ni ingestion documentaire.
