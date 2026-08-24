# Audit adversarial de la surface multi-autorisation — 2026-08-23

## Verdict

```
BASE_SHA=3548bf300c99685ff6ede0dce2e5bfe8c044d213
MULTIAUTH_CONTRACT_SURFACE_AUDIT_REQUIRED=true
CONTRACT_CHANGE_REQUIRED=true
V1_MUTATION_ALLOWED=false
SELECTED_COMPOSITION=AuthorizationSetV1
SELECTED_CAMPAIGN=CorpusCampaignV2
SELECTED_H2=H2CoverageEvidenceV2+H2EvidenceBundleV2
SELECTED_READINESS=ProductionReadinessManifestV2
CONTRACT_VERSION=0.13.0
```

L'affirmation historique « seul
`ProductionReadinessManifestV1.authorization_digest` bloque » est réfutée.
La cardinalité singulière est aussi portée par H2 V1, sa map de digests, la
campagne, le rapport/producteur, le republish, le workflow, le bundle H2 et
le signer. Les V1 conservent leur signification ; les lignes marquées
`true` exigent une nouvelle surface V2, pas une mutation de champ V1.

## Méthode

Recherche intégrale au SHA de base avec les termes demandés :
`authorization_id`, `authorization_digest`, `review_binding_digest`,
`authority_path`, `authority_file`, `review_binding_path`,
`input_file_digests["authority"]`, `--authorization`,
`--authorization-file`, `--authority`, `--authority-review-binding`, plus
les équivalents `scope_authorization_id`, registres de révocation,
readiness et publication. Résultat brut : **1 106 occurrences dans 123
fichiers**, incluant production, tests, fixtures, migrations, ADR et
rapports. Les documents/tests historiques ont été contrôlés pour détecter
les hypothèses, mais la matrice ci-dessous consolide chaque surface
exécutable ou contractuelle une seule fois.

## Matrice exhaustive des surfaces de trust

