# Rapport Codex — Lot 16A : migration de chemins et audit de nettoyage

## 1. Objectif

Le lot 16A vérifie la nouvelle organisation locale sous `/home/alaeddine/Bureau/RAG`, migre les chemins actifs de `rag-pedago`, confirme l'état du rapport 15J et produit un audit de nettoyage sans suppression.

Aucun fichier n’a été supprimé pendant le lot 16A.

Verdict : READY_FOR_CLEANUP_REVIEW.

## 2. Nouveau workspace détecté

Workspace confirmé :

- racine : `/home/alaeddine/Bureau/RAG` ;
- dépôt pédagogique : `/home/alaeddine/Bureau/RAG/rag-pedago` ;
- dépôt historique : `/home/alaeddine/Bureau/RAG/rag-local`.

Les deux dossiers attendus existent. Le listing `find . -maxdepth 2 -type d` montre notamment :

- `./rag-pedago/.git` ;
- `./rag-local/.git` ;
- `./rag-pedago/data`, `./rag-pedago/docs`, `./rag-pedago/rag_pedago`, `./rag-pedago/tests` ;
- `./rag-local/docs`, `./rag-local/infra`, `./rag-local/scripts`, `./rag-local/src`, `./rag-local/tests` ;
- des caches locaux dans `rag-local` : `.venv`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`.

## 3. État Git de rag-pedago

`rag-pedago` est un dépôt Git séparé :

```text
git rev-parse --show-toplevel
/home/alaeddine/Bureau/RAG/rag-pedago
```

État initial avant corrections :

```text
## main
```

Derniers commits observés :

```text
ccc9844 (HEAD -> main) docs: audit metadata-only governance chain
fe67d68 feat: add metadata-only preflight
17d31b6 feat: add real draft unlock gate
c629b5c feat: add human unlock guard
1f266bb feat: add real draft metadata guard
d32c5da feat: add metadata-only pilot rehearsal
1180b51 feat: add offline pilot manifest compiler
dbb4236 feat: add offline pilot manifest preparation kit
```

## 4. État Git de rag-local

`rag-local` est un dépôt Git séparé :

```text
git rev-parse --show-toplevel
/home/alaeddine/Bureau/RAG/rag-local
```

État observé en lecture seule :

```text
## main...origin/main
?? .windsurf/
?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt
```

Derniers commits observés :

```text
668d778 (HEAD -> main, origin/main, origin/HEAD) fix: address review feedback (OCR robustness, backfill pagination, search fallback)
e9a93ef Merge pull request #51 from cyranoaladin/fix/drive-office-dispatch-v2
8508b43 (origin/fix/drive-office-dispatch-v2, fix/drive-office-dispatch-v2) Fix typing for Drive byte download helper
a5188d1 Handle Drive Office files without PDF misclassification
6faace5 Merge pull request #50 from cyranoaladin/fix/rag-prod-20260419
61393b5 Add OCR fallback for scanned Drive PDFs
ebd2eda Make Drive sync state collection-aware
d4a62eb Add reusable backfill script for dedicated collections
```

Aucune modification n'a été faite dans `rag-local`.

## 5. État du lot 15J

Le rapport 15J existe dans `rag-pedago` :

```text
data/reports/codex_lot_15J_metadata_governance_review.md
```

Il est déjà committé. Le commit correspondant est en tête de `main` :

```text
ccc9844 (HEAD -> main) docs: audit metadata-only governance chain
```

## 6. Chemins anciens détectés

Recherche initiale des anciens chemins dans `rag-pedago` :

- anciens chemins actifs détectés dans des modules Python, tests, docs et une fixture synthétique ;
- nombreux anciens chemins détectés dans des rapports runtime historiques sous `data/reports/`.

Après correction :

- `grep -RIn --exclude-dir=.git "/home/alaeddine/Bureau/rag-pedago\|/home/alaeddine/Bureau/rag-local" . | wc -l` : `1187` lignes ;
- fichiers contenant encore un ancien chemin hors `data/reports/` : `0` ;
- les occurrences restantes sont confinées aux anciens rapports historiques et ne sont pas exécutées.

## 7. Corrections de chemins appliquées

Une constante centrale a été ajoutée :

```text
rag_pedago/paths.py
```

Elle définit :

- `WORKSPACE_ROOT = /home/alaeddine/Bureau/RAG` ;
- `REPO_ROOT = /home/alaeddine/Bureau/RAG/rag-pedago` ;
- `RAG_LOCAL_ROOT = /home/alaeddine/Bureau/RAG/rag-local` ;
- `PRODUCTION_RAG_UI_ROOT = /srv/nexusreussite/rag-ui`.

Fichiers actifs corrigés :

- `rag_pedago/imports/metadata_preflight.py` ;
- `rag_pedago/imports/pilot_metadata_rehearsal.py` ;
- `rag_pedago/imports/real_draft_guard.py` ;
- `rag_pedago/imports/human_unlock_guard.py` ;
- `rag_pedago/imports/pilot_manifest_template.py` ;
- `tests/unit/test_metadata_preflight.py` ;
- `tests/unit/test_pilot_metadata_rehearsal.py` ;
- `tests/unit/test_real_draft_guard.py` ;
- `tests/unit/test_human_unlock_guard.py` ;
- `tests/unit/test_real_draft_unlock_gate.py` ;
- `tests/unit/test_pilot_manifest_template.py` ;
- `tests/unit/test_pilot_manifest_compiler.py` ;
- `tests/unit/test_pilot_math_terminale_fixtures.py` ;
- `README.md` ;
- `docs/LEGACY_RAG_READONLY.md` ;
- `docs/contracts/invariants.yml` ;
- `AGENTS.md` ;
- `data/fixtures/pilot_math_terminale/real_draft_guard/metadata_candidate.invalid_forbidden_path.jsonl`.

Les anciens rapports Codex et rapports runtime historiques n'ont pas été réécrits.

## 8. Tests exécutés après correction

Commandes exécutées après correction :

```text
make metadata-preflight
make doctor
make project-doctor
make test
```

Résultats :

- `make metadata-preflight` : OK, `metadata_preflight_ready`, `issues: 0` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : OK, `370 passed in 78.95s`.

## 9. Inventaire des fichiers nettoyables

Inventaire lecture seule depuis `/home/alaeddine/Bureau/RAG` :

```text
python_cache_count=3218
pyc_count=29653
backup_count=3
patch_diff_count=4
sqlite_db_count=2
runtime_report_count=2570
potential_secret_path_count=54
```

Répartition utile :

```text
rag_pedago_pycache_count=7
rag_pedago_pyc_count=91
rag_pedago_pytest_cache_count=1
rag_local_pycache_count=3211
rag_local_pyc_count=29562
rag_local_pytest_cache_count=1
rag_local_venv_exists=yes
rag_pedago_data_staging=absent
rag_pedago_real_doc_count=0
```

Fichiers backup détectés :

```text
./rag-local/infra/.env.bak_20251106_194524
./rag-local/infra/.env.bak_20251106_194728
./rag-local/infra/.env.bak_20251106_195357
```

Fichiers patch/diff détectés :

```text
./rag-local/patch-ci-smoke.diff
./rag-local/patch-ci.diff
./rag-local/patch-metrics-quickcheck.diff
./rag-local/patch-readme-metrics.diff
```

Bases locales détectées :

```text
./rag-local/drive_sync_state.db
./rag-pedago/data/ledger/rag_pedago.sqlite
```

Exemples de rapports runtime générés :

```text
rag-pedago/data/reports/controlled_import_batch-001.json
rag-pedago/data/reports/controlled_import_batch-001.md
rag-pedago/data/reports/coverage_batch-001.json
rag-pedago/data/reports/coverage_batch-001.md
rag-pedago/data/reports/gate_batch-001.json
rag-pedago/data/reports/gate_batch-001.md
rag-pedago/data/reports/manifest_directory_import_batch-001-dry.md
rag-pedago/data/reports/manifest_directory_import_batch-001.md
```

Chemins sensibles ou assimilés détectés :

- nombreux faux positifs dans `rag-local/.venv` et `rag-local/.mypy_cache` liés à des librairies Python ;
- certificats de bundle dans `.venv` : `certifi/cacert.pem`, `grpc/_cython/_credentials/roots.pem`, `pip/_vendor/certifi/cacert.pem` ;
- fichiers sensibles réels ou à traiter comme tels dans `rag-local` : `infra/.env`, `src/ui/.env`, backups `.env.bak_*` ;
- scripts à examiner : `rag-local/infra/scripts/enable-gdrive-prod.sh`, `rag-local/scripts/generate-secrets.sh` ;
- faux positif attendu dans `rag-pedago` : `data/fixtures/pilot_math_terminale/human_unlock/human_unlock.invalid_secret_marker.json`.

Le faux positif `human_unlock.invalid_secret_marker.json` contient uniquement une fixture synthétique avec la note `synthetic secret marker only`; aucun secret réel n'a été identifié dans ce fichier.

## 10. Fichiers supprimables après validation humaine

Supprimables quasi sûrs après validation :

- dossiers `__pycache__` ;
- fichiers `.pyc` ;
- caches pytest ;
- caches ruff/mypy si non nécessaires à une session locale ;
- fichiers temporaires évidents.

Attention : la majorité du volume vient de `rag-local/.venv`. Ne pas supprimer automatiquement la `.venv` sans décision humaine, car elle peut servir au dépôt historique.

## 11. Fichiers à archiver ou déplacer

À envisager pour déplacement vers `archives/` ou `reports/runtime/` après validation :

- rapports runtime très nombreux dans `rag-pedago/data/reports` ;
- anciens rapports `manifest_directory_import_batch-*` ;
- anciens rapports `coverage_batch-*`, `gate_batch-*`, `controlled_import_batch-*` ;
- anciens `review_package_*` runtime ;
- fichiers `.diff` / `.patch` de `rag-local` après revue humaine ;
- anciens tree locaux comme `rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 12. Fichiers à conserver

