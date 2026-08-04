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

GitHub devient l'autorité d'identité et de review. Un workflow privilégié,
chargé exclusivement depuis `main`, calcule un challenge canonique, relit la
pull request, toutes ses reviews et la permission du reviewer, puis publie le
statut `trusted-human-review` sur le head attendu.

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

Les sept checks requis sont associés explicitement à l'application GitHub
Actions `15368`. Les `contexts` non associés à une application sont interdits
par la politique versionnée. Un statut homonyme créé par un autre producteur
ne satisfait donc pas le readback gouverné.

`required_status_checks.strict = true` rend toute PR non fusionnable dès que
`main` avance. La branche de tête doit alors intégrer la nouvelle base, ce qui
change son head, invalide le statut précédent et impose un nouveau challenge.
Le workflow n'a donc pas besoin d'un trigger `push` qui devrait énumérer et
modifier toutes les PR ouvertes.

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

## Sécurité du workflow privilégié

Seuls `pull_request_target` et `issue_comment` peuvent déclencher le workflow
privilégié ; ils le chargent depuis la branche par défaut.
`pull_request_review` est interdit parce que son merge ref permettrait à la PR
de proposer le YAML qui reçoit les permissions d'écriture. `workflow_dispatch`
est interdit parce que son appelant peut choisir un `ref` différent de `main`.
Le checkout ultérieur de `main` ne protégerait pas les étapes du workflow
elles-mêmes.

Ces triggers sont acceptés uniquement avec les contraintes suivantes :

- checkout explicite de `refs/heads/main` ;
- aucune exécution ni lecture du code du head de la PR ;
- actions GitHub épinglées par SHA ;
- credentials de checkout non persistés ;
- aucune utilisation de secret de dépôt ;
- aucune interpolation du titre, du corps, de la branche ou de l'auteur dans
  une commande ;
- permissions limitées à `contents: read`, `pull-requests: read`,
  `issues: write` et `statuses: write` ;
- numéro de PR et SHA contrôlés avant l'appel de l'adaptateur ;
- pour `issue_comment`, commande littérale `/nexus-trusted-review`, PR exigée et
  head relu par API ; le corps du commentaire ne devient jamais une commande
  shell ni une autorité ;
- pagination et temps d'appel bornés, sans shell dans l'adaptateur GitHub.

Le mode `--check` est strictement en lecture. Le mode `--publish` pose d'abord
le statut à `pending` sur le head attendu, avant toute première lecture de PR,
puis publie `success` uniquement après une décision pure positive. Toute erreur
ou course tente de remplacer ce statut par `failure` et échoue fermée.
Avant une réussite, l'adaptateur relit une seconde fois les reviews et les
permissions, réévalue ce snapshot final, puis vérifie encore la base et le head.

## Révocation

Une synchronisation ou un retargeting de la PR produit un nouveau calcul. Une
review ancienne, une révocation, une demande de changements, une perte de
permission ou le retrait de l'allowlist invalide le prochain calcul. Après une
action de review, un commentaire `/nexus-trusted-review` déclenche le readback ;
ce commentaire n'est jamais une autorité. Le commentaire géré par le workflow
rend seulement le challenge visible.

## Transition en deux temps

LOT41V est fusionné sous la politique antérieure, car le workflow privilégié
n'existe pas encore sur `main`. Avant cette fusion, le head final doit néanmoins
recevoir une review formelle de `abenrhouma`, contrôlée en lecture par
l'adaptateur.

Après fusion et CI `push` verte, le workflow est déclenché sur une PR témoin.
La politique cible n'est appliquée qu'après un statut GitHub Actions observé et
un readback complet de la protection. Cette séquence évite de rendre `main`
impossible à mettre à jour avant l'installation de son producteur de statut.

## Alternatives rejetées

- Une preuve locale signée par l'auteur est rejetée : elle reste auto-déclarée.
- Un commentaire `APPROVE` est rejeté : il n'est ni une review GitHub formelle,
  ni lié au dernier commit.
- Un workflow `pull_request` exécutant le head est rejeté : son vérificateur
  serait modifiable par le contributeur.
- Un contexte requis sans `app_id` est rejeté : un producteur différent
  pourrait publier le même nom.
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

Le retour arrière sûr conserve `main` protégé et retire d'abord le check
`trusted-human-review` de la politique live avant de désactiver son workflow.
Retirer le workflow en laissant son check obligatoire bloquerait toutes les PR.
Réintroduire des approbations locales auto-déclarées n'est pas un rollback
acceptable.
