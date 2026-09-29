---
paths:
  - "**/tests/**"
  - "scripts/tests/**"
  - "scripts/ci-local.sh"
  - ".github/workflows/ci.yml"
---

# Tests

- Univers de test : un compteur n'a de sens qu'avec son périmètre (service,
  commande, SHA). Ne jamais comparer le compteur d'un service à celui du dépôt.
- Un rouge n'est « préexistant » que s'il est reproduit sur le commit parent ;
  il se trace alors dans `docs/reports/*_dettes.md`.
- Test d'intégration Docker : jamais deux suites en parallèle (ports partagés) ;
  un module entier rouge d'un coup évoque ce conflit avant une régression.
- Le test hybride pgvector connu intermittent se vérifie par son périmètre puis
  se relance ; il ne se désactive pas.
- Un test de gouvernance ou de go-live teste d'abord le REFUS (fail-closed).
- Un nouveau fichier de `scripts/tests/` est collecté automatiquement par
  `pytest scripts/tests/` (CI `script-tests` et `ci-local.sh`) ; un script bash
  s'ajoute explicitement à `ci.yml` et à `ci-local.sh`.
- Venv hermétique par service ; ne jamais symlinker un paquet d'un venv à l'autre
  pour masquer un conflit de version.
