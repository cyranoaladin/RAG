# LOT41T — Durcissement fail-closed des preuves de gouvernance

## Verdict

**LOT41T_LOCAL_CI_GREEN_AWAITING_FINAL_HEAD_PROOF**

LOT41T ferme les six constats techniques historiques confirmés sans ouvrir de
capacité. Les diagnostics locaux ne peuvent plus transformer un fichier YAML,
un digest recalculable ou des états auto-déclarés en autorité humaine ou en
autorisation de publication. La CI locale source est verte, mais le présent
rapport ne préjuge ni les checks GitHub du futur head publié, ni ceux du commit
qui ajoute ce rapport.

**GO_LIVE: NO_GO**

Le projet complet n'est pas prêt au go-live : LOT41A doit encore fournir un
readback GitHub authentifié et LOT42 une chaîne d'attestations autoritaire liée
au contenu et au scope, avant la revue substantielle du corpus et les portes de
déploiement restantes.

## Périmètre

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-02 |
| Baseline `main` | `4bf51c762aee8d7c1561d7c30a13f2fdf5af42c6` |
| Branche | `lot-41t-governance-proof` |
| Head source vérifié | `22e0a807a7dca9125f3a05dd9bc8c7b448addba4` |
| Services modifiés | `services/rag-pedago` et documentation |
| Contrats, runtime déployé et données | aucun changement ; diagnostics locaux dormants durcis |
| Verrous de gouvernance | aucun changement, 18/18 conformes |

## Constats corrigés

Les quatre constats de la PR #81 et les deux constats de la PR #82 sont traités
comme suit :

1. une approbation décrite localement, depuis YAML ou en mémoire, échoue avec
   `approval.trusted_channel_unavailable` même si tous ses champs concordent ;
2. un package de publication ne peut plus substituer un autre scope : l'absence
   d'attestation externe liée au scope échoue avec
   `package.scope_attestation_unavailable` ;
3. les chaînes locales `passed/passed/reviewed` n'ont plus valeur de preuve :
   l'absence d'attestations autoritaires échoue avec
   `package.trusted_attestations_unavailable` ;
4. `39 notions` est présenté comme la cardinalité du scope taxonomique, jamais
   comme une couverture pédagogique ;
5. une revendication golden locale complète rend désormais
   `HUMAN_REVIEW_PENDING` avec
   `human_review.trusted_channel_unavailable`, jamais
   `HUMAN_REVIEW_APPROVED` ;
6. l'entrypoint direct du CLI golden transmet `sys.argv[1:]` et refuse un
   argument inconnu avec le code `2`.

Le manifeste golden canonique est revenu à un état `pending` propre. Le paquet
historique reste conservé avec un bandeau explicite de revendication non
authentifiée. Les rapports LOT38 et LOT39bis comportent des errata additifs :
les preuves historiques ne sont ni effacées ni présentées comme autoritaires.

## Frontière de confiance

LOT41T choisit l'échec fermé. Un SHA-256 prouve l'intégrité des octets, pas
l'identité ni l'autorité de leur auteur. Aucun callback fourni par l'appelant,
aucune clé auto-déclarée et aucun accès réseau ad hoc n'ont été ajoutés.

LOT41A devra vérifier hors de ce diagnostic une review GitHub formelle sur le
dépôt, la PR, la base et le head exacts, émise par un reviewer autorisé distinct
de l'auteur et liée à un challenge canonique. LOT42 devra lier les attestations
indépendantes `quality`, `gate` et `review` au même digest, au même scope et aux
mêmes items que le manifeste effectivement publié, puis vérifier l'autorité et
la révocation de la clé de signature. Tant que ces autorités n'existent pas,
l'absence de preuve reste un refus explicite.

## Cycles TDD et vérifications ciblées

| Cycle | RED observé | GREEN final |
| --- | --- | --- |
| Approbation locale et package auto-déclaré | 13 échecs, 173 réussites | 186 réussites |
| Golden local et arguments CLI | 8 échecs, 272 réussites | 280 réussites |
| Libellé de cardinalité et errata | 6 échecs, 26 réussites | 32 réussites |
| Suites golden et politique combinées | — | 312 réussites |

