# ADR-0044 — Composition multi-autorisation d'une release

- **Statut** : **Proposé — HUMAN GATE requis sur la PR contractuelle**.
- **Date** : 2026-08-23.
- **Décideur attendu** : reviewer humain habilité, avec challenge
  `NEXUS-TRUSTED-REVIEW-V1` lié au HEAD exact de la PR.
- **Périmètre** : représentation et vérification de N autorisations de scope
  dans une seule release ; campagne, H2, promotion, readiness, signer,
  déploiement et startup associés.
- **S'appuie sur** : ADR-0001, ADR-0032, ADR-0035, ADR-0042.
- **Ne supersede aucun ADR accepté.** ADR-0043 reste
  `UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`.

## Contexte et problème réel

Le recalcul read-only du corpus sur `main` au SHA
`3548bf300c99685ff6ede0dce2e5bfe8c044d213` établit 73 candidats de base,
un blocage PII non lié à l'autorité et un set final de 72 contenus soumis à
autorité. Ces contenus doivent être répartis entre plusieurs
`ResourceScope`, sans wildcard ni affectation inventée.

`ScopeAuthorizationArtifactV2` et `ScopeAuthorizationReviewBindingV1`
expriment correctement une décision et sa revue, individuellement. La
chaîne globale est cependant singulière : `CorpusCampaignV1.authorization_id`,
`H2CoverageEvidenceV1.authorization_id`,
`input_file_digests["authority"]`, les paramètres `authority_path` et
`review_binding_path`, puis
`ProductionReadinessManifestV1.authorization_digest` et
`review_binding_digest`. Le signer et les workflows suivent la même
cardinalité. La matrice exhaustive est publiée dans
`docs/reports/multi_authority_contract_surface_audit_20260823.md`.

L'audit révèle aussi deux défauts de trust qui doivent être corrigés sur le
chemin V2 :

1. `ScopeAuthorizationArtifactV2.manifest_digest` est le fingerprint du
   manifeste de profils selon ADR-0032, mais des chemins H2/republish le
   comparent au manifeste corpus `SHA256SUMS.txt` ;
2. le parseur partagé attend
   `NEXUS-AUTHORIZATION-REVOCATIONS-V1` avec
   `revoked_authorization_ids`, alors que le runtime lit un schéma distinct
   `{registry_version, revoked:[{kind,id}]}`.

## Options étudiées

### A. N campagnes indépendantes

Rejetée. Le gate mesure le corpus global à chaque run : chaque autorisation
partielle laisserait des gaps. N campagnes dupliqueraient catalogue, H2 et
readiness sans supprimer la nécessité d'une composition globale.

### B. Une campagne V2 liée à un `AuthorizationSet`

Retenue. Les décisions individuelles restent autonomes, tandis qu'un seul
artefact canonique prouve l'union exacte et devient l'identité globale
référencée par digest.

### C. Un orchestrateur hors contrat au-dessus des V1

Rejetée. Il conserverait des champs singuliers sémantiquement faux dans des
preuves signées et introduirait une seconde source de vérité non contractée.

## Décision

### Autorisations et bindings individuels inchangés

Chaque partition reste un `ScopeAuthorizationArtifactV2`. Chaque
autorisation conserve son `ScopeAuthorizationReviewBindingV1`, sa fenêtre
de validité et sa révocation individuelle. Le stockage et l'exécution par
job restent singuliers : un contenu, un scope, un
`scope_authorization_id`. Aucun champ V1 n'est transformé en liste.

### `NEXUS-AUTHORIZATION-SET-V1`

Un nouvel `AuthorizationSetV1` compose une liste non vide et triée de
membres. Chaque membre engage :

- `authorization_id`, `authorization_digest` et `review_binding_digest` ;
- le `ResourceScope` canonique complet et son digest ;
- `allowed_content_sha256`, son count et son set digest ;
- `valid_from` et `valid_until`.

Le document engage aussi `authorization_count`,
`corpus_manifest_sha256`, `profile_manifest_digest`,
`release_scope_placement_digest`, `authority_required_count`,
`authority_required_set_sha256`, `union_content_count`,
`union_content_sha256_digest`, puis la fenêtre agrégée
`max(valid_from) <= now < min(valid_until)`.

Les membres peuvent être fournis dans n'importe quel ordre au builder ; la
forme persistée est triée. Une permutation conserve le digest. Un membre,
scope, binding ou contenu modifié change le digest. Zéro membre, doublon,
overlap, gap, extra, révocation, autorisation future/expirée, binding
invalide/expiré, digest faux ou fichier manquant/supplémentaire sont des
refus.