À conserver :

- rapports Codex de lots, dont 15A à 15J ;
- protocoles et checklists ;
- fixtures synthétiques ;
- schémas ;
- taxonomies officielles validées ;
- docs d'architecture ;
- tests ;
- module central `rag_pedago/paths.py`.

## 13. Fichiers à ne jamais supprimer automatiquement

À ne jamais supprimer automatiquement :

- fichiers `creds`, `.env`, backups `.env.bak_*` ;
- `rag-pedago/data/ledger/rag_pedago.sqlite` ;
- `rag-local/drive_sync_state.db` ;
- uploads ;
- raw ;
- données sources ;
- fichiers d'infra production ;
- historiques Git ;
- fichiers sous `infra/creds` ou `creds`.

## 14. Fichiers à examiner humainement

À examiner humainement :

- `rag-local/patch-ci-smoke.diff` ;
- `rag-local/patch-ci.diff` ;
- `rag-local/patch-metrics-quickcheck.diff` ;
- `rag-local/patch-readme-metrics.diff` ;
- `rag-local/rag-ui-nexusreussite-academy-tree-20260613_222121.txt` ;
- `rag-local/drive_sync_state.db` ;
- `rag-local/infra/.env` ;
- `rag-local/src/ui/.env` ;
- `rag-local/infra/.env.bak_20251106_194524` ;
- `rag-local/infra/.env.bak_20251106_194728` ;
- `rag-local/infra/.env.bak_20251106_195357` ;
- rapports runtime non versionnés ou redondants dans `rag-pedago/data/reports`.