| FILE | FUNCTION/CLASS | CURRENT_CARDINALITY | TRUST_SEMANTICS | NEEDS_CHANGE_FOR_N_AUTH | WHY |
|---|---|---:|---|---|---|
| `packages/contracts/src/nexus_contracts/authority_artifacts.py` | `ScopeAuthorizationArtifactV2` | 1 scope, N contenus | Décision élémentaire exacte, fenêtre, profil, droits et PII | false | L'atomicité par scope est souhaitée ; N objets sont composés au-dessus. |
| `packages/contracts/src/nexus_contracts/authority_artifacts.py` | `canonical_authorization_path`, parse/digest V2 | 1 ID/fichier | Dérive le chemin et l'identité canonique d'une décision | false | Le set dérive N chemins en réutilisant cette primitive individuelle. |
| `packages/contracts/src/nexus_contracts/review_binding.py` | `ScopeAuthorizationReviewBindingV1` | 1 autorisation | Lie un digest/ID/PR/reviewer/challenge avec expiration | false | Chaque décision garde sa preuve de revue indépendante. |
| `packages/contracts/src/nexus_contracts/review_binding.py` | `verify_review_binding` | 1 binding + 1 auth | Signature Ed25519, ancre, chemin, digest, fraîcheur | false | Appelé N fois par le vérificateur du set. |
| `packages/contracts/src/nexus_contracts/authorization_revocations.py` | `parse_revoked_authorization_ids` | N IDs | Parseur canonique partagé du registre gouverné V1 | false | Il sait déjà représenter N révocations ; il doit devenir l'unique parseur V2 runtime. |
| `packages/contracts/src/nexus_contracts/h2_coverage_evidence.py` | `H2CoverageEvidenceV1.authorization_id` | 1 | Nomme l'unique autorisation que le rapport affirme avoir vérifiée | true | N identités ne peuvent être prouvées sans V2 lié au digest du set. |
| `packages/contracts/src/nexus_contracts/h2_coverage_evidence.py` | `H2CoverageEvidenceV1.input_file_digests["authority"]` | 1 digest | Engage un seul fichier d'autorité | true | Remplacé en V2 par les digests `authorization_set`, registre et ancre. |
| `packages/contracts/src/nexus_contracts/production_readiness.py` | `ProductionReadinessManifestV1.authorization_digest` | 1 | Lie la release signée à une autorisation | true | Nouveau `ProductionReadinessManifestV2.authorization_set_digest`. |
| `packages/contracts/src/nexus_contracts/production_readiness.py` | `ProductionReadinessManifestV1.review_binding_digest` | 1 | Lie la release signée à un binding | true | Le digest canonique du set engage les N bindings sans liste parallèle. |
| `packages/contracts/src/nexus_contracts/production_readiness.py` | sign/parse/verify V1 | 1 | Enveloppe canonique et signature offline d'une readiness V1 | true | Reste inchangé pour legacy ; sign/parse/verify V2 explicites sont requis. |
| `services/rag-pedago/rag_pedago/governance/corpus_campaign.py` | `CorpusCampaignV1.scope`, `authorization_id` | 1 | Identité approuvée d'une campagne et d'un scope | true | Une campagne globale V2 doit engager le set et ses agrégats exacts. |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `CoverageReport` | 1 binding implicite | Porte count/set requis mais seulement des booléens singuliers d'autorité | true | Ajouter une branche V2 typée : set digest/count, covered, gap/overlap/extra et dates N bindings. |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `generate_coverage_report(authority_path, ...binding_path)` | 1 fichier | Vérifie structure, sémantique, binding et révocation d'une autorisation | true | Doit résoudre le set et vérifier exactement N membres avant calcul global. |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `_authority_structural_validation` / `_authority_semantic_validation` | 1 | Transforme une allowlist singulière en couverture | true | Le V2 exige union exacte, disjonction et preuve contenu→scope. |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `authority_required_candidate_facts` / `authority_required_set_digest` | set global | Calcule le vrai périmètre après currentness | false | Primitive correcte à réutiliser ; ne dépend pas de l'autorité fournie. |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `report_to_h2_coverage_evidence` | 1 ID + 1 digest | Projette le rapport en H2CoverageEvidenceV1 | true | Garder V1 et ajouter une projection V2 distincte. |
| `services/rag-pedago/rag_pedago/governance/catalog_republish.py` | `republish_catalog` | 1 auth + 1 binding | Autorise la promotion du catalogue entier | true | V2 vérifie le set une fois et matérialise le mapping unique par contenu. |
| `services/rag-pedago/rag_pedago/governance/catalog_republish.py` | `_load_authority_evidence` | 1 | Charge binding/ancre/révocations gouvernés | true | Le chemin V2 résout N couples par chemins dérivés et le registre partagé. |
| `services/rag-pedago/rag_pedago/governance/cli.py` | commandes `h2-coverage`, `catalog-republish` | `--authority` et `--authority-review-binding` uniques | Entrées opérateur vers les gates | true | Ajouter `--authorization-set`/racine gouvernée sur les commandes V2. |
| `services/rag-pedago/rag_pedago/governance/h2_evidence.py` | `H2EvidenceBundle` / build/load | 1 `authorization_sha256` + 1 receipt | Lie campagne, rapport H2, exact-head/review et promotion | true | Nouveau bundle V2 lié au set et aux dates minimales des N bindings. |
| `services/rag-pedago/rag_pedago/governance/h2_evidence.py` | `verify_gate_outcome`, `verify_receipt_freshness` | 1 | Vérifie verdict et fraîcheur d'une revue | true | V2 doit empêcher qu'un simple recheck rafraîchisse une vieille revue. |
| `services/rag-pedago/rag_pedago/governance/pilot_validation.py` | `ValidationAuthorization`, `evaluate_authorization` | 1 autorisation de pilote | Gouverne une opération de validation pilote via son propre scope/ref/approval | false | Autorité distincte du protocole LOT41A de release ; elle reste atomique et ne participe pas à l'union des 72 contenus. |
| `.github/workflows/_produce-h2-evidence.yml` | production H2 | 1 campagne/auth/binding | Construit H2 et promotion evidence | true | Passe le set, utilise `--json-output`, ne lit pas `issued_at` à la racine du binding. |
| `.github/workflows/promote.yml` | input `campaign_id` + appel reusable H2 | 1 campagne | Gate de promotion global | true | La campagne V2 unique référence le set ; aucune boucle de campagnes partielles. |
| `services/rag-engine/scripts/sign_production_readiness_manifest_cli.py` | parser `--authorization-file` | 1 | Lit et vérifie une autorisation avant signature | true | Le signer V2 reçoit set + racine et dérive N fichiers. |
| `services/rag-engine/scripts/sign_production_readiness_manifest_cli.py` | `main` vérifications binding/H2/revocation | 1 | Compare H2 ID/digest, binding, fenêtre et registre | true | Doit vérifier N membres, union, scopes, domaines de manifest et frontière de temps uniforme. |
| `services/rag-engine/scripts/deploy_verified_release_cli.py` | `verify_readiness_manifest_if_supplied` | 1 readiness V1 | Vérifie signature, SHA release et compose avant mutation | true | Dispatch V2 strict et vérification du set/révocations matérialisés avant pull/up. |
| `services/rag-engine/scripts/deploy_verified_release_cli.py` | `materialize_verified_bundle` | 1 readiness file | Matérialise le bundle vérifié | true | Bundle V2 doit inclure les octets exacts du set et du registre. |
| `services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py` | startup/readiness gate | 1 readiness V1 | Bloque le démarrage si signature/digests/config divergent | true | Le chemin V2 vérifie set monté, registre, fenêtre agrégée et profile manifest. |
| `services/rag-engine/src/ingestor/ingestion_control/revocation_registry.py` | `load_revocation_registry` | N entrées, schéma runtime distinct | Vérifie digest readiness puis `{registry_version, revoked}` | true | Incompatible avec le registre partagé ; le runtime V2 doit appeler le parseur canonique. |
| `services/rag-engine/src/ingestor/ingestion_control/scope_authority.py` | `verify_scope_authorization` | 1 ID/job | Relit DB, GitHub, octets, scope, fenêtre et révocation live | false | Correct au checkpoint individuel ; aucune union globale n'est requise ici. |
| `services/rag-engine/src/ingestor/ingestion_control/scope_enforcement.py` | `enforce_before_fetch`, `enforce_content_sha256`, `enforce_rights`, `enforce_pii` | 1 autorisation vérifiée/job | Applique scope, profil, domaine, allowlist, droits, PII et fenêtre aux faits réels | false | Primitive individuelle correcte après sélection du membre ; le set ne remplace pas les checkpoints par contenu. |
| `services/rag-engine/src/ingestor/ingestion_worker/authorize_scope_cli.py` | `record-authorization`, `revoke-authorization` | 1 ID/commande | Relit la PR approuvée puis persiste/révoque une autorisation individuelle | false | L'émission et la révocation restent volontairement atomiques ; le set compose les lignes après leur enregistrement. |
| `services/rag-engine/src/ingestor/ingestion_worker/issue_review_binding_cli.py` | `_issue_binding`, `--authorization-id` | 1 binding/commande | Produit la signature de revue d'une autorisation exacte | false | N bindings sont produits séparément puis référencés par le set ; aucune signature globale ne les remplace. |
| `services/rag-engine/src/ingestor/ingestion_worker/create_job_cli.py` | payload `scope_authorization_id` | 1 ID/job | Nomme explicitement l'autorisation du job avant que le SHA fetched soit connu | true | La cardinalité reste singulière, mais le chemin V2 doit charger le set/readiness monté et refuser avant fetch un ID absent ou dont le scope digest ne correspond pas au job. |
| `services/rag-engine/src/ingestor/ingestion_worker/runner.py` | `run_job`, checkpoints | 1 ID/job | Vérifie avant fetch et publication, puis l'appartenance du SHA | true | La cardinalité par job reste singulière ; le wiring V2 doit néanmoins prouver l'appartenance de l'ID au set signé avant fetch, puis conserver les contrôles individuels actuels. |
| `services/rag-engine/src/ingestor/ingestion_agents/fetcher.py` | `AuthorizationBinding` | 1 | Lie le fetch au scope et à l'autorisation nommée | false | Primitive individuelle correcte. |
| `services/rag-engine/src/ingestor/ingestion_control/publication_evidence.py` | `PublicationFacts`, `collect_publication_facts` | 1 ID/digest/protocole par contenu | Relit les faits FETCHED durables qui nomment l'autorisation réellement utilisée | false | La granularité par contenu est exacte ; elle doit rester singulière même si la release possède N autorisations. |
| `services/rag-engine/src/ingestor/ingestion_control/publication_attestation.py` | `verify_publication_attestation` | 1 ID par ressource/attestation | Revérifie live l'autorisation, son digest, allowlist, profil, manifest et droits | false | Checkpoint individuel correct ; il consomme le mapping unique produit par le set sans porter l'union globale. |
| `services/rag-engine/src/ingestor/ingestion_worker/attest_publication_cli.py` | `_load_facts_and_authorization`, propose/record | 1 `--scope-authorization-id` par attestation | Construit la revue de publication depuis faits durables et autorisation live | false | Une attestation ne couvre qu'une ressource ; N IDs entre attestations sont normaux et aucune liste par attestation n'est requise. |
| `services/rag-engine/src/ingestor/governed_publisher_v2.py` | publication + advisory locks | N IDs entre items, 1 par item | Vérifie une attestation/autorisation par contenu et verrouille la séquence | false | Supporte déjà une séquence d'IDs ; alimenter depuis le mapping de catalogue. |
| `services/rag-engine/src/ingestor/h2c_placement_readiness.py` | `H2CAuthorityBinding`, checks | 1 par partition | Vérifie une autorisation pour une partition H2-C | false | La vérification globale reste H2 V2 ; H2-C demeure par partition. |
| `services/rag-engine/src/ingestor/release_readiness.py` | release registry/readiness DB | N manifests/placements | Compare exactement artefacts, placements, chunks et modèles | false | Déjà global et exact ; l'autorisation reste une propriété par placement/job. |
| `services/rag-engine/infra/postgres/ingestion_control/migrations/007_scope_authorizations.sql` | `scope_authorizations` | N lignes, clé par ID | Stockage individuel, révocation et fenêtre | false | Le schéma représente déjà N autorisations ; aucun tableau global en DB requis. |
| `services/rag-engine/infra/postgres/ingestion_control/migrations/008_publication_attestations.sql` et `011_external_authority_commit_pins.sql` | FK/pins d'autorité | 1 ID par attestation | Traçabilité de l'autorisation ayant publié un contenu | false | Cardinalité correcte à la granularité d'une publication. |