### Canonicalisation

Le digest d'un document est le SHA-256 du JSON UTF-8 canonique : clés
triées, indentation de deux espaces, `ensure_ascii=false`, LF final. Les
audiences de scope sont triées. Le digest d'un set de contenus réutilise
la règle actuelle : SHA lowercase triés, un SHA par ligne, LF final, puis
SHA-256 de ces octets. Les chemins membres sont dérivés de l'ID :

- `governance/authorizations/<authorization_id>.json` ;
- `governance/review-bindings/<authorization_id>.json`.

### Preuve indépendante contenu → scope

`NEXUS-RELEASE-SCOPE-PLACEMENT-V1` représente la projection indépendante
des placements acceptés sous la forme
`content_sha256 → profile_id/profile_version/ResourceScope`. Elle est
produite par `rag-pedago` depuis placements, release registry et manifeste
de profils, jamais depuis le set ou les autorisations. Le contrat partagé
reste une représentation pure et n'importe aucun service.

La vérification exige une égalité à quatre branches : membre du set,
autorisation individuelle, projection de placement, profil versionné du
manifeste vérifié. Un contenu ne peut apparaître que dans un membre. Cette
unicité fournit la fonction totale
`content_sha256 → scope_authorization_id` matérialisée au republish.

### Union exacte et anti-overlap

Les allowlists des membres sont deux-à-deux disjointes. Leur union doit être
strictement égale au fichier final de 72 SHA : aucun SHA manquant, aucun SHA
supplémentaire. `authority_required_count`, le digest du set requis, le
count d'union et le digest d'union doivent tous concorder. Une multiplicité
future ne pourra être admise que par un nouveau protocole explicite.

### Campagne et republish

`CorpusCampaignV2` conserve l'identité corpus et remplace le scope/ID
singulier par `authorization_set_digest`, les agrégats du set requis et
`profile_manifest_digest`. `expected_manifest_sha256` continue à désigner
exclusivement le manifeste corpus. Le republish V2 vérifie le set une fois,
publie exactement l'union et annote chaque contenu avec l'autorisation,
le profil et le scope uniques qui le gouvernent.

Le dépôt ne contient pas encore de producteur batch qui transforme ce
catalogue republié en jobs. Le présent lot matérialise donc la fonction
canonique `content_sha256 → scope_authorization_id` sans inventer un appelant.
Le lot de campagne réelle devra copier cet ID exact dans le payload singulier
et le tester de bout en bout ; il ne pourra ni choisir une autorisation
« récente », ni reconstruire localement la partition globale.

### H2

`H2CoverageEvidenceV2` remplace l'identité singulière par
`authorization_set_digest`, `authority_required_count`,
`authority_covered_count` et `authority_required_set_sha256`.
`input_file_digests` engage le set, le registre partagé et l'ancre des
bindings. Un verdict passant exige égalité des counts, union exacte, zéro
gap, overlap et extra, toutes les révocations vérifiées et tous les
invariants sécurité à zéro.

`CoverageReport` et `generate_coverage_report` obtiennent une branche V2
typée qui résout et vérifie chaque membre. `H2EvidenceBundleV2` lie campagne,
set et couverture V2, et porte les dates les plus anciennes de revue/binding
pour qu'une nouvelle vérification technique ne puisse pas rafraîchir une
ancienne revue humaine. Le workflow produit le JSON avec `--json-output`.

La politique de fraîcheur agrégée est explicite. Le bundle publie
`earliest_review_submitted_at`, `earliest_review_binding_verified_at` et
`earliest_review_binding_expires_at`, calculés sur tous les bindings du set.
Les deux premières dates ne doivent pas être futures et doivent chacune
satisfaire `now - date <= 7 jours`, en réutilisant la limite V1 existante
`EXACT_HEAD_RECEIPT_MAX_AGE`. La troisième impose strictement
`now < earliest_review_binding_expires_at`. `authorization_set_verified_at`
reste une date de contrôle technique : revérifier le même set ne rafraîchit
jamais la date ni la fraîcheur d'une revue humaine.

### Promotion et readiness

`NEXUS-PROMOTION-EVIDENCE-V2` engage explicitement
`authorization_set_digest`. `ProductionReadinessManifestV2` remplace les
deux digests singuliers d'autorisation/binding par ce digest unique ; le
digest du set engage sans ambiguïté chaque binding individuel. Une enveloppe
signée V2 et des parseurs V2 explicites empêchent tout fallback V2 vers V1.

