# Rapport de Lot : Réconciliation H2-C et Qualification des Portails Multilevel C2 et C3

## Phase

LOT_GO_LIVE_FINAL_BQ_CLOSE_H2C_C2_C3_MULTILEVEL_GATES

> **IMPORTANT — RAPPEL DE L'OBJECTIF FINAL DU CHANTIER GO-LIVE NEXUS**
> L'objectif final ne consiste pas uniquement à réduire des compteurs intermédiaires. L'objectif final impératif et non négociable est :
> - `GO_LIVE_READY = true` ;
> - `--assert-ready = 0` (exit code) ;
> - Production ready ;
> - Déploiement complet ;
> - RAG ingéré, interrogeable et fonctionnel ;
> - Rollback production éprouvé ;
> - Manifeste production signé ;
> - Aucune PII non décidée (`pii_undecided = 0`) ;
> - Aucune PR bloquante (`open_prs_blocking = 0`) ;
> - Aucune qualification ouverte (`go_live_qualification_blockers = 0`).
>
> Ce lot BQ reste un **lot technique intermédiaire**. Il n'autorise pas la production, ne modifie aucun current switch (`current_switch = 0`), ne prend aucune décision PII unilatérale (`pii_undecided = 149`), ne déploie aucun service en production et ne modifie aucune base de données de production (`production_db_writes = 0`).

---

## État Initial Vérifié

