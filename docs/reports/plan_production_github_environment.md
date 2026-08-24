# Plan opérateur exact — GitHub Environment `production`

## Statut observé

Ce document prépare le geste repo-admin sans l'exécuter. L'Environment
`production` était absent lors de l'audit et aucune mutation GitHub n'a été
faite dans ce lot.

Preuve read-only nettoyée :
`docs/reports/github_environment_read_only_observation_20260824.json`, observée
à `2026-08-24T06:53:53Z`. L'API retourne zéro Environment ; l'identité
`abenrhouma` a l'id `67140603` et la permission dépôt `write`.

```text
PRODUCTION_GITHUB_ENVIRONMENT_EXISTS=false
PRODUCTION_GITHUB_ENVIRONMENT_PROVISIONED=false
HUMAN_ADMIN_ACTION_REQUIRED=true
```

Les workflows `_produce-h2-evidence.yml` et `promote.yml` nomment déjà
`environment: production`. Tant que l'Environment n'existe pas, cette référence
ne fournit pas la protection opérateur exigée.

## Valeurs à appliquer

```text
ENVIRONMENT_NAME=production
REQUIRED_REVIEWER=abenrhouma
REQUIRED_REVIEWER_USER_ID=67140603
DEPLOYMENT_BRANCH_POLICY=main-only
PREVENT_SELF_REVIEW=true
ADMIN_BYPASS=false
WAIT_TIMER_MINUTES=0
ENVIRONMENT_SECRETS=0
```

Ces valeurs sont exactes pour cette release : `abenrhouma` est l'identité de
revue humaine déjà établie ; le déploiement ne peut partir que de `main` ;
l'auteur ne peut approuver son propre déploiement ; aucun administrateur ne
peut contourner le gate ; aucun délai supplémentaire n'est requis ; aucune clé
ou autre secret long-vécu n'entre dans l'Environment.

La clé privée de signature readiness ne va jamais dans GitHub, Git, CI, le
serveur ou les logs. Les workflows constatent et vérifient ; ils ne signent pas.

## Geste UI minimal

Dans `Settings → Environments` :

1. créer l'Environment nommé exactement `production` ;
2. ajouter `abenrhouma` (user id `67140603`) comme unique required reviewer ;
3. activer la prévention de l'auto-revue ;
4. désactiver tout bypass administrateur ;
5. limiter les deployment branches à `main` seulement ;
6. conserver le wait timer à `0` minute ;
7. ne créer aucun secret d'Environment.

Après sauvegarde, relire l'API/les réglages et comparer les sept valeurs
ci-dessus avant tout vrai run de promotion. Cette action est un HUMAN GATE et
reste non exécutée dans la PR contractuelle.
