# Lot — Promotion des candidats vérifiés par preuve de currentness primaire

## 1. Constat traité

L'audit Tier A du 2026-08-15 (fork d'investigation en lecture seule) a
identifié un gap concret et immédiatement actionnable, distinct du travail
Tier A plus large (~2057 items encore non résolus) : **au moins 10 objets
sont déjà preuve-résolus** — currentness confirmée `actuel` par identité
d'octets contre la source primaire officielle
(`services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml`),
droits et PII déjà `CLEARED` — mais restent `REVIEW_REQUIRED` car
`corpus_zone_routing.yml` route tout chemin `01_EDUSCOL_OFFICIEL/` sans
sous-dossier de statut vers `REVIEW_REQUIRED`/`currentness=unclassified`
de façon purement statique (par chemin physique), jamais par contenu.

## 2. Investigation qui a précisé le périmètre réel

Une première hypothèse ("petit correctif YAML") s'est révélée incomplète à
l'investigation : `_apply_mandatory_ingest_gates` (compilateur) court-
circuite `if base_disposition is not INGEST: return base_disposition, "",
{}` — ces objets ont donc `gate_statuses={}` : le compilateur n'a **jamais**
évalué droits/PII pour eux. Les promouvoir exige de basculer
`base_disposition` lui-même (`REVIEW_REQUIRED`→`INGEST`), pas seulement
`currentness`/`disposition` — un champ jusqu'ici traité comme la vérité
structurelle intangible du compilateur dans tout le reste de la chaîne H2.
Ce périmètre révisé a été explicitement confirmé avant codage.

## 3. Ce qui a été construit

Deux fonctions nouvelles dans
`services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py`, symétriques
à `_promote_authority_cleared_candidates` (lot précédent) :

- **`_load_currentness_verification_evidence`** : charge
  `multilevel_currentness_evidence.yml`, lié au manifeste scellé exact.
  Ne fait **jamais** confiance au drapeau `byte_identity` déclaratif seul
  (le fichier documente lui-même que la plupart de ses entrées proviennent
  d'un audit *réutilisé* — `decision_basis:
  READ_ONLY_OFFICIAL_NETWORK_AUDIT_REUSED_FAIL_CLOSED`) : la preuve
  retenue est la ré-égalité explicite `current_download_sha256 ==
  content_sha256` pour chaque entrée `decision=="CURRENT"`.
- **`_promote_currentness_verified_candidates`** : promeut un candidat
  seulement si `base_disposition=="REVIEW_REQUIRED"`, `currentness` est
  exactement `"unclassified"` ou `"a_verifier"` (jamais un motif déjà
  décidé comme `"transition"`/`"conflict"`), le `content_sha256` est
  couvert par l'évidence, ET droits+PII — **réévalués pour de vrai** via
  `_apply_mandatory_ingest_gates` (réutilisée du compilateur, jamais
  dupliquée) — passent tous les deux indépendamment. L'autorité reste
  délibérément non franchie : un item promu par currentness redevient un
  candidat INGEST authentique, qui doit encore passer par
  `_promote_authority_cleared_candidates` comme n'importe quel autre.

Réutilise également `_derive_rights_clearances`/`_derive_pii_clearances`
(déjà existantes dans `corpus_catalog_compiler.py`, jamais dupliquées) pour
réévaluer droits/PII sur le périmètre réel.

Câblé dans les deux producteurs déjà existants, jamais un troisième chemin
parallèle :
- `generate_coverage_report` (nouveau paramètre optionnel
  `currentness_verification_path`, nouveau flag CLI
  `--currentness-verification`) — le rapport de couverture H2 reflète
  désormais fidèlement l'état promu.
- `catalog_republish.py::republish_catalog` (nouveaux paramètres optionnels
  `currentness_verification_path`/`rights_path`/`pii_path`/`routing_path`,
  couplés : fournir le premier sans les trois autres est un refus explicite)
  — la matérialisation gouvernée reflète la même promotion.

## 4. Ce qui n'a délibérément pas changé

- `corpus_catalog_compiler.py` : jamais touché.
- `packages/contracts` : jamais touché.
- Aucun contenu réel n'est ajouté au registre de currentness — ce lot
  consomme l'évidence déjà commitée, n'en produit aucune nouvelle.
- Le travail Tier A plus large (~2057 items encore non résolus, dont 805
  `a_verifier` sans aucune couverture de registre) reste hors périmètre —
  documenté séparément dans l'audit du 2026-08-15.

## 5. Tests

- `services/rag-pedago/tests/test_currentness_verification_promotion.py` —
  19 tests : 7 sur le chargeur d'évidence (fail-closed sur chaque
  condition), 10 sur la fonction de promotion (candidats valides, chaque
  garde testée isolément), 2 d'intégration réelle contre
  `generate_coverage_report` (avec et sans le chemin de vérification).
- `services/rag-pedago/tests/test_catalog_republish.py` — 1 nouveau test
  (refus si `currentness_verification_path` fourni sans
  `rights_path`/`pii_path`/`routing_path`).
- Mutation-testing manuel sur les branches de sécurité de la fonction de
  promotion (garde droits, garde PII, garde catégorie de currentness,
  garde `base_disposition`, isolée via un test dédié après une première
  passe qui a révélé une garde redondante — corrigé) et sur le câblage
  réel dans `generate_coverage_report` (condition `if
  currentness_verification_path is not None` désactivée → le test
  d'intégration échoue pour la bonne raison) : chaque garde désactivée
  fait échouer son test dédié, restaurée, suite verte à nouveau.
- Suite complète : `test_currentness_verification_promotion.py` +
  `test_catalog_republish.py` + `test_h2b_coverage_report.py` +
  `test_h2f_golden_final_gate.py` + `test_h2_evidence_e2e_rehearsal.py` +
  `test_governance_cli_and_workflow.py` = 192/192 verts.
- `ruff check` et `mypy` : propres sur les fichiers de production touchés.

## 6. Booléens finaux

```
CURRENTNESS_VERIFIED_PROMOTION_STEP_EXISTS=true
CURRENTNESS_VERIFIED_PROMOTION_TESTED=true
CURRENTNESS_VERIFIED_PROMOTION_MUTATION_TESTED=true
WIRED_INTO_H2_COVERAGE_REPORT=true
WIRED_INTO_GOVERNED_CATALOG_REPUBLISH=true
CORPUS_CATALOG_COMPILER_UNTOUCHED=true
CONTRACTS_PACKAGE_UNTOUCHED=true
TIER_A_FULLY_RESOLVED=false   # hors périmètre -- seul le sous-ensemble déjà preuve-résolu est traité ici
NEW_CURRENTNESS_EVIDENCE_PRODUCED=false   # consomme l'existant, n'en produit aucune
```

## 7. Effet attendu sur l'éligibilité (à confirmer en conditions réelles)

Ce lot ne modifie aucune donnée du corpus — l'effet réel sur
`RELEASE_ELIGIBLE_ARTIFACTS` (actuellement 63) ne se manifestera que
lorsque `h2b_coverage_report.py`/`catalog_republish.py` seront exécutés
pour de vrai avec `--currentness-verification` pointant sur
`multilevel_currentness_evidence.yml`, contre le vrai catalogue candidat.
L'audit Tier A a identifié 10 candidats potentiellement concernés
(`10_ACTUEL_CONFIRME`-equivalents hors sous-dossier de statut) ; le nombre
exact promu dépendra de la réévaluation réelle des droits/PII pour chacun,
jamais supposé ici.