La production de preuves H2/promotion V2 fraîches est limitée au commit de
merge qui est exactement le HEAD courant de `main`. Un ancêtre de `main` est
refusé : exécuter les producteurs et relire les fichiers courants tout en
nommant une ancienne identité mélangerait deux releases. Cette restriction ne
modifie pas ADR-0036 §7 : le rollback peut rejouer une readiness déjà signée,
immuable et conservée, mais ne régénère pas de nouvelles preuves pour cet
ancien commit.

### Signer, deploy et startup

Le signer V2 reçoit le set et une racine gouvernée, dérive les chemins des
membres, vérifie chaque autorisation/binding, le registre canonique, H2 V2,
les deux domaines de manifest et la fenêtre uniforme
`valid_from <= now < valid_until` avant de signer. Il résout l'unique artefact
`promotion-evidence-<merge_sha>-<campaign_id>` du run de promotion vérifié et
exige que son `promotion-evidence.json` soit identique octet par octet à la
preuve locale utilisée. Enfin, immédiatement avant de lire la clé privée, il
relit `refs/heads/main` et refuse de créer une nouvelle signature si le merge
n'en est plus le HEAD ; cela n'interdit pas le rejeu d'une readiness historique
déjà signée pour rollback.

La CLI opérateur conserve `republish-catalog` pour V1 et expose une voie
distincte `republish-catalog-v2`. Cette dernière ne reçoit aucune autorité ni
review binding singulier : elle relit campagne, `AuthorizationSet` et membres
depuis le tree Git exact, puis délègue à la frontière V2 partagée.

Le bundle de déploiement V2 matérialise le set et le registre de révocation.
Deploy et startup rehashent les octets montés, exigent le digest readiness,
refusent tout membre révoqué ou hors fenêtre, et vérifient le manifeste de
profils réellement chargé. Toute divergence est refusée avant mutation
Docker. Le runtime V2 utilise le parseur partagé du registre ; le parseur
historique reste uniquement sur le chemin legacy explicite.

### Exécution par job et révocation live

La création d'un job continue à exiger un `scope_authorization_id` unique.
Avant fetch, l'ID doit appartenir au set signé et son scope correspondre au
scope validé du job. Après fetch, le SHA réel doit appartenir à l'allowlist
de cette autorisation. Le worker relit l'état individuel DB/GitHub et les
révocations aux checkpoints actuels. Le multi-auth est inter-jobs, jamais
intra-job.

### Séparation des domaines de manifest

- `authorization.manifest_digest == AuthorizationSet.profile_manifest_digest` ;
- le SHA du corpus scellé est comparé uniquement à
  `AuthorizationSet.corpus_manifest_sha256` ;
- aucune comparaison croisée corpus/profils n'est permise.

## Compatibilité V1/V2 et SemVer

`nexus-contracts` passe de `0.12.0` à `0.13.0`, évolution additive. Les V1
restent lisibles, vérifiables et byte-identiques à leurs fixtures gelées.
Les V2 ont des `protocol_version` nouveaux et ne sont jamais acceptés par
un parseur V1, ni inversement. Le chemin production nouveau émet uniquement
les V2 ; les anciennes releases utilisent un chemin legacy explicite.

## Migration

1. publier les contrats additifs et conserver les fixtures V1 ;
2. produire la projection indépendante après résolution des profils ;
3. produire les autorisations/bindings individuels puis l'AuthorizationSet ;
4. migrer campagne, republish, H2, promotion et signer vers V2 ;
5. vérifier deploy/startup/runtime V2 en rehearsal ;
6. signer et promouvoir uniquement après le human gate et toutes les suites
   vertes.

Aucune migration de schéma DB n'est requise pour la cardinalité : les lignes
d'autorisation et les payloads de job restent individuels.

## Rollback

Le rollback technique redéploie le dernier bundle signé V1 ou V2 déjà
vérifié, via son chemin de protocole explicite. Le rollback gouvernance
retire le set/campagne V2 par PR ; il ne réécrit ni autorisation ni binding
approuvé. Un rollback n'autorise jamais l'interprétation d'un document V2
comme V1.

## Conséquences

La release obtient une seule identité globale, tout en conservant scope,
review binding, validité et révocation individuels. La duplication des N
listes est limitée au seul artefact canonique. En contrepartie, campagne,
H2, promotion, readiness, signer, deploy et startup exigent de nouveaux
protocoles explicites et davantage de tests adversariaux.

Ce document n'autorise aucun contenu, ne crée aucun profil, ne signe aucune
readiness et n'autorise aucun déploiement. Son acceptation est le prochain
human gate.
