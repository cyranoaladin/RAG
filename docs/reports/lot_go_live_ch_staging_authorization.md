# Lot CH — Autorisation SSH de staging, par PR

- Lot : `LOT_GO_LIVE_FINAL_CH_STAGING_AUTHORIZATION_PR`
- Branche : `go-live/staging-ssh-authorization`
- Décision : `GO_LIVE_CH_STAGING_AUTHORIZATION_PR_OPEN`
- Aucune connexion n'a été ouverte. Aucun compteur modifié, aucun blocker fermé.

**L'approbation de la PR de ce lot par abenrhouma vaut autorisation SSH_STAGING_AUTHORIZED sur nexus-prod, uniquement pour
exécuter un staging cloisonné, sans current switch, sans exposition publique non contrôlée, sans écriture DB production,
sans ingestion production.**

## L'autorisation est un fichier vérifiable, pas une phrase

`docs/reports/go_live/authorizations/staging_ssh_authorization.json` porte le périmètre, les interdits, les conditions
d'arrêt, la preuve attendue, et **l'empreinte du plan d'exécution** qu'elle autorise.
`scripts/go_live/check_staging_authorization.py` est lancé avant toute commande `ssh` et refuse si :

- le fichier est absent, illisible, ou d'un autre type ;
- il n'est pas **fusionné à l'identique sur `origin/main`** — une branche locale n'autorise rien (état actuel : refus) ;
- le plan d'exécution a changé depuis l'autorisation ;
- le périmètre s'élargit : autre hôte, autre projet Compose, liaison autre que `127.0.0.1`, accès autre que le tunnel
  SSH, conteneur pgvector autre que `nexus-staging-pgvector-1`, image non figée par digest ;
- une seule des 15 interdictions manque (current switch, lecture ou écriture d'une base de production, ingestion de
  production, exposition publique, Nginx, DNS, certificats, redémarrage d'un service de production, lecture d'un secret de
  production, `docker prune`, `--remove-orphans`, suppression de volume hors projet, OAuth, rclone) ;
- l'approbateur n'est pas `abenrhouma`, l'autorisation n'est pas à usage unique, ou elle est déjà consommée.

## Périmètre autorisé

Hôte `nexus-prod` ; projet Compose `nexus-staging` ; ports loopback 18001 (API), 15435 (pgvector), 19191 (Prometheus) ;
volumes `nexus-staging_*` ; répertoire `/srv/nexus-staging` ; accès par tunnel SSH ; Cockpit sur le poste de travail ;
`PGVECTOR_CONTAINER=nexus-staging-pgvector-1` obligatoire ; image `ingestor` figée par digest, `--no-build` ensuite.
Index de staging : ingestion gouvernée de la release multilevel scellée (11 PDF officiels, 353 chunks). Lot de corpus
servable produit par l'outil gouverné `servable_corpus_cli`, empreinte mesurée. Charge : mesure **séquentielle** C0
seulement ; le profil complet C1 exigera une autre PR.

Commandes exactes, healthchecks, smoke tests, rollback, photographie préalable et les trois `diff` de non-atteinte :
`docs/runbooks/staging_externe_nexus_prod_cloisonne_EXECUTION_PLAN.md`, lié par empreinte.

## Après approbation et merge — lot CI

`check_staging_authorization.py` → phases 0 à 8 du plan, avec arrêt à la première des 10 conditions d'arrêt → preuve
`external_staging_proof.json` en mode A → `STAGING_EXTERNE` fermé **seulement** si la preuve est réelle → mesure C0.
À la fin, l'autorisation est marquée `consumed: true` par PR : elle ne sert qu'une fois.

## Si la PR est refusée

Aucune connexion. STAGING_EXTERNE reste ouvert ; la voie B (hôte séparé) reste possible.

## Limite déclarée

Même machine que la production : la preuve dira `production_cloisonnee`. Risque principal : contention CPU/RAM avec la
production pendant l'inférence — seuils d'arrêt en phase 0, durée courte, limites Compose.
