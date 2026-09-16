# Rapport de Lot : Réconciliation des PRs Arbitrées et Qualification C5 (Autorité d'Accès)

## Phase

LOT_GO_LIVE_FINAL_BO_CLOSE_ARBITRATED_PRS_AND_QUALIFY_ACCESS_AUTHORITY_C5

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
> Ce lot BO reste un **lot technique intermédiaire**. Il n'autorise pas la production, ne modifie aucun current switch, ne prend aucune décision PII unilatérale et ne déploie aucun service en production.

---

## État main

| Élément | Résultat |
|---|---|
| Commit parent de base | `eb0fb6a64190a4b6d8de6dbee7e4a2d61450bfcb` (post PR #206) |
| Branche de lot | `go-live/close-arbitrated-prs-and-qualification-c5` |
| Pré-requis searchability | Fermé (55 251 vecteurs, 2 264/2 264 contenus servables, latence respectée) |
| Autorités et verrous | 18 verrous intacts (`check-governance-locks.sh` OK, autorité unique validée) |
| Statut initial readiness | `GO_LIVE_READY = false`, `open_prs_blocking = 2`, `go_live_qualification_blockers = 10` |

---

## Réconciliation des PRs Arbitrées (#138 et #140)

Conformément à l'arbitrage humain consigné dans `docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md` :

| Élément | PR #138 | PR #140 |
|---|---|---|
| Branche | `lot/release-reseal-scopes-v2-20260828` | `lot/cockpit-cutover-20260829` |
| Décision humaine | Rejetée (conflit de modèle de release avec ADR-0050) | Remplacée (contenu modulaire déjà intégré par lots isolés) |
| Clôture effective GitHub | `state = CLOSED`, `mergedAt = null` | `state = CLOSED`, `mergedAt = null` |
| Commentaire motivé | Enregistré avec lien vers la décision humaine | Enregistré avec lien vers la décision humaine |
| Nouvelle disposition | `CLOSE_REJECTED` | `CLOSE_SUPERSEDED` |
| Prise en compte dans le gate | `DISPOSITIONS_NON_BLOQUANTES` étendue pour inclure `CLOSE_REJECTED` | Incluse dans `DISPOSITIONS_NON_BLOQUANTES` |
| Résultat gate PRs | **`open_prs_blocking = 0`**, **`open_prs_disposition_unknown = 0`** (0 bloquante sur 10 suivies) |

---

## Qualification C5 : Autorité d'Accès et Portées

Le bloqueur C5 impose : *« l'autorité d'accès refuse une portée non autorisée, prouvé par épreuve »*.

Un harnais de qualification formel et adversarial a été développé (`scripts/qualification/verify_access_authority_scopes.py`) et validé par une suite de tests unitaires dédiés (`scripts/qualification/tests/test_verify_access_authority_scopes.py`).

### Les 15 Épreuves Adversariales C5

| Épreuve Adversariale | Description | Preuve |
|---|---|---|
| `UNKNOWN_SCOPE_ID_REFUSED` | Refus strict d'un identifiant de portée inconnu / non déclaré | `True` |
| `FORGED_SCOPE_ID_REFUSED` | Refus de tentative de falsification ou traversée de chemin (`../../malicious_scope`) | `True` |
| `SCOPE_DIGEST_CORRUPTION_REFUSED` | Refus d'une portée dont l'enveloppe ou le hash canonique a été altéré | `True` |
| `TARGET_LEVEL_DRIFT_REFUSED` | Refus de dérive de niveau cible élève (`terminale` vs `premiere`) | `True` |
| `CURRICULUM_LEVEL_DRIFT_REFUSED` | Refus de dérive de niveau de curriculum (`premiere_generale` vs profil élève) | `True` |
| `CROSS_SUBJECT_DRIFT_REFUSED` | Refus de croisement de matière / collection hors périmètre de l'artefact | `True` |
| `OMITTED_CURRICULUM_SCOPE_REFUSED` | Refus en l'absence de curriculum scope (interdiction formelle de fallback implicite) | `True` |
| `AUTHORIZATION_MAPPING_INCOMPLETE_REFUSED` | Refus en cas de gap ou d'extra de contenus dans le mapping d'autorisation | `True` |
| `AUTHORIZATION_SET_V2_FALSIFIED_OR_DIVERGENT_REFUSED` | Refus de falsification du digest de l'AuthorizationSetV2 | `True` |
| `CONTENT_OUTSIDE_AUTHORIZATION_REFUSED` | Refus d'accès à un contenu hors de la portée autorisée | `True` |
| `OVERLAP_OR_DUPLICATION_REFUSED` | Refus de duplication ou chevauchement non gouverné de portées | `True` |
| `DENORMALIZED_COLUMNS_CANNOT_WIDEN_AUTHORITY` | Preuve formelle que les colonnes dénormalisées `rag_chunks.visibility` ou `audience` ne peuvent jamais élargir un placement gouverné `restricted` | `True` |
| `INACTIVE_PLACEMENT_REFUSED` | Refus de placement inactif (`placement_status != 'active'`) | `True` |
| `STALE_OR_UNREVIEWED_PLACEMENT_REFUSED` | Refus de placement non revu ou non à jour (`currentness != 'current'` ou `review != 'reviewed'`) | `True` |
| `_EFFECTIVE_SCOPE_FILTER_SQL_ENFORCES_GOVERNED_PLACEMENT` | Preuve formelle que la clause SQL de filtrage impose impérativement la jointure LATERAL `rag_artifact_placements` | `True` |

### Scellement Cryptographique et Non-Fermetures

- Attestation générée : `docs/reports/evidence/access_authority_c5_refusal_proof.json` (`status = VERIFIED`, 15/15 épreuves réussies).
- Empreinte SHA-256 scellée : `docs/reports/evidence/access_authority_c5_refusal_proof.sha256` (`sha256sum -c` OK).
- Intégration dans `build_qualification_blockers.py` : `verifier_c5` vérifie le digest SHA-256 de l'attestation, valide les 15 preuves adversariales, et déclare explicitement :
  ```python
  does_not_close=["C1", "MANIFESTE_PRODUCTION"]
  ```

---

## Qualification (État des 13 Bloqueurs)

| Blocker | État | Preuve |
|---|---|---|
| **C1** (Autorité de release et couverture promue) | **OUVERT** | 26 contenus refusés promus dans la baseline release. |
| **C2** (Ingestion multilevel réelle bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C3** (Worker CLI multilevel bout en bout) | **OUVERT** | Session H2-C externe requise. |
| **C4** (Contrat de retrieval sur corpus servable) | **CLOS** | Acquis lot BM : 8 conditions searchability tenues, 2 264/2 264 contenus couverts, 55 251 vecteurs staging, latence respectée. |
| **C5** (Autorité d'accès et portées) | **CLOS** | **Dérivé à `closed: true` au lot BO** : Harnais adversarial de 15 épreuves de refus validé, attestation SHA-256 scellée, `does_not_close: [C1, MANIFESTE_PRODUCTION]`. |
| **C6** (Qualification CAS et couverture magasin) | **OUVERT** | Couverture du magasin réel requise. |
| **COCKPIT_E2E** (Cockpit bout en bout API retrieval)| **OUVERT** | Validation e2e cockpit requise. |
| **STAGING_EXTERNE** (Staging externe qualifié) | **OUVERT** | Staging externe non ingéré. |
| **CONCURRENCE** (Comportement sous concurrence) | **OUVERT** | Mesure sous charge concurrente requise. |
| **SYNC_INCREMENTALE** (Synchronisation incrémentale)| **OUVERT** | Preuve sans perte ni doublon requise. |
| **ROLLBACK** (Mécanisme de rollback éprouvé) | **CLOS** | Acquis lot BN : Rejeu réel du rehearsal Docker V2 avec rollback éprouvé, isolation prouvée, intégrité cryptographique SHA-256 recalculée (4/4), 0 conteneur résiduel. |
| **MANIFESTE_PRODUCTION** (Manifeste signé) | **OUVERT** | Non signé. |
| **NON_PDF_REACQUISITION** (Ressources servables) | **CLOS** | Acquis lot BJ : 37 ressources vérifiées dans le store durable canonique. |

**Total bloqueurs de qualification ouverts : 9** (était 10 au lot BN).

---

## Readiness

| Compteur | Valeur |
|---|---:|
| `GO_LIVE_READY` | `false` |
| `--assert-ready` exit code | `1` |
| `go_live_qualification_blockers` | `9` (était 10, C5 clos) |
| `open_prs_blocking` | `0` (était 2, #138 et #140 closes) |
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

| Suite | Commande | Résultat |
|---|---|---|
| Qualification C5 (nouveaux tests) | `pytest -q scripts/qualification/tests/test_verify_access_authority_scopes.py` | **4 passed** |
| Qualification globale | `pytest -q scripts/qualification/tests` | **80 passed, 2 skipped** |
| Scripts et garde-fous | `pytest -q scripts/tests/` | **420 passed, 7 skipped** |
| rag-pedago | `pytest -q services/rag-pedago/tests` | **3 490 passed, 12 skipped** |
| rag-engine | `pytest -q services/rag-engine/tests -m "not integration"` | **100% passed (0 failed)** |
| cockpit tests | `npm test -- --run` (vitest) | **21 files passed, 180 passed** |
| cockpit typecheck | `npm run typecheck` (tsc) | **Exit 0** |
| cockpit contrats | `npm run contracts:check` | **Exit 0** |
| Verrous de gouvernance | `bash scripts/check-governance-locks.sh` | **18/18 conformes** |
| Tests des verrous | `bash scripts/tests/test-governance-locks.sh` | **16/16 passed** |
| Unicité de l'autorité | `bash scripts/check-authority-uniqueness.sh` | **PASS** |
| Tests unicité autorité | `bash scripts/tests/test-authority-uniqueness.sh` | **PASS** |
| Hygiène du dépôt | `bash scripts/check-repository-hygiene.sh` | **PASS** |
| Tests hygiène dépôt | `bash scripts/tests/test-repository-hygiene.sh` | **PASS** |
| Topologie CI | `bash scripts/tests/test-ci-local-topology.sh` | **PASS** |
| Linting ruff | `ruff check scripts/ ...` | **All checks passed!** |
| Intégrité git | `git diff --check` | **Propre (exit 0)** |

---

## Décision

**`GO_LIVE_BO_PR_OPEN`**