## Findings adversariaux supplémentaires

### Collision de domaines de manifest

ADR-0032 et le worker utilisent `authorization.manifest_digest` comme
fingerprint du manifeste de profils. H2/republish le confrontent aussi au
digest du manifeste corpus. Ces identités ne sont pas interchangeables. Le
chemin V2 porte deux champs et interdit toute comparaison croisée :
`profile_manifest_digest` et `corpus_manifest_sha256`.

### Deux schémas de révocation incompatibles

Le contrat partagé, le signer et H2 lisent :

```json
{"protocol_version":"NEXUS-AUTHORIZATION-REVOCATIONS-V1","revoked_authorization_ids":[]}
```

Le runtime lit :

```json
{"registry_version":"1","revoked":[{"kind":"authorization","id":"..."}]}
```

Le même digest ne peut satisfaire ces deux parseurs. Le chemin V2 runtime
doit utiliser le parseur partagé. Le format runtime existant reste legacy et
ne bénéficie d'aucun fallback heuristique.

### Couverture actuellement non exacte

Le gate singulier vérifie principalement les manquants du set requis par
rapport à l'allowlist. La composition V2 doit comparer l'union par égalité
stricte et compter séparément `gap`, `overlap` et `extra`. Elle doit aussi
prouver que chaque contenu appartient au scope/profile de son placement,
pas seulement qu'il apparaît dans une allowlist.