Les vérifications fraîches sur le head source ont également produit :

- Ruff : tous les contrôles réussis ;
- mypy : 76 fichiers sans erreur ;
- suite complète `rag-pedago` : 1 756 tests réussis ;
- audit de politique pilote : code `0`, état `DORMANT` ;
- audit golden canonique : code `3`, état `HUMAN_REVIEW_PENDING` ;
- appel CLI golden avec argument inconnu : code `2`, aucun stdout ;
- `git diff --check origin/main...HEAD` : réussi ;
- fichiers de verrous et baseline : aucun diff, 18/18 conformes.

Les trois volets d'implémentation ont reçu une revue indépendante avec verdict
**APPROVE**, sans constat restant dans leur périmètre.

## CI locale source

La CI racine exhaustive a été exécutée sur le head source exact
`22e0a807a7dca9125f3a05dd9bc8c7b448addba4`, avec Python 3.12.3 et Node
22.23.1. Elle a produit **13 réussites, 0 échec** : contrats, trois services,
build Cockpit, intégration PostgreSQL réelle, hygiène, topologie CI, protection
de `main`, gouvernance, taxonomie, preuves source et tests fail-safe. Ces
derniers comptent eux-mêmes 50 réussites et 0 échec.

Le journal éphémère non versionné `lot41t-source-ci.Lew4Ul.log`, conservé hors
du dépôt pendant la livraison, a pour SHA-256
`1a4a3573c888aba21e74f31bb000be4c2b85c850f33e9a441f2d55d0034e304d`.
Il certifie uniquement le head source qu'il nomme. Une seconde CI exhaustive
sera exécutée sur le head final incluant ce rapport, sans modification
postérieure ; sa preuve restera externe et sera publiée dans la PR.

## Signalement GitGuardian historique

Le signalement de la PR #81 vise
`services/rag-pedago/tests/fixtures/pilot_validation/github_approval.valid.yml`.
La valeur détectée est exactement le SHA-256 du fixture
`authorization.valid.yml` :

```text
5c42d84878e0338e80e8fdfc2ceb5488c16bbfaf72bedb4507e4b2fc79520ddc
```

Le calcul comparatif a réussi et Gitleaks 8.21.2 n'a trouvé aucune fuite sur la
plage source figée `origin/main..22e0a807a7dca9125f3a05dd9bc8c7b448addba4`,
après cinq commits analysés. Le head final incluant ce rapport sera scanné
séparément hors du dépôt. Aucune allowlist globale ni affaiblissement du
détecteur n'est introduit. Après fusion, une réponse documentera cette preuve
sur la PR #81 ; le classement de l'incident comme faux positif demeure une
action du tableau de bord GitGuardian et ne sera pas présenté comme résolu par
le code.

## Commits antérieurs au présent rapport

| SHA | Objet |
| --- | --- |
| `a64cc0c` | spécification du durcissement fail-closed |
| `5924dfa` | plan d'implémentation et de livraison |
| `00bb67c` | fermeture des preuves de transition locales |
| `f383527` | reclassification de la revue golden non authentifiée |
| `22e0a80` | correction des preuves et métriques historiques |

## Décision de livraison

Le lot peut passer à la preuve du head final puis à une PR dédiée. La fusion
reste conditionnée aux six checks protégés issus du seul événement
`pull_request`, aux contrôles complémentaires, à l'absence de fil non résolu et
à la protection de `main`. Le SHA de squash distinct devra ensuite être validé
par le run `push` de `main`.

Après fusion et vérification, les six anciens fils techniques des PR #81 et
#82 recevront une réponse liée au correctif puis seront résolus avec relecture
GraphQL. Le commentaire GitGuardian recevra séparément la preuve du faux
positif. Ces clôtures historiques ne changent pas le verdict global
`GO_LIVE: NO_GO`.
