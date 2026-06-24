# Rapport Codex — Lot 15A : cartographie et protocole corpus pilote

## 1. Objectif

Cartographier l'état réel du dépôt après les lots 1 à 14 et cadrer un futur
corpus pilote mathématiques terminale spécialité, sans ingestion documentaire,
sans scraping, sans réseau et sans lecture de `source_uri`.

## 2. Point de départ Git

Point de départ vérifié :

```text
branche: main
dernier commit: a822503 chore: strengthen project contracts and agent guardrails
statut initial: propre
```

## 3. Derniers commits

```text
a822503 chore: strengthen project contracts and agent guardrails
0fa3756 feat: add review and controlled import audit ledger
9276da5 chore: harden human review approval chain
490055a feat: add human review package and approval gate
d490271 feat: add official reference explainability
c8a9272 feat: add official reference compatibility resolver
ed76275 test: add official profiles manifest fixtures
5f0613c feat: enforce official references in manifest quality
0bf6cbc chore: harden official reference integrity
60869de feat: add official education reference model
```

## 4. Tests exécutés avant modification

Commandes :

```bash
make doctor
make project-doctor
make test
```

Résultats :

- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 276 passed.

## 5. Capacités réellement implémentées

### Schémas

Les modèles Pydantic existent pour :

- documents et chunks ;
- profils élèves et profils d'examen ;
- taxonomies ;
- sources et confiance source ;
- retrieval contractuel ;
- référentiel officiel ;
- ledger.

### Taxonomies et référentiel officiel

Le dépôt contient :

- taxonomies communes ;
- taxonomie mathématiques terminale spécialité ;
- taxonomie NSI terminale ;
- références officielles structurées dans `data/reference/` ;
- claims officiels ;
- statuts candidats ;
- contextes d'établissement ;
- examens composés.

### Ledger

Le ledger SQLite est implémenté avec :

- migrations versionnées ;
- runs, documents, états, chunks, erreurs ;
- audit des review packages ;
- audit des décisions humaines ;
- audit des tentatives d'import contrôlé ;
- vérifications d'import contrôlé ;
- diagnostics `ledger-doctor`.

### Manifests et imports contrôlés

Le dépôt sait :

- importer un manifest JSONL local vers le ledger ;
- importer un répertoire de manifests ;
- faire un dry-run ;
- détecter doublons et conflits ;
- produire des rapports Markdown/JSON ;
- appliquer une politique qualité ;
- bloquer selon les références officielles ;
- produire readiness, coverage et gate ;
- générer review package ;
- enregistrer approval/rejection ;
- exécuter controlled import metadata-only ;
- auditer les étapes dans SQLite.

### Doctor et project-doctor

`make doctor` vérifie le socle et les secrets évidents.

`make project-doctor` vérifie :

- docs clés ;
- contrats ;
- `.gitignore` runtime ;
- absence de `.env` suivi ;
- tokens sensibles évidents hors exceptions ;
- absence d'import réseau dans `rag_pedago/imports` ;
- absence de pattern d'ouverture `source_uri`.

### Tests

La suite actuelle couvre 276 tests : schémas, taxonomies, référentiel officiel,
resolver, qualité manifests, readiness, coverage, gate, review, controlled
import, audit ledger, contracts et doctors.

## 6. Capacités documentées mais non implémentées

Les capacités suivantes sont documentées comme futures mais non opérationnelles :

- parsing PDF ;
- OCR ;
- normalisation documentaire réelle ;
- chunking pédagogique ;
- embeddings texte ou visuels ;
- Qdrant ;
- PostgreSQL ;
- retrieval opérationnel ;
- API cockpit ;
- réponses LLM ;
- ingestion documentaire réelle.

## 7. Capacités partielles ou ambiguës

- `pipeline/` contient seulement `.gitkeep` et `__init__.py`.
- `retrieval/` contient seulement `.gitkeep` et `__init__.py`.
- Le Makefile expose encore des cibles futures (`ingest`, `verify`,
  `eval-retrieval`, `watch`, `api`, `scrape-official`) dont les modules ne sont
  pas réellement implémentés ou ne doivent pas être lancés sans lot dédié.
- Des rapports runtime ignorés existent localement dans `data/reports/`.
- `data/ledger/rag_pedago.sqlite` peut exister localement comme artefact runtime
  ignoré.

## 8. Risques identifiés

- Lancer des cibles futures du Makefile hors protocole peut échouer ou créer une
  confusion sur le périmètre réel.
- Les artefacts runtime nombreux dans `data/reports/` ne doivent pas être
  versionnés hors rapports Codex.
- Un futur corpus pilote doit éviter toute copie de documents historiques ou
  sensibles.
- Les documents AEFE Tunisie exigent une validation humaine des modalités
  locales et ne doivent pas être affirmés à partir d'une source `pending`.
- Toute ingestion réelle nécessite un lot dédié séparant staging, manifests,
  review humaine et import metadata-only.

## 9. Fichiers créés ou modifiés

- `docs/PILOT_CORPUS_PROTOCOL.md`
- `data/reports/codex_lot_15A_state_map_and_pilot_protocol.md`

## 10. Protocole corpus pilote créé

Le protocole cible :

- niveau terminale ;
- voie générale ;
- spécialité mathématiques ;
- AEFE Tunisie ;
- candidat scolarisé ;
- ressources officielles, cours, fiches méthode, exercices, corrigés, annales,
  sujets bac et barèmes.

Il précise :

- documents autorisés/interdits ;
- métadonnées obligatoires ;
- structure manifest attendue ;
- droits et visibilité ;
- provenance officielle ;
- règles candidat scolarisé/candidat individuel ;
- règles AEFE Tunisie ;
- contrôles avant import ;
- validation humaine ;
- critères d'acceptation ;
- requêtes futures de test.

## 11. Tests exécutés après modification

À exécuter en fin de lot :

```bash
make doctor
make project-doctor
make test
git diff --stat HEAD
git diff --name-status HEAD
git status --short --branch
```

## 12. Résultats

- `make doctor` : OK.
- `make project-doctor` : OK.
- `make test` : 276 passed.
- `git diff --stat HEAD` : aucun fichier suivi modifié.
- `git diff --name-status HEAD` : aucun fichier suivi modifié.
- `git status --short --branch` : deux fichiers non suivis, correspondant au
  lot 15A :
  - `docs/PILOT_CORPUS_PROTOCOL.md`
  - `data/reports/codex_lot_15A_state_map_and_pilot_protocol.md`
- Recherche de fichiers sensibles : aucun résultat.

## 13. Verdict

COMMIT_RECOMMANDÉ

## 14. Recommandation pour le lot 15B

Ne pas lancer d'ingestion documentaire. Le lot 15B devrait créer un dossier de
staging vide ou synthétique et un modèle de manifest pilote sans fichier réel,
puis valider uniquement la chaîne readiness/coverage/gate/review sur données
fictives ou métadonnées préparées manuellement.
