# ADR-0025 — Autorité de revue humaine GitHub

- Statut : Accepté
- Date : 2026-08-04
- Périmètre : revue indépendante, checks requis et protection de `main`
- S'appuie sur : ADR-0001, ADR-0010, ADR-0021 et ADR-0024

## Contexte

Les preuves locales de gouvernance sont reproductibles par leur auteur. Un
fichier YAML, un digest ou un commentaire textuel ne démontre ni l'identité
d'un reviewer, ni son habilitation, ni une décision portant sur le dernier SHA.
Le runtime a donc été fermé par LOT41U, mais aucune transition ultérieure ne
peut devenir autoritaire sans une décision humaine indépendante vérifiable.

Le reviewer initial est le compte GitHub `abenrhouma`. Il possède le rôle
`write` sur `cyranoaladin/RAG`. Cette habilitation ne constitue pas une
approbation : la décision doit être effectuée personnellement dans une review
GitHub formelle et porter sur le head exact de la pull request.

## Décision

GitHub devient l'autorité d'identité, de review et de fusion. La protection
native exige une approbation du Code Owner `@abenrhouma`, rejette les reviews
périmées et impose l'approbation du dernier push. Un vérificateur en lecture
seule calcule en plus un challenge canonique et relit la pull request, toutes
ses reviews et la permission du reviewer. Son verdict est un snapshot de preuve
à recalculer au moment de l'usage, jamais un statut persistant de fusion.

Une décision positive exige simultanément :

- une PR ouverte, non brouillon, interne au dépôt et ciblant `main` ;
- `abenrhouma` distinct de l'auteur et toujours habilité `write`, `maintain` ou
  `admin` ;
- une review `APPROVED` dont `commit_id` égale le head courant ;
- le challenge exact sur une ligne autonome du corps de cette review ;
- aucune décision ultérieure `CHANGES_REQUESTED` ou `DISMISSED` du même
  reviewer autorisé ;
- une collecte complète, bornée et non ambiguë ;
- un second readback du head après l'évaluation.

La protection cible exige aussi une approbation, la review du Code Owner, le
rejet des reviews périmées et l'approbation du dernier push. `.github/CODEOWNERS`
désigne `@abenrhouma` pour tout le dépôt.

Les six checks CI requis sont associés explicitement à l'application GitHub
Actions `15368`. Les `contexts` non associés à une application sont interdits
par la politique versionnée. Aucun statut `trusted-human-review` n'est requis :
l'identifiant d'application GitHub Actions est partagé entre les workflows et
ne permet pas de distinguer le vérificateur de code exécuté par une PR. La
décision humaine de fusion repose donc sur la protection native Code Owner,
pas sur un contexte Actions usurpable.

`required_status_checks.strict = true` rend toute PR non fusionnable dès que
`main` avance. La branche de tête doit alors intégrer la nouvelle base, ce qui
change son head, invalide la review native antérieure et impose un nouveau
challenge. Le workflow n'a donc pas besoin d'un trigger `push` qui devrait
énumérer toutes les PR ouvertes.

## Challenge canonique

Le challenge a la forme :

```text
NEXUS-TRUSTED-REVIEW-V1:<sha256>
```

Le SHA-256 couvre un JSON UTF-8 à clés triées et séparateurs compacts contenant
exactement le dépôt, le numéro de PR, la branche et le SHA de base, le SHA de
head, l'auteur, le reviewer et la version du protocole. Le challenge n'est pas
un secret. Il lie l'acte GitHub authentifié à un état précis ; tout nouveau
commit le rend caduc.

## Sécurité du workflow de readback

Seuls `pull_request_target` et `issue_comment` peuvent déclencher le workflow
de diagnostic ; ils le chargent depuis la branche par défaut.
`pull_request_review` est interdit parce que son merge ref permettrait à la PR
de proposer le YAML qui reçoit les permissions d'écriture. `workflow_dispatch`
est interdit parce que son appelant peut choisir un `ref` différent de `main`.
Le checkout ultérieur de `main` ne protégerait pas les étapes du workflow
elles-mêmes.

Cette provenance n'est pas une hypothèse : le run bootstrap GitHub
`30864574764` a exécuté le YAML `pull_request_review` du merge ref alors que le
workflow et son script n'existaient pas dans `main`. La référence GitHub de cet
événement indique également `GITHUB_REF = refs/pull/<n>/merge`, contrairement à
`pull_request_target`, dont le contexte est la branche par défaut.

