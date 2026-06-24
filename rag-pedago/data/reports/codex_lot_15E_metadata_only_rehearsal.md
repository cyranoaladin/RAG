# Rapport Codex — Lot 15E : rehearsal metadata-only avec review synthétique

## 1. Objectif

Valider une répétition générale metadata-only du corpus pilote mathématiques terminale spécialité, depuis un brouillon synthétique rempli jusqu'à un import contrôlé dans un ledger temporaire audité.

La chaîne répétée est :

filled draft synthétique -> compilation JSONL -> import manifest dry-run -> readiness -> coverage -> gate -> review package -> décision humaine synthétique -> controlled import metadata-only dans ledger temporaire -> audit ledger temporaire.

## 2. Incident de contexte corrigé

Pendant la première tentative du lot 15E, le shell était positionné dans le dépôt interdit `/home/alaeddine/Bureau/rag-local`. Un fichier de test non suivi a été créé par erreur :

`/home/alaeddine/Bureau/rag-local/tests/unit/test_pilot_metadata_rehearsal.py`

Correction appliquée :

- vérification par `git status --short --branch` dans `rag-local`;
- vérification que `git ls-files -- tests/unit/test_pilot_metadata_rehearsal.py` ne retournait rien;
- suppression ciblée uniquement du fichier accidentel non suivi;
- revérification que l'artefact n'existe plus dans `rag-local`;
- reprise du lot dans `/home/alaeddine/Bureau/rag-pedago` avec chemins absolus pour les créations.

Impact :

- aucun fichier suivi de `rag-local` n'a été modifié;
- aucun dossier de `rag-local` n'a été supprimé;
- aucun fichier du RAG historique n'a été copié;
- toutes les modifications effectives du lot sont dans `rag-pedago`.

## 3. Point de départ Git

Point de départ validé :

- branche : `main`;
- dernier commit : `1180b51 feat: add offline pilot manifest compiler`;
- `make doctor` : OK;
- `make project-doctor` : OK;
- `make test` : 316 passed.

## 4. Fichiers créés ou modifiés

Fichiers créés :

- `rag_pedago/imports/pilot_metadata_rehearsal.py`
- `tests/unit/test_pilot_metadata_rehearsal.py`
- `data/reports/codex_lot_15E_metadata_only_rehearsal.md`

Fichier modifié :

- `Makefile`

## 5. Chaîne répétée

Le module `rag_pedago.imports.pilot_metadata_rehearsal` orchestre uniquement les modules existants :

- compilation du brouillon via `pilot_manifest_compiler`;
- dry-run via `import_manifest_directory(..., dry_run=True)`;
- readiness via `build_readiness_report`;
- coverage via `build_coverage_report`;
- gate via `build_gate_report`;
- review package via `build_review_package`;
- approbation synthétique via `approve_review_package`;
- import contrôlé via `controlled_import_manifest_directory`.

Le module ne crée pas de pipeline parallèle.

## 6. Décision humaine synthétique

La décision est générée dans le dossier temporaire de rehearsal, avec :

- reviewer : `synthetic-reviewer`;
- decision : `approved`;
- notes : `synthetic=true; scope=metadata-only rehearsal; no_real_documents=true; no_source_uri_opened=true`.

Elle sert uniquement à tester le mécanisme d'approbation metadata-only.

## 7. Ledger temporaire

Le controlled import utilise un SQLite sous le workspace temporaire fourni par le test ou par l'option CLI `--tmp`.

Le ledger temporaire contient :

- les documents metadata-only;
- les runs manifest-only;
- le review package;
- la décision;
- la tentative d'import contrôlé;
- les vérifications d'audit.

Aucune écriture n'est faite dans `data/ledger/rag_pedago.sqlite`.

## 8. Règles de sûreté contrôlées

Contrôles ajoutés :

- refus d'un output sous `/srv/nexusreussite/rag-ui`;
- refus d'un output sous `/home/alaeddine/Bureau/rag-local`;
- refus d'un output contenant un marqueur de secret;
- aucune utilisation de `data/staging`;
- aucune ouverture de `source_uri`;
- aucun document réel créé;
- aucun PDF/DOCX/PPTX/XLSX créé;
- aucun appel réseau;
- aucun Qdrant;
- aucune modification de schéma;
- aucune modification de taxonomie officielle.

## 9. Tests ajoutés ou modifiés

Test ajouté :

- `tests/unit/test_pilot_metadata_rehearsal.py`

La cible Makefile non destructive ajoutée est :

- `pilot-rehearsal`

## 10. Tests exécutés

Tests et commandes exécutés :

```bash
pytest tests/unit/test_pilot_metadata_rehearsal.py -q
make pilot-rehearsal
make doctor
make project-doctor
make test
```

## 11. Résultats

Résultats observés :

- `tests/unit/test_pilot_metadata_rehearsal.py` : 8 passed.
- `make pilot-rehearsal` : rehearsal complète, `controlled_import_status=imported`, `ledger_audit_status=recorded`.
- `make doctor` : OK.
- `make project-doctor` : OK.
- `make test` : 324 passed.

Les validations ont été exécutées après création du module, des tests, de la cible Makefile et du rapport.

## 12. Limites volontaires

- aucun document réel;
- aucun PDF;
- aucun `data/staging`;
- aucun `source_uri` ouvert;
- aucune écriture dans le ledger permanent;
- aucun scraping;
- aucun Qdrant;
- aucun changement de schéma;
- aucune modification de taxonomie officielle;
- tout runtime écrit uniquement dans `tmp_path` ou dans un temporary directory CLI.

## 13. Risques restants

- la répétition couvre un corpus synthétique, pas un lot réel;
- la décision humaine est synthétique et ne remplace pas une revue Nexus;
- le contenu documentaire réel n'est toujours pas validé, lu ni parsé;
- les rapports runtime générés pendant les tests restent des artefacts temporaires ou ignorés.

## 14. Verdict

COMMIT_RECOMMANDÉ

## 15. Recommandation pour le lot 15F

Préparer un lot de validation humaine d'un premier brouillon réel metadata-only, sans ingestion documentaire, en utilisant le compilateur et la rehearsal comme garde-fous préalables.
