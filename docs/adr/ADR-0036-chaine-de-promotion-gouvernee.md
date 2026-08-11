# ADR-0036 — Chaîne de promotion gouvernée jusqu'au déploiement

- **Statut** : Proposé — **non Accepté**. Une acceptation exige une review
  humaine `APPROVED` du Code Owner `@abenrhouma` sur le HEAD exact de la PR
  d'implémentation.
- **Date** : 2026-08-11
- **Décideur proposé** : à confirmer par `@abenrhouma`.
- **Périmètre** : la chaîne qui relie un commit relu à une unité réellement
  déployée, et la preuve conservée de cette liaison. Ce document n'autorise
  aucun déploiement et ne provisionne aucune clé.
- **S'appuie sur** : ADR-0001, ADR-0025, ADR-0031, ADR-0033, ADR-0035.
- **Ne supersede rien.** ADR-0035 garde son sens entier : ce document
  ajoute la couche qui *consomme* son verdict.

## Contexte

L'audit pré-commit de `81f23a5` a établi que le verdict du gate final
H2-B/H2-F n'était consommé par personne. Aucun workflow, aucun script de
promotion, aucun mécanisme de déploiement ne lisait
`H2_COVERAGE_GATE_PASS`. Le gate était complet et sans effet.

L'inspection du dépôt a ensuite montré ce que le déploiement est
réellement aujourd'hui : `services/rag-engine/scripts/deploy-prod.sh`, un
script bash exécuté **en root, à la main, sur le serveur**, qui
synchronise des sources par `rsync` et construit les images localement
(`docker compose build`). Deux conséquences :

1. l'unité déployée n'est identifiée par rien — ni tag, ni digest, ni
   commit : deux exécutions du même script peuvent produire deux systèmes
   différents ;
2. aucun contrôle GitHub ne peut être rendu obligatoire, puisque le
   déploiement ne passe pas par GitHub.

## Décision

### 1. L'autorité de promotion passe à un Environment GitHub protégé

Le chemin normal devient :

```text
merge validé
  → workflow de promotion
  → vérification exacte (PR fusionnée, merge commit, arbres identiques)
  → construction d'artefacts immuables
  → gate de production
  → signature du manifeste de readiness
  → approbation de l'Environment production
  → déploiement par compte restreint
  → health checks
  → preuve conservée
```

Le script root manuel cesse d'être une voie normale. Il subsiste comme
**procédure break-glass** explicitement documentée et auditée.

Le chemin serveur est exécuté par un compte dédié `nexus-deployer`, sans
shell root arbitraire : clé SSH propre au déploiement, commande forcée,
ni PTY ni forwarding, `sudoers` limité à un wrapper root-owned unique, et
journalisation de chaque promotion.

### 2. Le SHA gouverné est le commit de merge, lié par l'arbre complet

Le déploiement porte sur le **commit de merge dans `main`** ; la revue
humaine ADR-0025 porte sur le **HEAD de PR exact**. Les deux sont liés par
une égalité qui ne laisse aucun jeu :

```text
git rev-parse "${PR_HEAD_SHA}^{tree}" == git rev-parse "${MERGE_SHA}^{tree}"
```

Une comparaison limitée à `governance/**` serait insuffisante : elle
prouverait que les preuves n'ont pas bougé, pas que le **code déployé**
est celui qui a été relu. C'est l'arbre complet ou rien.

Toutes les valeurs sont dérivées de GitHub ; le seul input humain est le
numéro de PR. Un `sha` fourni par l'opérateur ne peut servir que de
confirmation redondante, jamais de source d'autorité.

### 3. Sémantique du tag de release, figée

Format canonique : `release/rag/YYYYMMDD-<merge_sha12>`.

```text
RELEASE_TAG_CREATED_AFTER_GATE=true
RELEASE_TAG_CREATED_AFTER_MANIFEST_SIGNATURE=true
RELEASE_TAG_CREATED_BEFORE_DEPLOYMENT=true
RELEASE_TAG_MEANS_IMMUTABLE_RELEASE_IDENTITY=true
RELEASE_TAG_MEANS_SUCCESSFUL_DEPLOYMENT=false
```

Le tag identifie une version **candidate** au déploiement. Il peut donc
légitimement subsister sur un déploiement qui a échoué : le résultat du
déploiement est porté ailleurs — statut de l'Environment, artifact de
preuve final, journal d'audit, health checks. Aucun tag n'est jamais
déplacé ni réutilisé.

### 4. Manifeste de readiness signé — `NEXUS-PRODUCTION-READINESS-V1`

