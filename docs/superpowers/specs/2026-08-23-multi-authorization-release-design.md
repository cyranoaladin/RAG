# Composition multi-autorisation d'une release — Design

**Statut :** architecture proposée après audit adversarial de `main` au SHA `3548bf300c99685ff6ede0dce2e5bfe8c044d213`, autorisée pour implémentation par la décision opérateur du 2026-08-23 ; validation humaine attendue au PR gate.

## Problème

Le set final de cette release contient 72 contenus soumis à autorité, répartis sur plusieurs `ResourceScope`. Les décisions élémentaires sont déjà correctement modélisées par `ScopeAuthorizationArtifactV2` et scellées individuellement par `ScopeAuthorizationReviewBindingV1`, mais les surfaces globales de release n'acceptent qu'une autorisation : campagne, H2, bundle de promotion, signer et readiness.

L'audit a aussi trouvé deux incohérences indépendantes de la cardinalité :

- `ScopeAuthorizationArtifactV2.manifest_digest` signifie le digest du manifeste de profils selon ADR-0032 et le runtime, alors que H2/republish le comparent aujourd'hui au manifeste corpus `SHA256SUMS.txt` ;
- le signer/H2 et le runtime attendent deux schémas incompatibles pour le même registre de révocation et le même digest de readiness.

Les formats V1 existants ont déjà une signification et des octets approuvés. Ils restent inchangés et lisibles.

## Options évaluées

### A — N campagnes indépendantes

Rejetée. Le gate actuel mesure le périmètre corpus global à chaque exécution : une autorisation partielle échoue nécessairement. Répéter le catalogue, H2 et la campagne par scope multiplierait les sources de vérité et nécessiterait malgré tout une composition globale tardive.

### B — Une campagne globale liée à un AuthorizationSet

Retenue. Les autorisations et leurs bindings restent atomiques. Un artefact global canonique, adressé par digest, les compose sans recopier N listes dans H2 et readiness. Une campagne V2 unique conserve la découverte actuelle « exactement une campagne ».

### C — Un orchestrateur hors contrat au-dessus des V1

Rejetée. Il laisserait `CorpusCampaignV1`, H2 V1 et readiness V1 déclarer une identité singulière fausse, tout en créant une deuxième source de vérité non signée.

## Architecture retenue

### AuthorizationSetV1

`NEXUS-AUTHORIZATION-SET-V1` est le mapping global groupé `contenu → ResourceScope → autorisation`. Il n'embarque pas les octets complets des autorisations ou bindings, mais contient les faits minimaux nécessaires pour rendre la composition vérifiable :

- une liste non vide, canonique et triée par `authorization_id` ;
- pour chaque membre : `authorization_id`, `authorization_digest`, `review_binding_digest`, le `ResourceScope` canonique complet, `scope_digest`, la liste canonique `allowed_content_sha256`, `allowed_content_count`, `allowed_content_set_sha256`, `valid_from` et `valid_until` ;
- `authorization_count` ;
- `corpus_manifest_sha256` et `profile_manifest_digest`, séparés explicitement ;
- `release_scope_placement_digest`, digest de la projection canonique et
  indépendante `content_sha256 → profile_id/profile_version/ResourceScope`
  issue des placements de release acceptés ;
- `authority_required_count` et `authority_required_set_sha256` ;
- `union_content_count` et `union_content_sha256_digest` ;
- `authorizations_effective_valid_from` (maximum des `valid_from`) et
  `authorizations_effective_valid_until` (minimum des `valid_until`).

Le set est donc l'unique copie globale des N partitions. H2, campaign, promotion et readiness ne recopient jamais ces listes : ils ne portent que `authorization_set_digest` et les agrégats nécessaires.

Le digest du set est le SHA-256 de ses octets canoniques. Aucun `review_binding_set_digest` séparé n'est nécessaire : le digest du set engage déjà chaque digest de binding. Les digests de contenus réutilisent exactement la convention existante `authority_required_set_digest` : SHA-256 de chaque SHA lowercase trié, suivi de `LF`, avec un `LF` final. `scope_digest` est le SHA-256 du JSON canonique du `ResourceScope` selon les mêmes règles JSON que les artefacts d'autorité (clés triées, indentation 2, UTF-8, LF final, audience triée). IDs, digests, scopes et SHA de contenus sont uniques selon leur domaine ; un doublon est un refus.

