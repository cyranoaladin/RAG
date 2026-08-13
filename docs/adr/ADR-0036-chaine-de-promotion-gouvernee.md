# ADR-0036 — Chaîne de promotion gouvernée jusqu'au déploiement

- **Statut** : **Accepté** (2026-08-13). Décision positive rendue
  conformément à ADR-0025 : review humaine `APPROVED` du Code Owner
  `@abenrhouma`, `commit_id` égalant exactement le HEAD final de PR #95 au
  moment de la review — voir « Preuve d'acceptation », plus bas, pour le
  détail vérifiable. Même review, même head, même chaîne de preuve que
  l'acceptation d'ADR-0035 (introduits par la même PR).
- **Date de rédaction** : 2026-08-11
- **Date d'acceptation** : 2026-08-13
- **Décideur** : `@abenrhouma` (Code Owner, ADR-0025).
- **Autorité de la décision** : ADR-0025 (autorité de revue humaine GitHub).
- **PR de décision** : [#95](https://github.com/cyranoaladin/RAG/pull/95) —
  la même PR qui introduit à la fois ce document et le contrat qui
  implémente son mécanisme central
  (`packages/contracts/src/nexus_contracts/production_readiness.py`,
  protocole `NEXUS-PRODUCTION-READINESS-V1`). Aucune autre PR fusionnée ne
  touche ce fichier ADR — vérifié via l'historique serveur GitHub d'un
  chemin (`gh api repos/.../commits?path=...`, non plafonné,
  jamais l'historique Git local seul ni la liste de fichiers par PR de
  `gh pr list`, plafonnée à 100 fichiers par PR — voir « Preuve
  d'acceptation » pour le détail) : un seul commit avant ce lot,
  `2182339` (PR #95). Le parcours d'historique par chemin remonte tout le
  graphe de commits atteignable depuis `main`, quelle que soit la
  stratégie de fusion utilisée par chaque PR (squash, rebase, ou merge à
  deux parents) : cela couvre donc exhaustivement toute PR fusionnée, sans
  dépendre d'une hypothèse sur la méthode de fusion.
- **Périmètre** : la chaîne qui relie un commit relu à une unité réellement
  déployée, et la preuve conservée de cette liaison. Ce document n'autorise
  aucun déploiement et ne provisionne aucune clé.
- **S'appuie sur** : ADR-0001, ADR-0025, ADR-0031, ADR-0033, ADR-0035.
- **Ne supersede rien.** ADR-0035 garde son sens entier : ce document
  ajoute la couche qui *consomme* son verdict.

## Preuve d'acceptation

Cette section documente précisément ce qui a été approuvé, par qui, vérifié
en direct plutôt que déduit d'un texte historique — même chaîne de preuve
que celle établie pour l'acceptation d'ADR-0035 (`docs/adr/ADR-0035-
liaison-revue-scellee-autorisation-de-scope.md`), puisque les deux
documents sont introduits par la même PR :

1. **`3d0cf47133dfdba488890a9be3e6fe1fc83bd863`** est le HEAD exact de PR
   #95 tel qu'il existait immédiatement avant son merge — c'est **cet état
   précis** qui a été inspecté et approuvé humainement.
2. La review GitHub `APPROVED` porte explicitement sur cet état :
   **Reviewer** `@abenrhouma`, review `id=4923100913`, `state=APPROVED`,
   `commit_id=3d0cf47133dfdba488890a9be3e6fe1fc83bd863`, soumise le
   `2026-08-13T03:22:26Z` — recoupée via l'API GitHub paginée (45 entrées
   au total pour PR #95), jamais prise au mot depuis un seul appel non
   paginé. Le challenge correspondant (`NEXUS-TRUSTED-REVIEW-V1:
   ab4e17ab79bb118ab4661cadef9f48820a02d5c9bf3c30baa9b003d07f785fff`) a
   été revérifié par le run GitHub Actions réel `31663947902`
   (`conclusion: success`), qui republie la même décision machine.
3. Aucune review `DISMISSED` ni `CHANGES_REQUESTED` d'`@abenrhouma`
   n'existe après cette approbation (vérifié à nouveau, indépendamment,
   pour cette acceptation). Les deux seules reviews `DISMISSED` du même
   reviewer portent sur des heads antérieurs
   (`f2a662bc8054e35643cda0aa71cd8496aca2e8fe`,
   `e9708feca0b3438f2667c872a70106095abf0ba1`, toutes deux du 2026-08-10,
   bien avant l'approbation finale).
4. GitHub a ensuite fusionné PR #95 (`merged_at`: `2026-08-13T03:35:10Z`),
   produisant le commit `2182339fb9a0df49419370e5ead8b92ef4d62305` sur
   `main` — 13 minutes après l'approbation, sans review intermédiaire.
5. **Cette acceptation est architecturale et documentaire uniquement.**
   Elle ne constitue ni un déploiement, ni une autorisation de contenu, ni
   une clé provisionnée. La chaîne de promotion qu'elle décrit continue
   d'être construite incrémentalement : le manifeste de readiness qu'elle
   introduit (PR #95/#97), la liaison de revue scellée (ADR-0035/PR #99),
   et la provenance d'image de production (PR #102) sont chacun des lots
   séparés, gouvernés indépendamment, dont l'acceptation de ce document ne
   dispense aucun.

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

### 7. Politique de rejeu — pas d'`expires_at`, et pourquoi

```text
READINESS_EXPIRY_REQUIRED=false
READINESS_SAME_RELEASE_REPLAY_ALLOWED=true
READINESS_CROSS_RELEASE_REPLAY_ALLOWED=false
```

Le manifeste `NEXUS-PRODUCTION-READINESS-V1` n'a **volontairement** pas de
date d'expiration, contrairement au reçu de liaison de revue d'ADR-0035.
La différence n'est pas un oubli : les deux objets prouvent des choses de
natures différentes. Un reçu de revue atteste un *état GitHub à un
instant* — une PR peut être ré-ouverte, une approbation retirée — donc il
vieillit. Un manifeste de readiness atteste une *identité immuable* :
mêmes SHA, mêmes arbres, mêmes digests d'images, même Compose. Cette
identité ne vieillit pas.

**Ce que le binding rend impossible.** Le manifeste nomme le dépôt, la PR,
le HEAD de PR, l'arbre du HEAD de PR, le commit de merge, l'arbre de
merge, les sept digests de preuves de gouvernance, les digests OCI de
toutes les images et le digest du Compose résolu. Un manifeste d'une
release ne peut donc pas en valider une autre : `require_manifest_matches
_release` compare le merge SHA, et tout le reste est dans les octets
signés.

**Pourquoi une expiration nuirait.** Rejouer le même manifeste pour la
même unité immuable est exactement ce qu'un rollback et un redéploiement
idempotent exigent. Une expiration arbitraire rendrait un rollback
légitime impossible au pire moment — pendant un incident — sans rien
empêcher qu'une divergence de SHA ou de digest n'empêche déjà. L'
expiration de l'artifact GitHub bloque une *nouvelle* promotion dont la
preuve manque ; elle ne doit pas invalider rétroactivement une release
déjà gouvernée et conservée sur le serveur.

| Scénario | Verdict |
|---|---|
| même merge SHA, mêmes arbres, mêmes digests | **autorisé** — rollback et redéploiement idempotent |
| autre merge SHA | refusé — `require_manifest_matches_release` |
| tree SHA différent | refusé — invariant du modèle (`pr_head_tree_sha == merge_tree_sha`) |
| autre Compose ou digest d'image | refusé — signature invalidée |
| autre environnement | refusé — `environment` est dans les octets signés |
| signature par une clé absente de l'ancre readiness | refusé — `key()` de l'ancre |
| clé readiness retirée de l'ancre | refusé à **toute nouvelle vérification** |
| autorisation révoquée par `authorize_scope_cli --revoke` | publication refusée — `verify_scope_authorization` lit `scope_authorizations.revoked_at` à chaque vérification d'attestation |
| registre gouverné `authorization-revocations-v1.json` modifié seul | **ne bloque aucune publication déjà attestée** — voir § 9 |
| artifact GitHub expiré avant promotion | promotion refusée — la preuve requise manque |
| manifeste déjà installé, rollback connu | autorisé si **toutes** les identités correspondent |

Le rejeu d'un manifeste ancien ne peut donc pas publier du contenu
révoqué : la révocation runtime est revérifiée en direct contre la base à
chaque vérification d'attestation, indépendamment du manifeste. Le
manifeste prouve *quelle release tourne*, pas *ce qui est encore
autorisé* — et c'est cette séparation qui rend le rejeu sûr sans
expiration.

### 9. Deux surfaces de révocation, à ne pas confondre

Une version antérieure de ce document laissait entendre qu'éditer le
registre gouverné bloquait une publication. C'est faux, et l'imprécision
était dangereuse : elle pouvait conduire un opérateur à croire une
révocation effective alors qu'elle ne l'était pas. Les deux surfaces sont
distinctes, complémentaires, et **ne se remplacent pas**.

| | Registre gouverné | Révocation runtime |
|---|---|---|
| Fichier / colonne | `governance/trust-anchors/authorization-revocations-v1.json` | `ingestion_control.scope_authorizations.revoked_at` |
| Écrit par | un diff versionné, soumis à revue humaine | `authorize_scope_cli --revoke`, sous autorité GitHub vérifiée |
| Lu par | le gate de campagne H2-B/H2-F (`rag-pedago`) | `verify_scope_authorization` (`rag-engine`), avant toute publication |
| Effet | empêche une **future** campagne de produire une preuve H2 verte | refuse **immédiatement** toute publication, y compris pour une release déjà déployée |
| Ne fait pas | ne touche pas une publication déjà attestée ni un worker déjà démarré | ne bloque pas la génération d'un rapport H2 |

`rag-engine` ne lit **jamais** le fichier registre : la séparation des
plans (ADR-0001) l'interdit, et la révocation qui compte pour une
publication vit dans le plan de contrôle, sous les mêmes preuves d'autorité
GitHub que l'autorisation qu'elle annule.

**Conséquence opérationnelle.** Une révocation d'urgence passe
obligatoirement par `authorize_scope_cli --revoke`. Éditer le registre
gouverné seul est une décision de *campagne* — utile, tracée, revue — mais
qui laisse tourner ce qui tourne déjà. Les deux gestes sont normalement
faits ensemble ; les confondre revient à croire qu'on a fermé une porte
qu'on n'a pas touchée.

### 8. Rotation des clés de readiness

La politique de rotation remplace le besoin d'un `expires_at` aveugle :
elle révoque par **décision**, là où une expiration révoque par
**écoulement du temps**, sans rapport avec la sûreté de la release.

- une clé publique readiness **ne doit pas être retirée** de l'ancre tant
  qu'une release signée par elle reste un candidat de rollback autorisé ;
- retirer la clé invalide volontairement les manifestes correspondants à
  toute nouvelle vérification — c'est le mécanisme de révocation ;
- la liste des releases rollbackables doit donc être mise à jour **avant**
  tout retrait, et le retrait constaté comme sûr ;
- aucune ancienne clé ne reste autorisée indéfiniment sans justification
  écrite : une clé conservée « au cas où » est une clé dont personne ne
  décide plus ;
- la rotation ménage une période de recouvrement contrôlée, pendant
  laquelle ancienne et nouvelle clés sont déclarées, afin qu'aucun
  rollback ne devienne impossible entre deux promotions ;
- la procédure break-glass ne doit jamais réintroduire silencieusement une
  clé retirée : l'ancre est versionnée, donc toute réintroduction est un
  diff soumis à revue.

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
