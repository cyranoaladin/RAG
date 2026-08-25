# GitHub Environment `production` — configuration appliquée

## Statut relu

La configuration réversible et sans secret a été appliquée via l'API GitHub,
puis relue le `2026-08-25T05:03:17Z`. La preuve nettoyée est
`docs/reports/evidence/github_production_environment_20260825.json`.

```text
PRODUCTION_GITHUB_ENVIRONMENT_EXISTS=true
PRODUCTION_GITHUB_ENVIRONMENT_PROVISIONED=true
HUMAN_ADMIN_ACTION_REQUIRED=false
```

## Valeurs effectives

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

La lecture live confirme une unique règle de branche `main`, le reviewer
`abenrhouma`, la prévention de l'auto-revue, le bypass administrateur
désactivé, aucun wait timer actif et zéro secret d'Environment.

La clé privée de signature readiness ne va jamais dans GitHub, Git, CI, le
serveur ou les logs. L'approval de déploiement reste une vraie action humaine
au moment de la promotion.