Le builder accepte les membres dans n'importe quel ordre et produit le même set trié. Le parseur exige les octets canoniques. Les chemins sont dérivés, jamais fournis membre par membre : `governance/authorizations/<authorization_id>.json` et `governance/review-bindings/<authorization_id>.json`. Le vérificateur global reçoit le set, les autorisations et bindings individuels résolus sous ces chemins, l'ancre, le registre de révocation, le manifeste de profils vérifié, la projection canonique de placements de release, l'instant de vérification et le set final attendu. Il refuse : zéro membre, membre/fichier fourni en plus du set de release attendu, membre/fichier déclaré manquant, doublon, overlap, mauvais digest/ID/scope/binding, autorisation non V2, mauvais profil/fingerprint/manifeste de profils, mauvaise projection de placement, révocation, expiration, autorisation future, union différente ou contenu affecté au mauvais scope. Les autorisations historiques ou hors release qui coexistent sous `governance/authorizations/` ne sont pas des extras : elles ne sont ni fournies dans le bundle de release ni parcourues par ce vérificateur.

La preuve de scope est une égalité à trois branches :

1. le membre du set porte le scope et la sous-liste exacte de contenus ;
2. l'autorisation individuelle doit porter exactement le même scope et la même sous-liste ;
3. la projection canonique des placements de release doit affecter chaque
   contenu de cette sous-liste à ce `profile_id/profile_version` et à ce
   scope exact ; son digest doit être
   `AuthorizationSet.release_scope_placement_digest` ;
4. ce scope doit être exactement celui du profil versionné nommé par
   l'autorisation dans le manifeste de profils vérifié.

La projection de placements est la source indépendante de l'affectation.
`ReleaseScopePlacementV1` est un contrat canonique pur
`NEXUS-RELEASE-SCOPE-PLACEMENT-V1` : il ne lit aucun fichier de service et
n'importe aucun service. Un producteur dans `rag-pedago` la dérive des
placements canoniques, du registre de release et du manifeste de profils
accepté, jamais du set ni des autorisations. Sa forme canonique trie les
lignes par `content_sha256`, exige une seule ligne par contenu, encode le
scope avec les règles canoniques ci-dessus et termine chaque ligne JSON par
`LF`. Son digest est le SHA-256 de ces octets. Les adaptateurs de
`rag-pedago` et `rag-engine` vérifient localement leurs propres profils et
passent seulement les faits canoniques au contrat partagé ; aucun service
n'importe le code d'un autre. Le builder de set ne peut donc pas rendre
valide un contenu déplacé vers un scope inventé en modifiant les deux copies
qu'il contrôle.

Le global set est lui-même relu dans la PR de campagne exacte. Ainsi une permutation est neutre, mais toute modification d'une partition, d'un profil, d'un scope ou d'un contenu change le digest du set. Une entrée `content_sha256` ne peut apparaître que dans un membre ; cette unicité fournit aussi la fonction totale `content_sha256 → authorization_id` utilisée au republish et par les jobs.

### Campagne et republish

`CorpusCampaignV2` conserve l'identité immuable du corpus et remplace le `scope`/`authorization_id` singulier par `authorization_set_digest`, `authority_required_count`, `authority_required_set_sha256` et `profile_manifest_digest`. Son `expected_manifest_sha256` reste exclusivement le SHA-256 du manifeste corpus scellé. Le republish V2 vérifie le set global une seule fois puis promeut exactement son union. Pour chaque contenu promu il matérialise `scope_authorization_id`, le scope et l'identité de profil issus de l'unique membre qui le couvre. `CorpusCampaignV1` et son parser restent inchangés pour les fixtures/releases historiques.

La création de job singulière conserve `--scope-authorization-id`. Le CLI
opérateur traite une URL avant que ses octets et donc son `content_sha256`
soient connus : il ne peut pas consulter honnêtement une clé contenu. Il
charge alors le set immuable dont le digest est scellé par readiness V2 et
exige que l'ID fourni soit l'unique membre dont le `scope_digest` correspond
au `ResourceScope` validé du job. Après fetch, le worker exige en plus que le
`content_sha256` réel appartienne à l'allowlist de cette autorisation. Pour
les contenus déjà republiés, le catalogue expose le champ
`scope_authorization_id`, indexé par `content_sha256`. Le dépôt ne contient
actuellement aucun producteur de jobs batch consommant ce catalogue : ce PR
matérialise et teste le mapping canonique mais ne prétend pas livrer un
caller inexistant. L'exécuteur de la vraie campagne, après profils et
autorisations, devra copier cet ID exact dans le payload et sera testé dans
le lot de campagne ; il ne sélectionnera jamais « la plus récente ». Aucun
set global n'est injecté dans le payload d'un job ; seul son digest de
readiness et l'autorisation individuelle nommée gouvernent les deux
checkpoints.

### H2