Introduit par cet ADR dans `packages/contracts`
(`nexus_contracts.production_readiness`). Il vit dans le contrat partagé
parce qu'il traverse **trois** frontières : le workflow qui l'émet, le
wrapper serveur qui refuse de déployer sans lui, et le runtime
d'ingestion qui refuse de démarrer sans lui. Trois parseurs indépendants
finiraient par diverger, et un manifeste interprété différemment par le
vérificateur et par l'exécutant n'est plus une preuve.

Vingt-six champs obligatoires, `extra="forbid"`, canonicalisation octet à
octet, signature Ed25519. Il lie le dépôt, la PR, les quatre SHA (HEAD de
PR, arbre de PR, merge, arbre de merge), le tag, l'environnement, les
sept digests de preuves de gouvernance, le verdict du gate, les digests
OCI de **toutes** les images applicatives et amont, le digest du fichier
Compose résolu, et la provenance d'émission (workflow, ref, run, tentative,
instant, clé).

Refus par construction : arbre divergent, tag incohérent avec le merge
SHA, image désignée par un tag mutable plutôt qu'un digest, environnement
autre que `production`, verdict non passant, champ inconnu ou manquant.

### 5. Séparation des clés

```text
READINESS_SIGNING_KEY_SEPARATE_FROM_REVIEW_BINDING_KEY=true
NEXUS_PRODUCTION_READINESS_SIGNING_KEY
governance/trust-anchors/production-readiness-v1.json
```

La clé qui signe un manifeste de readiness n'est jamais celle qui signe un
reçu de liaison de revue. Les deux autorités sont distinctes : l'une
atteste qu'un humain a relu une autorisation, l'autre qu'une chaîne de
promotion complète a réussi. Une clé unique permettrait à quiconque peut
émettre un reçu d'émettre aussi une autorisation de déploiement.

L'ancre de readiness porte son propre `protocol_version` : une ancre de
review binding présentée à sa place est refusée par type, pas seulement
faute de contenir la bonne clé. La clé privée ne vit que dans
l'Environment `production` ; seule la clé publique est versionnée.

### 6. Mode répétition

Le contrat de production n'est **pas** affaibli pour accueillir un
rehearsal : `environment` y est littéralement `"production"`. Une
répétition utilise ses propres fixtures et sa propre ancre, dans un
chemin distinct. Accepter silencieusement `rehearsal` dans le contrat de
production reviendrait à rendre indiscernables une preuve et une
répétition.

## Modèle de menace

```text
HOST_ROOT_IS_TRUSTED=true
HOST_ROOT_COMPROMISE_OUT_OF_SCOPE=true
ROUTINE_OPERATOR_BYPASS_MUST_BE_BLOCKED=true
BREAK_GLASS_ACTIVITY_MUST_BE_AUDITED=true
```

Le contrôle runtime **n'est pas** une protection cryptographique contre
l'administrateur de l'hôte. Un root hostile ou compromis peut modifier le
code, monter un faux manifeste, changer l'environnement, redéployer une
révision ancienne, remplacer les images ou le wrapper, ou parler
directement à PostgreSQL. Prétendre le contraire serait une fausse
assurance.

Ce que le contrôle runtime ferme réellement, en défense en profondeur :

- l'erreur de configuration ;
- la substitution par un processus non privilégié ;
- le démarrage incomplet ;
- le déploiement normal privé de preuve.

C'est utile et c'est borné ; les deux doivent être dits.

## Conséquences

**Positives.** Le verdict du gate cesse d'être décoratif. L'unité déployée
devient identifiable et reproductible. La revue humaine couvre exactement
ce qui tourne. Chaque promotion laisse une preuve vérifiable hors GitHub.

**Négatives, assumées.** Un second secret de signature doit être
provisionné. La chaîne devient plus longue qu'un `ssh && ./deploy-prod.sh`.
Le stack legacy et son script devront être dépréciés dans un lot
ultérieur, avec le cutover v2 prévu au Lot 1.2 — cet ADR ne le fait pas.

**Non traité ici.** La rotation des deux clés, la transparence des
manifestes émis (log append-only), et la migration des images vers GHCR
sont conçues mais implémentées en phase B.

## Alternatives écartées

- **Gate CI seul, déploiement manuel inchangé** — contournable par
  `sudo deploy-prod.sh` ; un théâtre de conformité.
- **Gate uniquement dans le runtime** — ne couvre pas la mise à jour du
  stack, et fut d'abord présenté à tort comme incontournable par root.
- **Réutiliser la clé de review binding** — confond deux autorités.
- **Comparer seulement `governance/**` entre PR et merge** — prouverait
  que les preuves n'ont pas bougé, pas que le code déployé est celui relu.
- **OIDC vers un fournisseur cloud** — aucun fournisseur compatible n'est
  identifié : la cible est un hôte unique sans registry cloud. Inventer un
  fournisseur aurait produit une conception invérifiable.
