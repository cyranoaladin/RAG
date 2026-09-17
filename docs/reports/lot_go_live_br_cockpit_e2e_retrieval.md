# Rapport de Lot : Qualification Bout en Bout Cockpit et API de Retrieval (COCKPIT_E2E)

## Phase

LOT_GO_LIVE_FINAL_BR_QUALIFY_COCKPIT_E2E_RETRIEVAL

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
> Ce lot BR reste un **lot technique intermédiaire**. Il n'autorise pas la production, ne modifie aucun current switch (`current_switch = 0`), ne prend aucune décision PII unilatérale (`pii_undecided = 149`), ne déploie aucun service en production et ne modifie aucune base de données de production (`production_db_writes = 0`).

---

## État Initial Vérifié

| Indicateur / Métrique | Valeur de Départ |
|---|---|
| Commit parent de base | `7769b72259d8e51749de07ab9a2dbc0a6e86ef28` (post PR #209) |
| Branche de lot | `go-live/qualify-cockpit-e2e-retrieval` |
| Statut initial readiness | `GO_LIVE_READY = false`, `--assert-ready = 1` |
| Bloqueurs de qualification ouverts | `6` (C1, COCKPIT_E2E, STAGING_EXTERNE, CONCURRENCE, SYNC_INCREMENTALE, MANIFESTE_PRODUCTION) |
| PRs bloquantes ouvertes | `0` |
| PII non décidées | `149` |
| Contenus refusés promus | `26` |
| Current switch / Production DB writes | `0` / `0` |

---

## Objectif Précis du Lot BR

Fermer le bloqueur **COCKPIT_E2E** (*Cockpit bout en bout contre l'API de retrieval*) en démontrant :
1. L'intégration réelle et non mockée entre le frontend/BFF Cockpit (Next.js) et le moteur de recherche (FastAPI RAG Engine) ;
2. La propagation sécurisée du jeton de session NextAuth et du jeton d'identité interne Nexus (`nexus-internal-token`) ;
3. Le respect des contrôles d'accès et des refus de sécurité (401 non authentifié, 403 non autorisé, 400 requête invalide) ;
4. La complétude et la navigabilité des citations retournées à l'utilisateur dans l'interface Cockpit (titre de source, URL, numéro de page, extrait de texte vérifié) ;
5. L'exécution hermétique et autonome avec 0 conteneur résiduel et 0 accès aux environnements de production.

---

## Architecture de Qualification Réelle

Le banc d'intégration mis en œuvre (`services/rag-engine/tests/integration/test_cockpit_e2e_retrieval.py`) orchestre une chaîne complète :

```
┌─────────────────────────────────────────────────────────────┐
│                 Banc de Qualification Réel                  │
├─────────────────┬───────────────────┬───────────────────────┤
│  PostgreSQL 16  │   Redis Server    │     RAG Engine v2     │
│   (pgvector)    │   (éphémère)      │   (FastAPI / Uvicorn) │
│   Port libre    │   Port libre      │       Port libre      │
└────────┬────────┴─────────┬─────────┴───────────┬───────────┘
         │                  │                     │
         │                  │                     │
         └──────────────────┼─────────────────────┘
                            │ (BFF Token / Internal Token)
                            ▼
              ┌───────────────────────────┐
              │   Cockpit Next.js Server  │
              │     (Serveur de Prod)     │
              │         Port libre        │
              └─────────────┬─────────────┘
                            │ (HTTP Session Cookie)
                            ▼
              ┌───────────────────────────┐
              │ Client HTTP d'Acceptance  │
              │     (Sonde de Test)       │
              └───────────────────────────┘
```

### Composants Clés Développés

1. **Générateur de jetons de session (`services/cockpit/scripts/mint-session-token.mjs`)** :
   - Génère le cookie chiffré NextAuth (`__Secure-authjs.session-token`) et le jeton interne Nexus (`NEXUS_INTERNAL_TOKEN_SECRET`).
   - Configure les réclamations de profil en conformité avec la portée pilote (`role: teacher`, `candidat: libre`, disciplines Terminale Maths et NSI).
   - Intègre les empreintes cryptographiques exactes du scope pilote scellé (`a1ed0fb1c7ec6344...`).

2. **Banc d'Acceptance Réel (`services/rag-engine/tests/integration/test_cockpit_e2e_retrieval.py`)** :
   - Ingestion préalable réelle de la release `prerentree_2026_2027` (11 artefacts, 10 collections, 353 chunks vectorisés avec E5 large).
   - Démarrage de Redis éphémère (`--save "" --appendonly no`) pour la révocation des tokens.
   - Démarrage du sous-processus FastAPI RAG Engine sur port dynamique.
   - Démarrage du serveur Cockpit Next.js sur port dynamique.
   - Exécution des vérifications protocolaires :
     - Refus 401 : appel sans cookie de session renvoie une réponse non autorisée.
     - Refus 403 : session sans rôle pédagogique ou sur collection interdite est rejetée.
     - Refus 400 : requête de recherche vide ou mal formée est rejetée.
     - Requête 200 Maths : recherche "Qu'est-ce qu'une suite géométrique ?" renvoie des résultats pertinents avec citations complètes.
     - Requête 200 NSI : recherche "Algorithme de Dijkstra et graphes pondérés" renvoie des résultats avec citations complètes.

3. **Vérificateur CLI Hermétique (`scripts/qualification/verify_cockpit_e2e_retrieval.py`)** :
   - Supporte le mode `--verify-only` pour vérification instantanée sans Docker ni réseau dans les environnements CI hermétiques.
   - Valide l'empreinte SHA-256 de la preuve, la conformité du commit parent `7769b72259d8e51749de07ab9a2dbc0a6e86ef28`, l'absence de mocks, le nombre de citations et l'absence de résidus Docker.

4. **Test Unitaire Hermétique (`scripts/qualification/tests/test_cockpit_e2e_hermetic_proof_integrity.py`)** :
   - Vérifie la cohérence structurelle et cryptographique de la preuve COCKPIT_E2E dans le pipeline de qualification hermétique.

---

## Preuve Scellée Cryptographiquement

- **Fichier de preuve** : `docs/reports/evidence/cockpit_e2e_retrieval_proof.json`
- **Fichier de sceau** : `docs/reports/evidence/cockpit_e2e_retrieval_proof.sha256`
- **Digest SHA-256** : `92d52a3abb866192ab8a94851e5765fd20dea5be96e07b27ab24fa919afa8a5b`
- **Contrôle d'intégrité** : `sha256sum -c docs/reports/evidence/cockpit_e2e_retrieval_proof.sha256` -> **OK**

### Extraits Clés de la Preuve Scellée

```json
{
  "observed_at_main_sha": "7769b72259d8e51749de07ab9a2dbc0a6e86ef28",
  "qualification_blocker": "COCKPIT_E2E",
  "verification_status": "VERIFIED",
  "docker_residues_after_test": 0,
  "production_db_writes": 0,
  "current_switch": 0,
  "verdicts": {
    "COCKPIT_SEARCH_ENDPOINT_200": true,
    "MOCK_ABSENCE_CONFIRMED": true,
    "REFUSAL_400_VERIFIED": true,
    "REFUSAL_401_VERIFIED": true,
    "REFUSAL_403_VERIFIED": true,
    "TEST_EXECUTION_PASSED": true
  },
  "citations_summary": {
    "citations_have_page_numbers": true,
    "citations_have_text_quotes": true,
    "citations_have_urls": true,
    "total_citations_verified": 2
  }
}
```

---

## Câblage dans `build_qualification_blockers.py`

La fonction `verifier_cockpit_e2e(racine)` a été implémentée dans `scripts/go_live/build_qualification_blockers.py` :
- Vérifie l'existence et l'intégrité SHA-256 de `cockpit_e2e_retrieval_proof.json`.
- Contrôle que `verification_status == "VERIFIED"` et que le commit parent observé correspond bien à la base du lot (`7769b72259d8e51749de07ab9a2dbc0a6e86ef28`).
- Contrôle les verdicts élémentaires (`TEST_EXECUTION_PASSED`, `COCKPIT_SEARCH_ENDPOINT_200`, `REFUSAL_401_VERIFIED`, `REFUSAL_403_VERIFIED`, `MOCK_ABSENCE_CONFIRMED`).
- Contrôle que `citations_have_urls`, `citations_have_page_numbers`, `citations_have_text_quotes` sont vrais et qu'au moins une citation a été validée.
- Contrôle l'absence de résidus Docker (`docker_residues_after_test == 0`) et l'absence d'écriture en production (`production_db_writes == 0`, `current_switch == 0`).
- Enregistre rigoureusement le contrat de non-fermeture `does_not_close` sur les bloqueurs restants (`C1`, `STAGING_EXTERNE`, `CONCURRENCE`, `SYNC_INCREMENTALE`, `MANIFESTE_PRODUCTION`, `PII_UNDECIDED`, `RELEASE_PROMOTED_REFUSED_CONTENTS`, `GO_LIVE_READY`).

---

## Évolution des Bloqueurs de Qualification

| Bloqueur | Statut Avant BR | Statut Après BR | Justification / Preuve |
|---|---|---|---|
| **C1** (Autorité de release et couverture promue) | OUVERT | OUVERT | 26 contenus refusés promus dans la baseline release. |
| **C2** (Ingestion multilevel réelle bout en bout) | CLOS | CLOS | Validé au lot BQ. |
| **C3** (Worker CLI multilevel bout en bout) | CLOS | CLOS | Validé au lot BQ. |
| **C4** (Contrat de retrieval sur corpus servable) | CLOS | CLOS | Validé au lot BM. |
| **C5** (Autorité d'accès et portées) | CLOS | CLOS | Validé au lot BO. |
| **C6** (Qualification CAS et couverture de magasin) | CLOS | CLOS | Validé au lot BP. |
| **COCKPIT_E2E** (Cockpit bout en bout API retrieval) | OUVERT | **CLOS** | Chaîne complète Cockpit <-> API v2 <-> pgvector validée, citations prouvées, refus 401/403/400 testés, preuve scellée. |
| **STAGING_EXTERNE** (Staging externe qualifié) | OUVERT | OUVERT | Staging externe non ingéré. |
| **CONCURRENCE** (Comportement sous concurrence) | OUVERT | OUVERT | Test de charge non exécuté. |
| **SYNC_INCREMENTALE** (Synchronisation incrémentale) | OUVERT | OUVERT | Test incrémental requis. |
| **MANIFESTE_PRODUCTION** (Manifeste production signé) | OUVERT | OUVERT | Manifeste non signé. |
| **PII_UNDECIDED** (Décision PII humaine) | OUVERT | OUVERT | 149 contenus restent non décidés. |
| **RELEASE_PROMOTED_REFUSED_CONTENTS** (Refusés promus) | OUVERT | OUVERT | 26 contenus refusés dans la baseline release. |

**Total des bloqueurs de qualification ouverts** : passage de **6 à 5**.

---

## État de Readiness Avant / Après

| Paramètre | Avant BR | Après BR |
|---|---|---|
| `GO_LIVE_READY` | `false` | `false` |
| `--assert-ready` exit code | `1` | `1` |
| `open_prs_blocking` | `0` | `0` |
| `open_prs_disposition_unknown` | `0` | `0` |
| `go_live_qualification_blockers` | `6` | **`5`** |
| `pii_undecided` | `149` | `149` |
| `release_promoted_refused_contents` | `26` | `26` |
| `current_switch` | `0` | `0` |
| `production_db_writes` | `0` | `0` |
| `production_deployments` | `0` | `0` |

---

## Vérifications d'Hygiène, Gouvernance et Tests

1. **Gardes de gouvernance** : 18 verrous vérifiés et intacts (`check-governance-locks.sh` OK, 16 tests de verrous OK).
2. **Unicité d'autorité (Règle R1)** : `NEXUS-AUTHORITY-UNIQUENESS-V1: PASS` (0 divergence, 0 lecteur production non autorisé).
3. **Hygiène du dépôt** : Racine suivie propre, 0 résidu ou fichier indésirable (`test-repository-hygiene.sh` PASS).
4. **Linters et formatage** :
   - `make -C services/rag-engine lint` : `All checks passed!`
   - `git diff --check` : 0 anomalie d'espace ou fin de ligne.
5. **Tests automatisés** :
   - `pytest -q scripts/qualification/tests` : 88 passed, 2 skipped.
   - `pytest -q scripts/tests/test_qualification_blockers_producer.py` : 77 passed.
   - `npm --prefix services/cockpit test -- --run` : 180 passed (21 suites).
   - `python3 scripts/qualification/verify_cockpit_e2e_retrieval.py --verify-only` : VERIFIED en mode hermétique.
   - `check_go_live_readiness.py --check-only` : `go_live_qualification_blockers=5`, `GO_LIVE_READY=false`.
   - `check_go_live_readiness.py --assert-ready` : exit code 1 (`ASSERT_READY=failed`).

---

## Conclusion et Suite

Le bloqueur `COCKPIT_E2E` est désormais clos sur une preuve réelle, scellée, reproductible et vérifiable hermétiquement.
Les 5 bloqueurs de qualification restants sont :
1. `C1` : Autorité de release et couverture promue (26 contenus refusés promus) ;
2. `STAGING_EXTERNE` : Qualification du staging externe ;
3. `CONCURRENCE` : Comportement sous concurrence ;
4. `SYNC_INCREMENTALE` : Synchronisation incrémentale ;
5. `MANIFESTE_PRODUCTION` : Manifeste production signé.