`H2CoverageEvidenceV2` remplace `authorization_id` et `input_file_digests["authority"]` par :

- `authorization_set_digest` ;
- `authority_required_count` ;
- `authority_covered_count` ;
- `authority_required_set_sha256` ;
- les digests réels `authorization_set`, `authority_revocations` et `review_binding_trust_anchor` dans `input_file_digests`.

Un verdict passant exige l'égalité des counts, l'union exacte, zéro gap, zéro overlap, toutes les revocations vérifiées et tous les invariants de sécurité à zéro. `H2EvidenceBundleV2` lie à son tour la campagne, le set et le rapport H2 V2. Les deux V1 restent strictement parsables et ne reconnaissent jamais un document V2.

`CoverageReport` reçoit des champs typés `authorization_set_digest`, `authorization_count`, `authority_required_count`, `authority_covered_count`, `authority_required_set_sha256`, `authorization_overlap_count`, `authorization_gap_count`, `authorization_extra_count`, `authorization_set_verified_at`, `earliest_review_submitted_at`, `earliest_review_binding_verified_at` et `earliest_review_binding_expires_at`. `generate_coverage_report` prend `authorization_set_path` au lieu des chemins singuliers sur le chemin V2, résout les membres canoniquement, vérifie chaque binding et produit ces agrégats directement depuis les champs signés `submitted_at`, `verified_at` et `expires_at` des N bindings. `report_to_h2_coverage_evidence_v2` projette ces champs sans les recalculer.

`NEXUS-H2-EVIDENCE-V2` remplace `authorization_sha256`, `exact_head_receipt_sha256` et `exact_head_receipt_issued_at` par `authorization_set_digest`, `authorization_set_verified_at`, `earliest_review_submitted_at`, `earliest_review_binding_verified_at` et `earliest_review_binding_expires_at`. La date de vérification du set n'est pas une date d'approbation. La vérification exige donc, pour le plus vieux des N bindings, `now - submitted_at <= 7 jours`, `now - verified_at <= 7 jours`, aucune date future et `now < earliest_review_binding_expires_at`, en conservant la limite V1 `EXACT_HEAD_RECEIPT_MAX_AGE`. Revérifier un vieux set ne rafraîchit jamais une revue humaine. Le CLI `h2-evidence` et `_produce-h2-evidence.yml` utilisent `--authorization-set`, produisent le rapport machine avec `--json-output`, puis vérifient les champs V2 ; ils ne lisent plus une date inexistante à la racine d'un binding.

`NEXUS-PROMOTION-EVIDENCE-V2` est émis parce que le bundle H2 change de protocole. Il porte explicitement `authorization_set_digest` en plus du digest du bundle H2. Le format de promotion V1 reste historique ; il n'est pas silencieusement réinterprété comme une preuve V2.

### Readiness, signer, deploy et startup

`ProductionReadinessManifestV2` remplace uniquement les digests singuliers d'autorisation et de binding par `authorization_set_digest`. Le reste de l'identité technique/signée est conservé. Une enveloppe signée V2 et des fonctions de parse/sign/verify V2 explicites évitent tout fallback V2 vers V1.

Le signer de cette release reçoit le set global et une racine gouvernée, puis dérive les chemins canoniques de ses membres ; il ne reçoit pas N chemins libres. Il revérifie chaque autorisation/binding, le registre canonique courant, H2 V2, les deux domaines de manifest et les liens corpus/profil avant signature. La fenêtre est uniforme : `valid_from <= now < valid_until` pour chaque autorisation et `now < expires_at` pour chaque binding.

Le bundle de déploiement V2 matérialise, en plus du readiness signé,
l'`AuthorizationSet` et le registre de révocation canonique. Le Compose de
production monte explicitement les octets du set en lecture seule sous
`/app/production/authorization-set.json`, depuis un host-file obligatoire.
Le deploy résout la source effective de ce bind avant toute mutation, la
rehash et exige son égalité au digest du set vérifié par readiness ; il
refuse donc un bundle correct accompagné d'un host-file différent avant tout
`docker compose pull/up`. Readiness gate, CLI de job et worker lisent tous ce
même chemin. Le deploy et le startup :

- vérifient `authorization_set_digest` et `revocation_registry_digest` contre readiness V2 ;
- refusent un ID du set présent dans le registre courant ;
- refusent hors de la fenêtre agrégée du set ;
- vérifient le manifeste de profils effectivement chargé par le runtime et
  exigent son digest exact égal à
  `AuthorizationSet.profile_manifest_digest` ;
- ne relisent aucune liste depuis H2 ou readiness.