Ces triggers sont acceptés uniquement avec les contraintes suivantes :

- checkout explicite de `refs/heads/main` ;
- aucune exécution ni lecture du code du head de la PR ;
- actions GitHub épinglées par SHA ;
- credentials de checkout non persistés ;
- aucune utilisation de secret de dépôt ;
- aucune interpolation du titre, du corps, de la branche ou de l'auteur dans
  une commande ;
- permissions limitées à `contents: read` et `pull-requests: read` ;
- numéro de PR et SHA contrôlés avant l'appel de l'adaptateur ;
- pour `issue_comment`, commande littérale `/nexus-trusted-review`, PR exigée et
  base `main` vérifiée et head relu par API avant l'adaptateur ; le corps du
  commentaire ne devient jamais une commande shell ni une autorité ;
- pagination et temps d'appel bornés, sans shell dans l'adaptateur GitHub.

L'adaptateur n'expose que le mode `--check`, strictement en lecture. Avant une
réussite, il relit une seconde fois les reviews et les permissions, réévalue ce
snapshot final, puis vérifie encore la base et le head. Aucune permission
`issues: write` ou `statuses: write` n'est accordée, et aucun statut ou
commentaire n'est publié par l'automatisation.

## Révocation

Une synchronisation ou un retargeting de la PR produit un nouveau calcul. Une
review ancienne, une révocation, une demande de changements, une perte de
permission, une modification du challenge ou le retrait de l'allowlist invalide
le prochain readback. Après une action de review, un commentaire
`/nexus-trusted-review` déclenche ce readback ponctuel ; ce commentaire et le
check Actions résultant ne sont jamais une autorité. GitHub protège la fusion
par l'état natif de la review Code Owner. Toute future autorisation métier doit
relancer `--check` et ne peut réutiliser un snapshot antérieur.

## Transition en deux temps

LOT41V est fusionné sous la politique antérieure, car le workflow de readback
n'existe pas encore sur `main`. Avant cette fusion, le head final doit néanmoins
recevoir une review formelle de `abenrhouma`, contrôlée en lecture par
l'adaptateur local `--check` avec le head distant exact. Ce readback externe ne
publie aucun statut et sa sortie normalisée est consignée dans la conversation
de la PR bootstrap.

Après fusion et CI `push` verte, le workflow read-only est déclenché sur une PR
témoin afin de vérifier son chargement depuis `main`. La politique cible exige
alors les six checks CI et les gardes natives de review, puis fait l'objet d'un
readback complet. Aucun producteur de statut supplémentaire n'est nécessaire.

## Alternatives rejetées

- Une preuve locale signée par l'auteur est rejetée : elle reste auto-déclarée.
- Un commentaire `APPROVE` est rejeté : il n'est ni une review GitHub formelle,
  ni lié au dernier commit.
- Un workflow `pull_request` exécutant le head est rejeté : son vérificateur
  serait modifiable par le contributeur.
- Un statut Actions dédié à la review est rejeté comme autorité de fusion :
  `app_id=15368` identifie GitHub Actions dans son ensemble, pas un workflow
  unique, et une PR pourrait demander le même contexte.
- L'usurpation de la décision humaine par un agent est interdite : l'action
  personnelle de `abenrhouma` est une dépendance irréductible.

## Conséquences et limites

LOT41V installe une frontière d'autorité réutilisable, mais n'autorise aucun
contenu ni aucune capacité métier. LOT41A doit encore autoriser un scope précis,
LOT42 doit fournir les attestations indépendantes `quality → gate → review`, et
les revues pédagogiques et opérationnelles restent requises.

Le verdict demeure `GO_LIVE: NO_GO`. La perte ou la compromission du compte
reviewer exige son retrait de l'allowlist, de CODEOWNERS et de l'accès au dépôt,
puis une nouvelle décision d'architecture.

## Retour arrière

Le retour arrière sûr conserve `main` protégé par les six checks et les gardes
natives de review, puis désactive éventuellement le workflow read-only. Aucun
contexte `trusted-human-review` n'est requis et ne doit être ajouté. Réintroduire
des approbations locales auto-déclarées n'est pas un rollback acceptable.
