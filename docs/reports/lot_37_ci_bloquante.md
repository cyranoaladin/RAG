# LOT 37 — CI bloquante et validation exécutable

## Périmètre

- branche : `lot-37-ci-bloquante` ;
- correction de la topologie CI locale, porte `make full-regression`, E2E
  explicitement read-only, workflow GitHub, alignement outillage `rag-engine` ;
- déplacement par `git mv` de `MANIFEST_LOT28.md` et `MANIFEST_LOT29.md` vers
  `docs/reports/` ;
- aucune modification de contrat, de verrou de gouvernance, de logique métier,
  de schéma SQL ou de déploiement.

Extension autorisée par l’utilisateur : fixtures hermétiques dans les trois
racines de tests et marquage `network` des deux modules pgvector.

## Décisions

1. `full-regression` ne prépare aucun environnement et force `PIP_NO_INDEX`
   ainsi que `NPM_CONFIG_OFFLINE`. La préparation des venv et de `node_modules`
   est explicite et distincte dans la CI ; une dépendance absente échoue
   fermement.
2. Les tests pgvector existants sont marqués `network`, non conteneurisés. Ils
   sont comptés et désélectionnés par défaut. Les tests d’intégration sans
   dépendance externe restent inclus.
3. Le fixture autouse interdit les sockets IPv4/IPv6 hors marqueurs `network`
   et `e2e`. Les sockets Unix locales indispensables à `TestClient` restent
   possibles : elles ne constituent pas un accès réseau.
4. L’E2E reçoit exclusivement un jeton élève explicite. Il exerce les seules
   routes API de lecture autorisées et son routeur Playwright bloque toute autre
   méthode ou route ; aucune valeur de production, IP ou SSH n’est codée.
5. Le contrôle « zombies et doublons » est rendu statique afin de respecter
   l’hermétisme : artefacts runtime suivis par Git et `container_name` dupliqués
   sont détectés sans lire l’état d’une machine.
6. `.gitignore` contenait déjà `__pycache__/` et `.mypy_cache/` ; aucun diff
   documentaire artificiel n’a été ajouté pour une règle déjà satisfaite.

## Preuves d’exécution

### Avant modification

- `python -m pytest -q` à la racine : 77 erreurs de collecte, car pytest
  parcourait les services sans leurs environnements dédiés.
- les tests de topologie CI échouaient : sentinelle absente et
  `scripts/audit/rag-pr-audit.sh` relançait `scripts/ci-local.sh`.
- le test de politique E2E échouait car le module de liste blanche était absent.

### Après modification

- `make full-regression` : `FULL REGRESSION — ALL PASS`, `21/21 étapes
  passées`, `Hors périmètre explicite : network=8, e2e=0`.
- `bash scripts/ci-local.sh` : `CI LOCAL — SUMMARY`, 9 cibles passées,
  0 échec (`packages/contracts`, `services/rag-pedago`,
  `services/rag-engine`, `services/cockpit`, `governance-locks`,
  `taxonomy-validation`, `source-evidence-check`, `governance-guard-tests`,
  `ci-failsafe-tests`).
- `python -m pytest -q` à la racine : 4 tests passés ; seule la suite smoke
  racine est collectée.
- `bash scripts/check-governance-locks.sh` : `OK: all governance locks match
  baseline (18 keys verified)`.
- `bash scripts/tests/test-governance-locks.sh` : 16 tests passés, 0 échec.
- `detect-secrets scan -n` sur les 40 fichiers modifiés/non suivis du lot :
  aucun secret détecté.

## Métriques

| Indicateur | Avant | Après |
| --- | ---: | ---: |
| Commande racine de régression | 0 | 1 (`make full-regression`) |
| Tests racine collectés | tous les services, 77 erreurs | smoke tests uniquement |
| Tests pgvector dans la porte hermétique | non déclarés | 2 modules `network`, comptés et exclus |
| Appels SSH dans la régression | 1 contrôle production | 0 |
| Artefacts de lot à la racine | 2 | 0 |

## Protection de `main` à appliquer par un humain GitHub

Dans **Settings → Branches → Add branch protection rule**, cibler `main`, puis :

1. cocher **Require a pull request before merging**, avec au moins une
   approbation et rejet des approbations obsolètes après nouveau push ;
2. cocher **Require status checks to pass before merging** et sélectionner :
   `packages/contracts`, `services/rag-pedago`, `services/rag-engine`,
   `services/cockpit`, `governance locks guard`, `repository hygiene` et
   `full regression` ;
3. cocher **Require branches to be up to date before merging** ;
4. décocher **Allow force pushes** et **Allow deletions** ;
5. ne pas inclure l’E2E production read-only dans les checks requis ;
6. sauvegarder la règle et vérifier avec une PR de test que les sept checks
   sont obligatoires.

## Limites restantes explicites

- L’E2E production read-only ne valide ni ingestion, ni revue, ni promotion de
  statut, ni migration. Un environnement de recette iso-production demeure
  nécessaire, notamment pour les lots 36, 42 et 43.
- `main` ne peut pas être protégée par un changement de dépôt : l’application
  de la règle GitHub ci-dessus reste une action humaine.
- Les tests `network` ne sont pas une validation pgvector dans cette porte ;
  ils doivent être exécutés dans une recette explicitement provisionnée.

## Dettes créées

Aucune dette technique créée par ce lot. Les limites de recette sont tracées
ci-dessus comme contraintes opérationnelles existantes.