| Indicateur / Métrique | Valeur de Départ |
|---|---|
| Commit parent de base | `4e7c40b731823a517f1a29f3838c3794638bde68` (post PR #208) |
| Branche de lot | `go-live/qualify-h2c-c2-c3-multilevel-gates` |
| Statut initial readiness | `GO_LIVE_READY = false`, `--assert-ready = 1` |
| Bloqueurs de qualification ouverts | `8` (C1, C2, C3, COCKPIT_E2E, STAGING_EXTERNE, CONCURRENCE, SYNC_INCREMENTALE, MANIFESTE_PRODUCTION) |
| PRs bloquantes ouvertes | `0` |
| PII non décidées | `149` |
| Contenus refusés promus | `26` |
| Current switch / Production DB writes | `0` / `0` |

---

## Traitement Technique des PRs Historiques (#167 et #168)

Conformément au mandat strict :
- Les PRs #167 et #168 n'ont **pas été mergées directement** (anciennes, non mergeables, basées sur un historique obsolète).
- Leurs apports techniques minimaux et utiles ont été extraits, revalidés et reconstruits sur le commit de base actuel `4e7c40b731823a517f1a29f3838c3794638bde68`.

### Apport de la PR #167 (Sonde d'authentification API v2)
- Dans `services/rag-engine/tests/integration/test_multilevel_real_ingestion.py` :
  - Génération d'un registre synthétique d'API clients `RAG_API_CLIENTS` avec scope `rag:search`.
  - Injection dans l'environnement du sous-processus uvicorn et passage de l'en-tête `X-RAG-API-Key`.
  - Résout le blocage 401 sur le middleware de contrôle des métriques `require_api_scope`.

### Apport de la PR #168 (Recalcul et réalignement des digests d'autorité)
- Dans `services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py` :
  - Recalcul des empreintes exactes depuis les artefacts du dépôt sur `main` :
    - `RELEASE_SHA = "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"` (remplace l'ancienne constante obsolète `d8ee6703...`)
    - `DOCUMENT_TYPES_SHA = "3518fe87d4394a4615c10887f276d95cfd58f517adb58af6f8efc686f242561b"` (remplace l'ancienne constante obsolète `ce5e51b7...`)

---

## Preuves Réelles et Scellement Cryptographique C2 et C3

### Bloqueur C2 : Ingestion Multilevel Réelle Bout en Bout
- **Test exécuté** : `pytest -v services/rag-engine/tests/integration/test_multilevel_real_ingestion.py` (succès 100% en 466.57s).
- **Environnement** :
  - PostgreSQL 16 éphémère (Docker jetable, détruit en teardown, 0 conteneur résiduel).
  - Miroir PDF nommé : `/home/alaeddine/nexus-drive-mirror-20260912` (les 11 PDF requis par la release sont vérifiés présents et intègres).
  - Évidence PII : `/home/alaeddine/Documents/NEXUS_RAG_H2_EVIDENCE/multilevel_pii_full_candidates_20260812_policy_v5.json` (SHA `46d6c738...`).
  - Modèles locaux vérifiés : E5 large (`e2c7384b...`) et reranker ms-marco (`bdcedc4d...`).
- **Cardinalités et Assertions Vérifiées** :
  - 10 collections cibles couvertes.
  - 11 artefacts ingérés et 11 placements publiés.
  - 353 chunks générés et indexés dans pgvector.
  - API v2 démarrée, authentifiée et testée sur 30 requêtes HTTP (3 requêtes par collection) : citations, numéros de pages et extraits textuels validés.
  - Isolation cross-scope démontrée (tentative de requête hors portée renvoie rigoureusement 403).
- **Attestation scellée** :
  - `docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.json`
  - `docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.sha256`

### Bloqueur C3 : Worker CLI Multilevel Bout en Bout
- **Test exécuté** : `pytest -v services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py` (succès 100% en 94.19s).
- **Environnement** :
  - Deux instances PostgreSQL éphémères (control_pg et product_pg, détruites en teardown, 0 conteneur résiduel).
  - Exécution en sous-processus des CLI réels de production : `ingestor.ingestion_worker.multilevel_cli` (Worker A) et `multilevel_publication_resume_cli` (Worker B).
- **Cardinalités et Assertions Vérifiées** :
  - Campagne span sur 2 collections cibles (`rag_nexus_maths_quatrieme_tc` et `rag_nexus_nsi_premiere_specialite`).
  - 2 propositions de revue générées par Worker A.
  - 2 publications de chunks attestées par Worker B.
  - Autorités intègres, zéro secret fuité, zéro mutation externe.
- **Attestation scellée** :
  - `docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.json`
  - `docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.sha256`

---

## Câblage dans `build_qualification_blockers.py`

Les fonctions `verifier_c2(racine)` et `verifier_c3(racine)` ont été ajoutées au constructeur canonique :
- Contrôle cryptographique strict du fichier SHA-256 de chaque preuve.
- Refus systématique si `proof=null`, si `verification_status != "VERIFIED"`, ou si `observed_at_main_sha` diverge du commit attendu (`4e7c40b731823a517f1a29f3838c3794638bde68`).
- Refus si `docker_residues_after_test > 0`, si `production_db_writes > 0` ou si `current_switch != 0`.
- Refus en cas d'écart ou de divergence sur l'une des autorités sous-jacentes.
- Enregistrement impératif du contrat de non-fermeture `does_not_close` sur C1, COCKPIT_E2E, STAGING_EXTERNE, CONCURRENCE, SYNC_INCREMENTALE, MANIFESTE_PRODUCTION, PII_UNDECIDED, RELEASE_PROMOTED_REFUSED_CONTENTS, GO_LIVE_READY.

---

## Évolution des Bloqueurs de Qualification

| Bloqueur | Statut Avant BQ | Statut Après BQ | Justification / Preuve |
|---|---|---|---|
| **C1** (Autorité de release et couverture promue) | OUVERT | OUVERT | 26 contenus refusés promus dans la baseline release. |
| **C2** (Ingestion multilevel réelle bout en bout) | OUVERT | **CLOS** | Ingestion réelle des 10 collections, 353 chunks, 30 requêtes HTTP et citations prouvées, preuve scellée. |
| **C3** (Worker CLI multilevel bout en bout) | OUVERT | **CLOS** | Worker A et B CLI testés en réel sur 2 collections, publications attestées, preuve scellée. |
| **C4** (Contrat de retrieval sur corpus servable) | CLOS | CLOS | Validé au lot BM. |
| **C5** (Autorité d'accès et portées) | CLOS | CLOS | Validé au lot BO. |
| **C6** (Qualification CAS et couverture de magasin) | CLOS | CLOS | Validé au lot BP. |
| **COCKPIT_E2E** (Cockpit bout en bout API retrieval) | OUVERT | OUVERT | Validation e2e cockpit requise. |
| **STAGING_EXTERNE** (Staging externe qualifié) | OUVERT | OUVERT | Staging externe non ingéré. |
| **CONCURRENCE** (Comportement sous concurrence) | OUVERT | OUVERT | Test de charge non exécuté. |
| **SYNC_INCREMENTALE** (Synchronisation incrémentale) | OUVERT | OUVERT | Test incrémental requis. |
| **MANIFESTE_PRODUCTION** (Manifeste production signé) | OUVERT | OUVERT | Manifeste non signé. |
| **PII_UNDECIDED** (Décision PII humaine) | OUVERT | OUVERT | 149 contenus restent non décidés. |
| **RELEASE_PROMOTED_REFUSED_CONTENTS** (Refusés promus) | OUVERT | OUVERT | 26 contenus refusés dans la baseline release. |

**Total des bloqueurs ouverts** : passage de **8 à 6**.

---

## État de Readiness Avant / Après

| Paramètre | Avant BQ | Après BQ |
|---|---|---|
| `GO_LIVE_READY` | `false` | `false` |
| `--assert-ready` exit code | `1` | `1` |
| `open_prs_blocking` | `0` | `0` |
| `open_prs_disposition_unknown` | `0` | `0` |
| `go_live_qualification_blockers` | `8` | **`6`** |
| `pii_undecided` | `149` | `149` |
| `release_promoted_refused_contents` | `26` | `26` |
| `current_switch` | `0` | `0` |
| `production_db_writes` | `0` | `0` |
| `production_deployments` | `0` | `0` |

---

## Vérifications d'Hygiène, Gouvernance et Tests

1. **Gardes de gouvernance** : 18 verrous vérifiés et conformes (`check-governance-locks.sh` OK, 16 tests de verrous OK).
2. **Unicité d'autorité (Règle R1)** : `NEXUS-AUTHORITY-UNIQUENESS-V1: PASS`.
3. **Hygiène du dépôt** : Racine propre, 0 fichier non suivi indésirable (`test-repository-hygiene.sh` PASS).
4. **Tests automatisés** :
   - Producteur de blocages : 65 tests passés (`test_qualification_blockers_producer.py`).
   - Suite hermétique de qualification : 86 tests passés (`scripts/qualification/tests/`).
   - Tests globaux scripts : 450 tests passés (`scripts/tests/`).
   - Tests unitaires rag-engine : 100% passés (`services/rag-engine/tests -m "not integration"`).
   - Ingestion réelle multilevel : passée en 466.57s (`test_multilevel_real_ingestion.py`).
   - Worker CLI multilevel : passé en 94.19s (`test_multilevel_worker_cli_e2e.py`).
   - Linting ruff et formatage git diff : 0 anomalie.

---

## Décision

**`GO_LIVE_BQ_PR_OPEN`**
- Les preuves H2-C pour C2 et C3 sont rigoureusement réétablies et scellées sur le main actuel.
- Les bloqueurs C2 et C3 sont formellement fermés, portant les bloqueurs ouverts à 6.
- Les invariants de sécurité restent hermétiquement scellés.
- La PR est prête à être ouverte pour revue humaine trusted.
