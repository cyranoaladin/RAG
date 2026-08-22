# Lot — Audit adversarial de la surface contractuelle multi-authority (2026-08-22)

## 1. Périmètre et méthode

PR#127 avait conclu que seul `ProductionReadinessManifestV1.authorization_digest`
bloquait le support multi-scope. Cet audit reprend la question de façon
adversariale et exhaustive, sans faire confiance à cette conclusion
préalable — chaque affirmation ci-dessous a été relue directement dans le
code sur `main` (`3548bf3`), jamais recopiée. Travail exclusivement dans
`~/Bureau/RAG-multi-auth` (`rag-pedago/multi-auth-contract-20260822`),
lecture seule, aucune donnée de la branche quarantinée
`rag-pedago/tier-a-currentness-byte-identity-20260820` réutilisée.

## 2. Matrice exhaustive

| FILE:LINE | FUNCTION/CLASS | CURRENT_CARDINALITY | TRUST_SEMANTICS | NEEDS_CHANGE_FOR_N_AUTH | WHY |
|---|---|---|---|---|---|
| `authority_artifacts.py:349-372` | `ScopeAuthorizationArtifactV2` | 1 autorisation par fichier, N fichiers coexistent déjà | attestation scope+contenu+droits+PII, auto-suffisante | **false** | Chaque autorisation est déjà un document indépendant et auto-suffisant. N fichiers côte à côte ne demandent aucun changement à cette classe. |
| `authority_artifacts.py:637-646` | `canonical_authorization_path` | 1 chemin par `authorization_id` | nommage | false | Dérivation pure par id ; N ids → N chemins, trivialement. |
| `authorization_revocations.py:34-88` | `parse_revoked_authorization_ids` | déjà un ensemble | registre de révocation | false | Déjà pluriel par construction. |
| `review_binding.py:129,423-454` | `ReviewBindingV1.authorization_id` + `verify_review_binding_receipt` | 1 binding ↔ 1 authorization_id | prouve qu'un humain distinct a revu CETTE autorisation à CE head | false (classe) / **true (consommation)** | La classe est correcte (1 binding par autorisation est la bonne granularité, ADR-0035). Mais chaque consommateur qui charge aujourd'hui exactement un binding doit apprendre à en vérifier N, un par autorisation. |
| `h2_coverage_evidence.py:178` | `H2CoverageEvidenceV1.authorization_id: StrictStr` | exactement 1 | nomme quelle autorisation a été vérifiée | **true** | Ne peut structurellement pas nommer plus d'un identifiant. |
| `h2_coverage_evidence.py:92` `input_file_digests["authority"]` | — | exactement 1 digest = sha256(octets d'un seul fichier) | lie le rapport aux octets exacts de l'unique autorité revue | **true** | Voir §3.1 — pas un simple ajout de valeur, un changement de sémantique de vérification. |
| `h2b_coverage_report.py:398,910,1331` | `_authority_structural_validation`, `_load_authority_evidence`, `generate_coverage_report(authority_path: Path)` | 1 fichier en entrée, 1 artefact en sortie | charge+valide UNE autorisation de bout en bout | **true (orchestration, pas contrat)** | Nécessite du nouveau code pour charger/valider/révoquer N artefacts et unir leurs `allowed_content_sha256` avant de calculer la couverture. |
| `h2b_coverage_report.py:1660-1661` | calcul de `input_files["authority"]` | 1 digest de 1 fichier | lie le rapport aux octets | **true** | Même cause racine que le champ contractuel ci-dessus. |
| `catalog_republish.py:130-186` | `republish_catalog` + `authorization_id != campaign.authorization_id` | 1 fichier d'autorité ↔ exactement le `authorization_id` unique de la campagne | lie une campagne promue à une autorisation revue précise | **true (orchestration)** | Égalité stricte 1:1 entre le document chargé et l'id de campagne. |
| `corpus_campaign.py:111-282` | `CorpusCampaignV1.scope`/`.authorization_id` | exactement 1 scope, exactement 1 autorisation, inlinés dans l'identité canonique | « identité approuvée d'un corpus » pour un seul scope gouverné | **true — décision d'architecture** | `canonical_document()` inline les 10 dimensions du scope comme champs scalaires — ce n'est pas un champ singulier accessoire, c'est le cœur de l'identité du modèle. |
| `corpus_campaign.py:332-372` | `discover_promoted_campaign` | exactement 1 campagne par promotion, refus dur sur 0 ou >1 | empêche une promotion multi-campagne ambiguë/accidentelle | **true (décision de conception nécessaire)** | Invariant délibéré et bien justifié ("laisser le hasard décider de ce qui part en production") — à préserver, pas à contourner. |
| `production_readiness.py:127-128` | `ProductionReadinessManifestV1.authorization_digest`, `.review_binding_digest` | exactement 1 chacun | lie une approbation de déploiement à exactement une autorisation revue + son reçu de revue | **true, les deux champs** | PR#127 n'avait signalé que le premier ; `review_binding_digest` a exactement le même problème et avait été manqué. |
| `sign_production_readiness_manifest_cli.py:643-738` | cross-checks `h2_evidence.authorization_id != authorization.authorization_id`, `input_file_digests["authority"] != authorization_digest` | 1 fichier, 2 vérifications supposant une identité singulière | prouve que H2, l'autorisation et le review binding s'accordent sur LA MÊME autorisation | **true (cascade)** | Chaque vérification doit devenir "cette autorisation est-elle un membre du set, et chaque membre du set a-t-il un review binding correspondant". |
| `.github/workflows/promote.yml` | entrée `campaign_id` | 1 campagne par run, pas de `matrix:` | déclenche une promotion | **dépend de l'option retenue** | Voir ADR-0044 §3 — résolu par l'Option B sans changer ce fichier. |
| `services/rag-engine/.../ingestion_control/scope_authority.py` (`_load_row` etc.) | table `scope_authorizations`, 1 ligne par `authorization_id`, vérifiée individuellement en direct contre GitHub | vérification par ligne, indépendante | **false** | Constat le plus positif de cet audit : ce composant est déjà N-capable, aucun changement requis. |
| `services/rag-engine/.../ingestion_control/scope_enforcement.py` | 1 autorisation par job, N jobs possibles | vérification par job | false | Même raisonnement — conçu par entité dès l'origine. |
| CLIs runtime (`authorize_scope_cli.py`, `issue_review_binding_cli.py`, `attest_publication_cli.py`, `create_job_cli.py`, `runner.py`) | opèrent sur 1 id nommé par invocation | enregistrement/révocation/attestation par entité | false | N autorisations = N invocations, pas un changement de code. |
| `revocation_registry.py:35,81-101` | `RevocationRegistry.revoked_authorization_ids: frozenset[str]` | déjà un ensemble | vérification O(1) | false | Déjà N-capable par construction. |
| `governed_publisher_v2.py:460-513,952-982` | `authorization_ids: Sequence[str]`, `tuple(sorted(set(...)))` | déjà une séquence de N ids | verrous advisory par publication | false | Précédent directement réutilisable pour la canonicalisation triée-dédupliquée de l'`AuthorizationSetV1`. |
| `h2c_placement_readiness.py:147-148,600,753-777` | `authorization_id`/`authorization_digest` | 1 par décision de placement | mécanisme LOT44f distinct, pas LOT41A | false (non applicable) | Vérifié et confirmé sans rapport avec ce sujet. |
| `pilot_validation.py:321,356,965-966` | `authorization_id`/`authorization_digest` | 1 par décision pilote | gouvernance pilote séparée | false (non applicable) | Faux positif de grep, sans rapport. |
| `h2b_coverage_report.py:2149-2197` (`report_to_h2_coverage_evidence`) | passthrough 1:1 vers `H2CoverageEvidenceV1.authorization_id` | miroir de la même hypothèse singulière | **true** | Cascade automatiquement de la V2 du contrat H2, aucune conception indépendante nécessaire. |

## 3. Les quatre adjudications

### 3.1 `H2CoverageEvidenceV1` — `H2_V1_CAN_STAY_UNCHANGED=false`

`input_file_digests["authority"]` est aujourd'hui littéralement
`sha256(octets_bruts_d'un_seul_fichier)`. Pour porter N autorisations, la
seule façon de faire tenir cela dans le même champ hex64 serait
`sha256(json_canonique_de_N_digests)` — ce qui n'est pas "le même champ
avec plus de données", c'est un digest de nature différente, avec une
sémantique de vérification différente (aujourd'hui un vérificateur
recalcule `sha256(fichier)` et compare directement ; demain il faudrait
disposer de la liste ordonnée complète des N digests pour recalculer
l'agrégat). Combiné à `authorization_id: StrictStr` (singulier,
contraint par motif), il n'existe aucun moyen de représenter "N
autorisations conjointement prouvées complètes" sans nouvelle version de
protocole. `StrictBaseModel` impose `extra="forbid"` (vérifié,
`document.py:10-11`) — aucune extension additive silencieuse n'est
possible non plus. **Nécessite `H2CoverageEvidenceV2`.**

### 3.2 `ProductionReadinessManifestV1` — les deux champs, pas un seul

N autorisations, si chacune exige sa propre revue humaine distincte selon
ADR-0035 (« Réutiliser une seule clé permettrait à quiconque peut émettre
un reçu d'émettre aussi une autorisation de déploiement »), impliquent
structurellement N review bindings, jamais un seul couvrant les N. Un
`review_binding_digest: StrictStr` unique ne peut pas nommer N reçus de
revue distincts, exactement comme `authorization_digest` ne peut pas
nommer N autorisations. **Nécessite `V2` pour les deux champs ensemble**
(remplacés par une référence unique à un artefact agrégat canonique,
plutôt que deux listes parallèles à garder synchronisées).

### 3.3 `CorpusCampaignV1` — le cœur de la décision d'architecture

`scope: ResourceScope` n'est pas un champ périphérique : `canonical_document()`
inline ses dix dimensions comme valeurs scalaires directement dans
l'identité de la campagne elle-même, et `discover_promoted_campaign`
refuse explicitement plus d'une campagne promue par événement (invariant
délibéré, bien justifié, à préserver). Deux options restaient ouvertes,
aucune n'étant gratuite — voir ADR-0044 §3 pour l'analyse complète et la
décision retenue (Option B). `ARCHITECTURE_AMBIGUOUS=true` avant cette
décision ; résolu dans l'ADR.

### 3.4 Tout le reste marqué `true`

Cascade des trois points ci-dessus (cross-checks du signer, vérification
1:1 de `catalog_republish`, entrée unique de `promote.yml`) — aucun de ces
points n'introduit un blocage indépendant nouveau au-delà de ce qui est
déjà listé ; ce sont des consommateurs à mettre à jour une fois les trois
décisions de cœur prises.

## 4. Contraintes pour la conception de l'`AuthorizationSetV1` (observations,
pas une conception — formalisées dans ADR-0044 §4)

