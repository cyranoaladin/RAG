# LOT41V — Autorité de revue humaine GitHub

## Statut et objectif

Cette spécification est validée pour préparer la frontière de confiance requise
par LOT41A sans activer de capacité métier. LOT41V rend une approbation humaine
indépendante obligatoire et vérifiable sur le SHA exact d'une pull request.

Le reviewer autorisé initial est `abenrhouma`, collaborateur dont le rôle
GitHub `write` est relu par API. Cette habilitation est un prérequis externe,
pas une preuve d'approbation : seul un acte `APPROVED` effectué personnellement
par ce reviewer sur le dernier head peut ouvrir le garde GitHub.

LOT41V ne passe aucun verrou `*_allowed` à `true`, n'ingère aucun document et ne
prétend pas terminer LOT41A, LOT42 ou le go-live. Le verdict global reste
`GO_LIVE: NO_GO`.

## Décision d'architecture

Le lot sépare trois autorités :

1. GitHub conserve l'identité, la review formelle et la protection de branche.
2. Un workflow privilégié présent uniquement sur la branche de base vérifie la
   review et publie un statut sur le head exact.
3. La politique versionnée décrit les règles que l'outil opérateur applique et
   relit sur `main`.

Le workflow utilise `pull_request_target` et `issue_comment`, deux événements
dont le code privilégié est chargé depuis la branche par défaut.
`issue_comment` ne lance le recalcul que pour la commande publique littérale
`/nexus-trusted-review` sur une PR dont la base relue par API est `main` ; son
contenu n'est jamais injecté dans un shell. Le workflow ne checkout jamais le
head de la PR,
n'exécute aucun script provenant de la PR et n'interprète aucun champ libre
comme une commande. Le vérificateur exécuté est celui de la branche de base.

`pull_request_review` est explicitement exclu : cet événement utilise le merge
ref de la PR et peut donc charger un YAML de workflow proposé par la branche à
auditer. Le checkout ultérieur de `main` ne suffirait pas à protéger les étapes
et permissions déjà définies par ce YAML. `workflow_dispatch` est également
exclu parce qu'un opérateur peut sélectionner un `ref` autre que `main`.

Cette architecture est préférée à un workflow `pull_request` modifiable par le
contributeur, et à une preuve YAML locale que l'auteur pourrait recalculer.

## Séquence de transition sans verrouillage

La transition se fait en deux temps :

1. LOT41V est développé sous la protection actuelle. `abenrhouma` est promu à
   `write`, reçoit une demande de review et doit approuver personnellement le
   head final de LOT41V. Cette approbation est vérifiée par readback GitHub avant
   fusion au moyen de l'adaptateur local `--check`, même si le compteur live vaut
   encore zéro et que le workflow bootstrap n'existe pas sur `main`. La sortie
   normalisée est publiée dans la conversation sans créer de statut.
2. Après le run `push` vert du commit fusionné, la nouvelle politique est
   appliquée à `main`. Les PR suivantes exigent alors le statut
   `trusted-human-review`, une approbation, une review Code Owner et
   l'approbation du dernier push.

Le statut privilégié n'est ajouté aux contextes obligatoires qu'après que le
workflow correspondant existe sur `main`. Cette chronologie évite de rendre
toute PR impossible à fusionner.

## Politique GitHub cible

Les six contextes CI existants restent obligatoires et distincts :

- `packages/contracts` ;
- `services/rag-pedago` ;
- `services/rag-engine` ;
- `services/cockpit` ;
- `governance locks guard` ;
- `repository controls`.

Le contexte `trusted-human-review` est ajouté après installation du workflow.
La protection cible impose également :

- `required_approving_review_count = 1` ;
- `required_status_checks.strict = true`, afin qu'une avance de `main` impose
  l'intégration de la nouvelle base, un nouveau head et un nouveau challenge ;
- `dismiss_stale_reviews = true` ;
- `require_code_owner_reviews = true` ;
- `require_last_push_approval = true` ;
- `enforce_admins = true` ;
- historique linéaire et conversations résolues ;
- aucun bypass utilisateur, équipe ou application ;
- force-push et suppression interdits.

Un fichier `.github/CODEOWNERS` désigne `@abenrhouma` pour l'ensemble du dépôt.
Ce choix est volontairement strict : tous les lots qui peuvent affecter la
chaîne de confiance doivent obtenir une décision indépendante.

## Challenge canonique

Le challenge est calculé à partir d'un objet JSON canonique contenant exactement
les champs suivants :

- dépôt `owner/name` ;
- numéro de PR ;
- branche de base, obligatoirement `main` ;
- SHA de base observé ;
- SHA de head observé ;
- auteur de la PR ;
- reviewer attendu ;
- version du protocole LOT41V.

La sérialisation utilise UTF-8, des clés triées et des séparateurs JSON compacts.
Le challenge public est `NEXUS-TRUSTED-REVIEW-V1:<sha256>`. Le workflow publie ou
met à jour un commentaire géré indiquant le challenge attendu pour le head
courant. Le reviewer doit inclure ce challenge exact dans le corps de sa review
`APPROVED`.

Tout changement de head produit un autre challenge et invalide les reviews
précédentes. Aucun timestamp ni secret n'entre dans le digest ; l'autorité vient
de l'identité GitHub authentifiée et du workflow de base, pas de l'entropie du
challenge.