### Workflow et frontière temporelle

`_produce-h2-evidence.yml` utilise actuellement `--output` puis traite la
sortie comme JSON : le chemin machine doit employer `--json-output`. Il lit
aussi `.issued_at` à la racine d'un binding signé, alors que les dates de
revue sont dans le document lié. Enfin le signer V1 accepte la frontière
`now == valid_until` alors que H2 la refuse ; le nouveau protocole uniformise
`valid_from <= now < valid_until`.

## Décision de composition

Le nom retenu est **AuthorizationSet**, et non Bundle : l'artefact contient
des références et faits canoniques vérifiables, pas une archive libre de N
fichiers. Le set est l'unique source globale ; les autorisations et bindings
restent les sources individuelles. Les surfaces globales nouvelles ne
recopient pas N listes : elles engagent `authorization_set_digest`.

La campagne retenue est une `CorpusCampaignV2` globale. N campagnes
indépendantes sont rejetées pour éviter duplication et divergence. La
revocation et la revue restent individuelles. L'union exacte est prouvée
une fois, puis liée par digest jusqu'à readiness et deploy.

## Compatibilité et statut d'ADR-0043

`H2CoverageEvidenceV1`, `CorpusCampaignV1` et
`ProductionReadinessManifestV1` restent lisibles et inchangés. Les nouveaux
documents ont des protocoles V2 explicites et ne sont jamais parsés comme
V1. ADR-0043 n'est ni une source ni une base de copie : il reste
`UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`.