- L'agrégat doit être **indépendant de l'ordre** (tri canonique par
  `authorization_id`) — `governed_publisher_v2.py:471` fait déjà exactement
  cela, précédent directement réutilisable.
- La **liaison au manifeste doit être vérifiée par autorisation, pas une
  fois pour l'ensemble** — sinon une autorisation bâtie contre un ancien
  manifeste pourrait se cacher dans un ensemble bâti contre le manifeste
  actuel.
- **Révocation et expiration doivent être vérifiées par autorisation,
  jamais une fois pour l'ensemble** — le patron par-ligne de
  `scope_authority.py` est le bon modèle à suivre.
- Le **review binding doit rester 1:1 avec chaque autorisation**, jamais
  agrégé en "une seule revue approuve l'ensemble" — cela romprait
  silencieusement la garantie non-transférable d'ADR-0035.

## 5. Ce qui n'a pas changé de conclusion depuis PR#127

Le constat central (`ScopeAuthorizationArtifactV2` n'a besoin d'aucun
changement, le champ `scope` n'est jamais croisé avec
`allowed_content_sha256` au gate H2) reste valide et est reconfirmé ici.
Ce qui a changé : la portée du blocage réel est plus large que
PR#127 ne l'avait caractérisé (`review_binding_digest` en plus de
`authorization_digest`, et surtout `CorpusCampaignV1` qui nécessite bien
un changement, contrairement à la conclusion initiale trop optimiste).

## 6. Booléens finaux

```
MULTIAUTH_CONTRACT_SURFACE_AUDIT_REQUIRED=true (satisfait par ce lot)
H2_V1_CAN_STAY_UNCHANGED=false
PRODUCTION_READINESS_BOTH_FIELDS_AFFECTED=true
CORPUS_CAMPAIGN_NEEDS_CHANGE=true
RUNTIME_SCOPE_AUTHORITY_NEEDS_CHANGE=false
GOVERNED_PUBLISHER_PATTERN_REUSABLE=true
ARCHITECTURE_DECISION=Option B (voir ADR-0044)
ADR0043_REUSED=false
```