## Vérification d'une review

Le vérificateur reçoit des données JSON déjà collectées par le workflow et reste
pur, déterministe et sans réseau. Il refuse par défaut lorsque :

- le dépôt, la PR, la base ou le head diffèrent de l'événement courant ;
- le dépôt du head diffère du dépôt audité : les PR provenant d'un fork sont
  refusées par cette première version ;
- la PR est en brouillon, fermée ou ne cible pas `main` ;
- le reviewer n'est pas dans l'allowlist versionnée ;
- le reviewer est l'auteur de la PR ;
- le rôle GitHub du reviewer n'est pas `write`, `maintain` ou `admin` ;
- aucune review `APPROVED` ne porte sur le head exact ;
- la review approuvée ne contient pas le challenge exact ;
- une review ultérieure du même reviewer demande des changements ou annule
  l'approbation ;
- les données sont incomplètes, dupliquées ou de forme inattendue.

Une réussite produit un document normalisé minimal contenant le dépôt, la PR,
la base, le head, le reviewer, l'identifiant de review, sa date et le challenge.
Ce document est une preuve de diagnostic ; le statut GitHub sur le head reste
l'autorité de fusion.

## Workflow privilégié

Le workflow est déclenché sur les événements qui peuvent changer le verdict :

- ouverture, réouverture, passage ready, synchronisation et modification de la
  base d'une PR ;
- commentaire littéral `/nexus-trusted-review` sur une PR, posté après une
  soumission, modification ou révocation de review.

Ses permissions sont minimales : `contents: read`, `pull-requests: read`,
`issues: write` pour le commentaire géré et `statuses: write` pour le head. Il
interdit la persistance de credentials dans un checkout et n'utilise aucun
secret de dépôt. Pour le commentaire de recalcul, le numéro de PR est borné et
le head est relu par API avant l'adaptateur. Les appels GitHub sont bornés,
paginés et échouent fermés.

Le workflow place `trusted-human-review` à `pending` sur le head attendu avant
toute première lecture de PR susceptible d'échouer, puis à `success` ou
`failure` avec une description non sensible. Il n'utilise jamais le nom d'un
job du workflow PR pour satisfaire ce contexte.

L'adaptateur valide le dépôt contre sa configuration locale avant toute
écriture. Il collecte deux snapshots successifs des reviews et permissions,
réévalue le second, puis relit encore la base et le head avant toute réussite.

## Erreurs et révocation

Les erreurs d'API, dépassements de pagination, réponses ambiguës et permissions
insuffisantes donnent `failure`, jamais `success`. Une synchronisation de head
replace immédiatement le nouveau SHA à `pending`. Une erreur après la tentative
initiale de `pending` tente aussi un statut `failure`, afin qu'un succès ancien
ne reste pas l'état le plus récent. Une review `CHANGES_REQUESTED` ou
`DISMISSED` invalide le statut correspondant.

La suppression future d'un reviewer de l'allowlist invalide les recalculs. Les
statuts historiques restent visibles dans GitHub mais ne peuvent satisfaire une
PR dont le head ou le challenge diffère.

## Tests exigés

Le développement suit RED → GREEN → REFACTOR. Les tests couvrent au minimum :

- sérialisation et digest canoniques ;
- approbation exacte par `abenrhouma` ;
- auteur auto-approbateur ;
- reviewer sans rôle suffisant ;
- review sur ancien head ;
- challenge absent, altéré ou d'une autre PR ;
- changements demandés ou review révoquée après approbation ;
- résultats paginés et données malformées ;
- révocation de review ou de permission entre les deux snapshots ;
- refus d'un dépôt non configuré avant toute écriture de statut ;
- permissions et événements du workflow ;
- absence de checkout du head et d'exécution de code PR ;
- politique versionnée, CODEOWNERS et readback normalisé ;
- test de non-régression de la CI locale complète.

## Livraison et preuve

Le lot produit :

- la configuration des reviewers autorisés ;
- le vérificateur pur et ses tests ;
- le workflow privilégié ;
- CODEOWNERS ;
- la politique de protection cible et ses tests ;
- un ADR de frontière de confiance ;
- un rapport `docs/reports/lot_41v_*.md`.

La PR n'est fusionnable qu'après :

- CI locale exhaustive verte ;
- checks GitHub du head exact verts ;
- zéro fil non résolu ;
- review formelle `APPROVED` de `abenrhouma` sur le head final ;
- readback de cette review vérifiant l'identité, le rôle et le commit exact.

Après fusion, le run `push` du SHA de `main` doit être vert. L'outil de
protection applique ensuite la politique cible et en relit tous les champs.

## Lots suivants

LOT41V ne préjuge pas les décisions suivantes :

1. LOT41A porte l'autorisation pure du périmètre `nexus-validation-1` et utilise
   la frontière GitHub désormais autoritaire.
2. LOT42 introduit les attestations indépendantes `quality → gate → review`,
   liées au contenu, au scope et aux items remis.
3. LOT43/43A portent l'évaluation exhaustive et sa seconde autorisation.
4. LOT44 à LOT46 portent observabilité, exploitation, sauvegarde/restauration,
   supply chain, grants et rollback sur l'infrastructure cible.
5. LOT47 reste une décision humaine finale de go-live et ne peut être produite
   par un agent.
