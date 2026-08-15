# ADR-0042 — Preuve H2 machine-lisible et registre de révocation partagés

- **Statut** : **Accepté** (voir « Preuve d'acceptation » ci-dessous).
- **Date** : 2026-08-13
- **Décideur** : `@abenrhouma`.
- **Périmètre** : deux structures de représentation partagées dans
  `packages/contracts`, consommées par `rag-pedago` (productrice) et
  `rag-engine` (vérificatrice hors ligne). Ce document n'autorise aucun
  contenu, ne signe aucun manifeste, et ne modifie aucun calcul métier
  existant.
- **S'appuie sur** : ADR-0001, ADR-0025, ADR-0035, ADR-0036.
- **Ne supersede rien.**

## Preuve d'acceptation

Cette section documente précisément ce qui a été approuvé, par qui, vérifié
en direct plutôt que déduit d'un texte historique — même chaîne de preuve
que celle établie pour l'acceptation d'ADR-0035 (PR #101) et ADR-0036
(PR #103) :

1. **`5e3095376730595bc339fada4033f4537f519b76`** est le HEAD exact de PR
   #104 tel qu'il existait immédiatement avant son merge — c'est **cet état
   précis** qui a été inspecté et approuvé humainement (après cinq rounds de
   revue Codex, chacun vérifié contre le producteur réel avant correction :
   voir `docs/reports/lot_h2_coverage_evidence_contract.md`).
2. La review GitHub `APPROVED` porte explicitement sur cet état :
   **Reviewer** `@abenrhouma`, review `id=4936762551`, `state=APPROVED`,
   `commit_id=5e3095376730595bc339fada4033f4537f519b76`, soumise le
   `2026-08-14T11:37:33Z`, corps de review portant exactement le challenge
   `NEXUS-TRUSTED-REVIEW-V1:
   c02da391865b2dff0e514e7fa274fbdae6e1ef65c185c73f31e70441b1590414` — même
   discipline de liaison cryptographique qu'ADR-0025/ADR-0035, revérifiée
   par le run GitHub Actions réel `31797022943` (`conclusion: success`, le
   workflow `trusted-human-review.yml` republiant `"approved": true,
   "reason": "approved"` pour ce `review_id` exact).
3. La liste complète des reviews de PR #104 (6 au total, un seul appel API
   non paginé suffisant à l'établir puisqu'aucun en-tête `Link` n'est
   renvoyé) ne contient aucune review `DISMISSED` ni `CHANGES_REQUESTED` —
   les quatre autres reviews sont les commentaires `chatgpt-codex-connector
   [bot]` des rounds de correction, tous `state=COMMENTED`, jamais des
   décisions humaines. Une première review `@abenrhouma` `APPROVED`
   (`id=4933937961`, `2026-08-14T04:17:37Z`) existe sur le même commit mais
   sans le challenge dans son corps (`"ok"`) — insuffisante pour le
   protocole `/nexus-trusted-review`, elle a été explicitement remplacée
   par la review `id=4936762551` ci-dessus avant toute décision d'acceptation.
4. GitHub a ensuite fusionné PR #104 (`merged_at`: `2026-08-14T11:39:34Z`),
   produisant le commit `c2cf3bd86199452483adcada29ed9eb11649732b` sur
   `main` — moins de deux minutes après l'approbation valide, sans review
   intermédiaire.
5. **Cette acceptation est architecturale et documentaire uniquement.**
   Elle ne constitue ni un déploiement, ni une autorisation de contenu, ni
   une clé provisionnée. L'intégration de ces deux contrats dans le signer
   `sign_production_readiness_manifest_cli.py` (PR #100) reste un lot
   séparé, non dispensé par cette acceptation.

## Contexte

`services/rag-engine/scripts/sign_production_readiness_manifest_cli.py`
(PR #100) hache trois preuves de gouvernance H2-B (`catalog`,
`sealed_manifest`, `h2b_report`) sans jamais les revérifier
sémantiquement : un digest prouve qu'un fichier n'a pas changé depuis sa
lecture, pas qu'il décrit une campagne de gouvernance réellement passante.

Deux causes distinctes, auditées séparément :

1. **`h2b_coverage_report.CoverageReport`** — la structure interne qui
   porte réellement `h2_coverage_gate_pass` et l'ensemble des sous-checks
   (`zero_gap`, `zero_overlap`, `mandatory_gate_blockers`, etc.) — n'est
   sérialisée qu'en Markdown (`--output data/reports/h2b_coverage_
   report.md`). Aucun artefact machine-lisible canonique n'existe.
   `catalog` (`corpus_catalog_compiler`) et `sealed_manifest`
   (`sealed_corpus.SealedManifest`) ont, eux, déjà des producteurs/
   parseurs canoniques en JSON — ce n'est donc pas leur défaut qui motive
   ce document.
2. **Le registre de révocation gouverné**
   (`governance/trust-anchors/authorization-revocations-v1.json`) a
   aujourd'hui **deux parseurs indépendants** : le parseur strict complet
   de `rag_pedago.imports.h2b_coverage_report._parse_revocation_registry`
   (clés inconnues refusées, `protocol_version` exigé, IDs non-vides,
   doublons refusés), et un parseur volontairement minimal introduit dans
   PR #100 (`sign_production_readiness_manifest_cli._revoked_
   authorization_ids`), documenté dans son propre rapport de lot comme
   insuffisant — parce que `rag-engine` ne peut pas importer
   `rag_pedago` (ADR-0001) et qu'aucune troisième option n'existait alors.

ADR-0001 interdit à `rag-engine` d'importer du code métier `rag-pedago`.
La solution n'est donc pas de partager du code métier, mais d'introduire,
dans `packages/contracts` — déjà la frontière partagée entre les deux
services pour `production_readiness.py` et `review_binding.py` — deux
**représentations strictes**, sans aucun calcul pédagogique.

## Décision

### 1. `NEXUS-H2-COVERAGE-EVIDENCE-V1` (`nexus_contracts.h2_coverage_evidence`)

Projection stricte, canonique (clés triées, indentation 2, UTF-8, saut de
ligne final — même discipline que `production_readiness.py`/
`review_binding.py`), du sous-ensemble de `CoverageReport` nécessaire à un
vérificateur hors ligne : identité (`protocol_version`, `environment`,
`report_id`, `generated_at`, `git_commit`, `producer_version`), identité
du manifeste scellé (`manifest_sha256`) et des preuves d'entrée
(`input_file_digests` — catalogue, routage, droits, PII), verdicts de
couverture (`corpus_match`, `sum_equals_total`, `zero_overlap`,
`zero_gap`, `coverage_complete`), verdicts de gate (`rights_gate_status`,
`pii_gate_status`, `golden_validation_pass`, `h2_coverage_gate_pass`), et
liaison d'autorité (`authority_review_binding_verified`,
`authority_revocations_checked`).

`rag_pedago.imports.h2b_coverage_report` produit ce document en plus (pas
à la place) du rapport Markdown existant — projection pure depuis
`CoverageReport`, déjà calculé ; **aucun nouveau calcul**, aucune
duplication de `_derive_rights_clearances`/`_derive_pii_clearances`
(celles-ci restent, avec toute la sémantique de gouvernance H2-B, dans
`rag-pedago`).

`rag-engine` (intégration différée dans un commit séparé sur PR #100,
après ce lot) parse ce document avec le contrat partagé, vérifie sa forme
canonique octet à octet, et exige `h2_coverage_gate_pass=true` avant de
signer — jamais un scrape de texte Markdown.

### 2. `NEXUS-AUTHORIZATION-REVOCATIONS-V1` partagé (`nexus_contracts.authorization_revocations`)

Le parseur strict complet (précédemment dupliqué, en version affaiblie,
dans PR #100) migre dans `packages/contracts`. `rag_pedago.imports.
h2b_coverage_report._parse_revocation_registry` et
`sign_production_readiness_manifest_cli._revoked_authorization_ids`
(intégration différée, même commit que ci-dessus) l'appellent tous les
deux — un seul parseur, jamais deux qui pourraient diverger.

### 3. Aucune fuite de métier vers `packages/contracts`

Ni `_derive_rights_clearances`, ni `_derive_pii_clearances`, ni
`verify_catalog_evidence_bindings`, ni aucune logique de calcul de
disposition ne quitte `rag-pedago`. `packages/contracts` ne gagne que de
la représentation, de la canonicalisation, et de la validation
structurelle — jamais un calcul pédagogique.

### 4. SemVer

`nexus-contracts` passe de `0.11.0` à `0.12.0` — ajout additif de deux
modules, aucun changement de forme sur les contrats existants
(`production_readiness`, `review_binding`, `authority_artifacts`).

## Conséquences

**Positives.** Le signer peut vérifier sémantiquement, pas seulement
hacher, l'évidence H2 avant de signer. Un seul parseur de révocation,
partagé, au lieu de deux qui divergeraient silencieusement.

**Négatives, assumées.** Un service de plus (`packages/contracts`)
maintenu par deux équipes de fait. La sérialisation canonique de
`CoverageReport` doit être tenue à jour si de nouveaux champs deviennent
pertinents pour le signer — versionnée (`NEXUS-H2-COVERAGE-EVIDENCE-V2`
si besoin), jamais réécrite sous le même protocole.

**Non traité ici.** L'intégration du signer (`sign_production_readiness_
manifest_cli.py`) à ces deux contrats — commit séparé, après acceptation
de ce document et merge de son lot d'implémentation.

## Alternatives écartées

- **Scraper `H2_COVERAGE_GATE_PASS=true` depuis le Markdown** — fragile,
  explicitement rejeté par instruction humaine antérieure à ce document.
- **Dupliquer le parseur de révocation dans `rag-engine` (déjà fait une
  fois dans PR #100)** — c'est exactement le défaut que ce document
  corrige ; deux parseurs indépendants finissent par diverger.
- **Déplacer `_derive_rights_clearances`/`_derive_pii_clearances` dans
  `packages/contracts`** — violerait la séparation de plans (ADR-0001) en
  faisant de `packages/contracts` un lieu de calcul pédagogique, pas
  seulement de représentation.