## 15. Proposition de nouvelle arborescence

Proposition documentaire, non créée pendant ce lot :

```text
/home/alaeddine/Bureau/RAG/
├── README.md
├── rag-pedago/
├── rag-local/
├── archives/
│   ├── rag-pedago-runtime-reports/
│   ├── rag-local-old-patches/
│   └── old-trees/
├── ops/
│   ├── scripts/
│   └── checklists/
└── workspace/
    └── scratch/
```

Règles proposées :

- `rag-pedago/` reste le dépôt actif pour le RAG pédagogique ;
- `rag-local/` reste en lecture seule ;
- `archives/rag-pedago-runtime-reports/` reçoit uniquement des rapports runtime approuvés pour archivage ;
- `archives/rag-local-old-patches/` reçoit les patchs historiques après revue ;
- `archives/old-trees/` reçoit les anciens inventaires `tree.txt` ;
- `workspace/scratch/` sert uniquement à des essais non versionnés et non documentaires.

## 16. Risques

Risques identifiés :

- volume élevé de caches et `.pyc`, surtout dans `rag-local/.venv` ;
- présence de `.env` et backups `.env.bak_*` dans `rag-local`, à ne jamais afficher ni copier ;
- `rag-pedago/data/reports` contient de nombreux rapports runtime historiques avec anciens chemins absolus ;
- `rag-pedago/data/ledger/rag_pedago.sqlite` existe et ne doit pas être supprimé ni modifié automatiquement ;
- déplacer des rapports sans politique claire peut casser des références documentaires ou l'audit historique ;
- supprimer la `.venv` de `rag-local` pourrait perturber un usage local du dépôt historique.

## 17. Prochaine étape recommandée

Lot 16B recommandé : revue humaine du rapport 16A puis décision explicite sur une politique de nettoyage sans suppression automatique.

Priorité 16B proposée :

1. valider la liste des fichiers à ignorer, archiver ou conserver ;
2. définir si les rapports runtime doivent rester dans `data/reports` ou migrer vers une archive ;
3. établir une checklist de nettoyage non destructive ;
4. seulement après validation, exécuter un lot dédié de déplacement/suppression contrôlée.

Message de commit proposé si ce rapport est accepté :

```text
docs: audit path migration and cleanup candidates
```