La création de job et le worker revalident ensuite l'autorisation individuelle et son état DB/GitHub aux checkpoints existants. Le rollback peut toujours relire un ancien bundle V1 signé ; V1 n'est accepté que par le chemin legacy explicite, jamais par un fallback du parseur V2.

Le chemin V2 du runtime utilise le parseur partagé `NEXUS-AUTHORIZATION-REVOCATIONS-V1`. Le parseur runtime historique `{registry_version, revoked:[...]}` reste disponible uniquement pour les releases legacy ; aucun fichier n'est interprété silencieusement selon les deux schémas. H2, signer, deploy, startup et worker consultent la même source gouvernée : H2 et signer la vérifient au moment de leur production, deploy/startup exigent le digest signé courant, et le worker conserve la révocation individuelle live en base.

Les deux domaines de manifest ne sont jamais croisés :

- chaque autorisation exige `authorization.manifest_digest == AuthorizationSet.profile_manifest_digest` ;
- campagne/H2 exigent `AuthorizationSet.corpus_manifest_sha256 == SHA-256(SHA256SUMS.txt)` ;
- `profile_manifest_digest` n'est jamais comparé au corpus et `corpus_manifest_sha256` n'est jamais comparé au runtime profile manifest ;
- les anciens chemins V1 gardent leur comportement historique, sans réinterprétation de leurs octets.

### Runtime par job

Le stockage PostgreSQL, `verify_scope_authorization`, la création de job, le worker, les checkpoints fetch/rights et les attestations restent singuliers : chaque contenu appartient à exactement un scope et nomme exactement une autorisation. Le multi-auth est inter-jobs, jamais intra-job. Les révocations individuelles restent effectives en direct.

## Migration et rollback

- `nexus-contracts` passe de `0.12.0` à `0.13.0` : ajout de nouveaux protocoles, aucun changement d'octets V1.
- Le nouveau chemin de production émet V2 uniquement.
- Les fonctions V1 restent testées sur leurs fixtures historiques.
- Aucun changement de schéma DB n'est requis ; les autorisations restent des lignes individuelles.
- Rollback technique : redéploiement du dernier bundle signé V1 ou V2 déjà vérifié.
- Rollback gouvernance : retrait du set/campagne V2 par PR ; aucune réécriture d'autorisation ou de binding approuvé.

## Tier A et profils

Le recalcul final reproduit depuis les artefacts réels donne :

- `FINAL_BASE_INGEST_CANDIDATES=73` ;
- `FINAL_NON_AUTHORITY_BLOCKED_COUNT=1` ;
- `FINAL_AUTHORITY_REQUIRED_COUNT=72` ;
- `FINAL_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0`.

Le SHA-set exact trié, 72 lignes avec LF final, sera versionné dans `docs/reports/final_authority_required_set_20260823.txt`; son propre SHA-256 est la valeur ci-dessus. La preuve de reproduction et la matrice profils seront versionnées dans le rapport du lot. Les 73 candidats de base se divisent donc en 72 release-eligible soumis à autorité et 1 blocage PII non-authority. Les 2 582 contenus uniques ont une disposition terminale : 72 `INGEST_CANDIDATE`, 2 399 `REVIEW_REQUIRED`, 2 `QUARANTINE`, 19 `ARCHIVE_ONLY`, 53 `EXCLUDE`, 37 `UNSUPPORTED`.

La matrice propose 24 partitions. Dix sont entièrement groundées et couvrent 11 contenus. Quatorze couvrant 61 contenus requièrent une décision produit ; aucune valeur de profil n'est inventée. Ce manque n'empêche pas de livrer le protocole, mais interdit de créer les vraies autorisations avant résolution.

## Tests d'acceptation

Les tests exigés couvrent notamment : zéro autorisation, missing/extra/duplicate, overlap, mauvais manifest corpus/profil, contenu dans le mauvais scope ou profil, révocation/expiration (y compris égalité à `valid_until`), binding expiré, mauvais binding/digest/path, permutation stable, changement d'un membre modifiant le digest, union finale différente, schéma de révocation croisé, compatibilité V1 byte-identique, séparation stricte V1/V2, et cohérence end-to-end campagne → H2 coverage V2 → bundle H2 V2 → promotion V2 → signer → readiness V2 → deploy/startup → job.

## Hors périmètre de ce PR

- création des 24 profils de production lorsque leurs dimensions seront groundées ;
- émission des vraies autorisations et bindings ;
- migration ou déploiement production ;
- correction du rehearsal Docker mutatif/rollback, qui exige un PR technique séparé ;
- provisionnement du GitHub Environment `production`.

ADR-0043 reste `UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`.
