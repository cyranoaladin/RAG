# Rapport de Lot : Fermeture des PRs Bloquantes et Qualification du Rollback Production

## Phase

LOT_GO_LIVE_FINAL_BN_CLOSE_BLOCKING_PRS_AND_PRODUCTION_QUALIFICATION_PATH

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
> Ce lot BN reste un **lot technique intermédiaire**. Il n'autorise pas la production, ne modifie aucun current switch, ne prend aucune décision PII et ne déploie aucun service en production.

---

## État main

| Élément | Résultat |
|---|---|
| Commit parent de base | `679d9d37c7b3c70a6544d81bbf4703b1b6092118` (post PR #205) |
| Branche de lot | `go-live/close-blocking-prs-and-production-qualification` |
| Pré-requis searchability | Fermé (55 251 vecteurs, 2 264/2 264 contenus servables, latence respectée) |
| Autorités et verrous | 18 verrous intacts (`check-governance-locks.sh` OK, autorité unique validée) |
| Statut initial readiness | `GO_LIVE_READY = false`, `open_prs_blocking = 4`, `go_live_qualification_blockers = 11` |

---

## PR #132 / rollback

| Élément | Résultat |
|---|---|
| Titre de la PR #132 | `rag-engine: rehearse atomic Docker V2 deployment` |
| Head SHA PR #132 | `c98ad5e62b7e050feed0961cc6bef8651a7f08a9` |
| Fichiers importés sur main | `atomic_docker_v2_rehearsal.py`, `atomic_docker_v2_rehearsal_fixture.py`, `test_atomic_docker_v2_rehearsal.py`, `test-go-live-evidence-refresh.py`, artefacts de preuve (`.json`, `.sha256`, `.transcript.txt`, `.md`) |
| Preuve 1 : Rejeu réel Docker V2 sur main | **REJOUÉ ET VALIDÉ** via daemon Docker local (`NEXUS_RUN_DOCKER_V2_REHEARSAL=1`) : `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`, `ROLLBACK_REHEARSAL_PASS=true`, 4 scénarios de refus stricts sans mutation (`mutation_boundary_calls=0`), `PROJECT_CONTAINERS_REMAINING=0`, résidu `{containers: [], networks: [], volumes: []}` |
| Preuve 2 : Conformité cryptographique digest par digest | **INTÈGRE ET CONFORME** : `sha256sum -c docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.sha256` : 4/4 fichiers vérifiés avec succès |
| Non-fermetures explicites de ROLLBACK | Ne ferme pas C1 (Autorité de release et couverture promue : 26 contenus refusés promus), ne ferme pas MANIFESTE_PRODUCTION |
| Nouvelle disposition PR #132 | `CLOSE_SUPERSEDED` (mécanisme et preuves entièrement intégrés sur `main`, ne bloque plus) |

---

## PR #151 / url_source_registry

| Élément | Résultat |
|---|---|
| Titre de la PR #151 | `rag-pedago: registre des URL sources et disposition de fraîcheur par objet gouverné` |
| Head SHA PR #151 | `784f47a08df21c7cafb76620aed52d04d356dc56` |
| Composants autonomes extraits | `url_source_registry.py`, `build_url_source_registry.py`, `url_source_registry_audit.py`, `url_source_registry.json`, `test_url_source_registry.py`, `test_build_url_source_registry.py`, rapport de lot |
| Préservation de l'autorité currentness | **ADR-0055 STRICTEMENT PRÉSERVÉ** : aucun écrasement de `currentness_disposition.py` officiel, aucune seconde autorité créée |
| Audit du registre extrait | `VERDICT : REGISTRE DES URL SOURCES COHÉRENT, AUCUNE URL NON COMPTÉE` (`URL_UNACCOUNTED = 0`) |
| Tests associés | 38/38 tests passés (`test_url_source_registry.py`, `test_build_url_source_registry.py`) |
| Nouvelle disposition PR #151 | `CLOSE_SUPERSEDED` (composants utiles extraits et intégrés sans conflit, ne bloque plus) |

---

## PR #138 / #140

| Élément | Résultat |
|---|---|
| PR #138 (`lot/release-reseal-scopes-v2-20260828`) | Maintien en `HUMAN_DECISION_REQUIRED` — collision avec ADR-0050 et l'architecture actuelle scellée |
| PR #140 (`lot/cockpit-cutover-20260829`) | Maintien en `HUMAN_DECISION_REQUIRED` — trunk d'intégration géant de 343 fichiers dont les modules ont déjà été intégrés de façon modulaire et propre |
| Dossier d'arbitrage produit | `docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md` |
| Commandes recommandées pour l'arbitre humain | `gh pr close 138 --comment "..."` et `gh pr close 140 --comment "..."` formellement préparées et documentées |
| Impact sur le comptage | Non fermées unilatéralement, restent comptées dans `open_prs_blocking = 2` jusqu'à clôture effective |

---

## Qualification

| Blocker | État | Preuve |
|---|---|---|
| **C1** (Autorité de release et couverture promue) | **OUVERT** | 26 contenus refusés promus dans la baseline release. |
| **C2** (Ingestion multilevel réelle bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C3** (Worker CLI multilevel bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C4** (Contrat de retrieval sur corpus servable) | **CLOS** | Acquis du lot BM / PR #204 : 8 conditions searchability tenues, 2 264/2 264 contenus indexés, 55 251 vecteurs staging, budget latence validé. |
| **C5** (Autorité d'accès et portées) | **OUVERT** | Vérification formelle d'autorité d'accès requise. |
| **C6** (Qualification CAS et couverture magasin) | **OUVERT** | Couverture du magasin réel requise. |
| **COCKPIT_E2E** (Cockpit bout en bout API retrieval)| **OUVERT** | Validation e2e cockpit requise. |
| **STAGING_EXTERNE** (Staging externe qualifié) | **OUVERT** | Staging externe non ingéré. |
| **CONCURRENCE** (Comportement sous concurrence) | **OUVERT** | Mesure sous charge concurrente requise. |
| **SYNC_INCREMENTALE** (Synchronisation incrémentale)| **OUVERT** | Preuve sans perte ni doublon requise. |
| **ROLLBACK** (Mécanisme de rollback éprouvé) | **CLOS** | **Dérivé à `closed: true` au lot BN** : Rejeu réel du rehearsal Docker V2 avec scénario de rollback éprouvé (`ROLLBACK_REHEARSAL_PASS=true`, `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`), isolation prouvée, intégrité cryptographique SHA-256 recalculée (4/4), 0 conteneur résiduel. |
| **MANIFESTE_PRODUCTION** (Manifeste signé) | **OUVERT** | Non signé. |
| **NON_PDF_REACQUISITION** (Ressources servables) | **CLOS** | Acquis du lot BJ : 37 ressources vérifiées dans le store durable canonique. |

---

## Readiness

| Compteur | Valeur |
|---|---:|
| `GO_LIVE_READY` | `false` |
| `--assert-ready` exit code | `1` |
| `go_live_qualification_blockers` | `10` (était 11, ROLLBACK clos) |
| `open_prs_blocking` | `2` (était 4, #132 et #151 résolues) |
| `open_prs_disposition_unknown` | `0` |
| `rag_searchability_blocker` | `false` |
| `rag_searchability_conditions_not_met` | `[]` |
| `staging_vectors_present` | `55 251` |
| `pii_undecided` | `149` (intact) |
| `release_promoted_refused_contents` | `26` (intact) |
| `currentness_policy_applied` | `true` |
| `non_pdf_servable_reacquired` | `37` |
| `obsolete_worktrees_remaining` | `0` |
| `root_owned_worktree_residues` | `0` |

---

## Safety

| Élément | Résultat |
|---|---|
| Accès SSH production | Aucun |
| Ingestion / Mutation base production | Aucune |
| Current switch | Aucun (`current_switch = 0`) |
| Release v3 | Aucune |
| Décision PII | Aucune (`pii_undecided = 149` strictement préservé) |
| Révocation Google OAuth | Aucune |
| Reconfiguration rclone | Aucune |
| Tokens / Secrets exposés | Aucun |
| Verrous de gouvernance (`scripts/check-governance-locks.sh`)| 18/18 conformes à la baseline |
| Unicité de l'autorité (`scripts/check-authority-uniqueness.sh`)| `PASS` (0 seconde autorité, 0 lecteur non épinglé) |
| Hygiène du dépôt (`scripts/tests/test-repository-hygiene.sh`)| `PASS` |

---

## Tests

| Commande | Résultat |
|---|---|
| `pytest -q scripts/tests/` | **413 passed, 7 skipped** |
| `pytest -q scripts/qualification/tests` | **76 passed, 2 skipped** |
| `pytest -q services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py` | **26 passed, 1 skipped** (unitaire) ; **1 passed** (e2e réel Docker) |
| `pytest -q services/rag-pedago/tests/test_url_source_registry.py ...` | **114 passed** (composants extraits et gouvernance currentness) |
| `bash scripts/check-governance-locks.sh` | **18/18 conformes** |
| `bash scripts/tests/test-governance-locks.sh` | **16/16 passed** |
| `bash scripts/check-authority-uniqueness.sh` | **PASS** |
| `bash scripts/tests/test-authority-uniqueness.sh` | **PASS** |
| `bash scripts/tests/test-repository-hygiene.sh` | **PASS** |
| `ruff check scripts/ services/rag-engine services/rag-pedago` | **All checks passed** |
| `git diff --check` | **Propre (exit 0, aucun whitespace orphelin)** |

---

## PR

| Élément | Résultat |
|---|---|
| Branche | `go-live/close-blocking-prs-and-production-qualification` |
| Base | `679d9d37c7b3c70a6544d81bbf4703b1b6092118` (`main`) |
| Titre proposé | `feat(go-live): integrate docker v2 rollback rehearsal, extract url registry, reduce blocking PRs to 2` |

---

## Décision

**`GO_LIVE_BN_PR_OPEN`**
