# Plan de cloture go-live

> **Fichier derive.** Regenere par
> `scripts/go_live/check_go_live_readiness.py`. Il ordonne ce qui reste ;
> il n autorise rien. Le seul garde est `--assert-ready`.

`go_live_ready=false`
 — phases fermees : 0 sur 5

## Cinq niveaux, souvent confondus

Un contenu qui figure dans une matrice n est pas pour autant servi.

| Niveau | Mesure | Valeur |
| --- | --- | --- |
| contenu promu | ensemble promu canonique | 319 |
| contenu candidat a la servabilite | matrice de servabilite, applied=false | 2301 |
| contenu ingere | base pgvector d un environnement identifie | non mesurable depuis le depot |
| contenu exploitable par recherche | contrat de retrieval sur un service identifie | non mesurable depuis le depot |
| contenu reellement servi en production | production, hors de portee de ce lot | non mesurable depuis le depot |

Trois de ces cinq niveaux **ne se mesurent pas depuis le depot**. Ils
exigent une base et un service identifies. Rendre zero pour eux serait
une fausse assurance, et c est pourquoi ils sont declares non mesurables
plutot que remplis.

## Ordre impose

| Phase | Etat | Bloqueurs ouverts | Bloquee par | Qui agit |
| --- | --- | --- | --- | --- |
| `P1_PRE_RELEASE` Fermer les bloqueurs de pre-release | actionnable | PII_UNDECIDED, CURRENTNESS_POLICY_APPLIED | — | ENGINEERING, HUMAN_REVIEWER |
| `P2_DEPOT` Vider le depot de ses PR bloquantes | actionnable | OPEN_PRS_BLOCKING | — | HUMAN_DECISION |
| `P3_OCTETS` Disposer des octets des contenus servables | en attente | — | P1_PRE_RELEASE | — |
| `P4_QUALIFICATION` Fermer les gates de qualification | en attente | GO_LIVE_QUALIFICATION_BLOCKERS | P1_PRE_RELEASE, P2_DEPOT | MIXED |
| `P5_DEPLOIEMENT` Deployer, apres et seulement apres | en attente | — | P4_QUALIFICATION | — |

Une phase ne s ouvre pas tant que celles dont elle depend restent
ouvertes. Qualifier un staging avant d avoir les octets, ou deployer
avant d avoir qualifie, oblige a tout refaire.

## Conditions de fermeture

### P1_PRE_RELEASE — Fermer les bloqueurs de pre-release

Gate : `pre_release_blockers == 0`

### P2_DEPOT — Vider le depot de ses PR bloquantes

Gate : `open_prs_blocking == 0`

### P3_OCTETS — Disposer des octets des contenus servables

Gate : `non_pdf_servable_reacquired == non_pdf_servable_total`

### P4_QUALIFICATION — Fermer les gates de qualification

Gate : `go_live_qualification_blockers == 0`

### P5_DEPLOIEMENT — Deployer, apres et seulement apres

Gate : `--assert-ready rend 0`
