# LOT 34 — Baseline CI stricte et intégration du cockpit

Date de validation : 29 juillet 2026.

## Révision testée

- Commit fonctionnel : `8343b71ee34f7296487401e557761b513babb94f`.
- Arbre Git archivé : `e60085f55e00b75229ba491e5699d537d82630bb`.
- Branche : `lot-34-baseline-ci`.
- Le présent rapport est commité séparément après la validation afin de ne pas
  rendre la preuve du SHA circulaire.

## Environnement

| Composant | Version réellement utilisée |
|---|---:|
| Python | `3.12.3` |
| Node.js | `22.22.0` |
| npm | `10.9.8` |

Le poste expose Node `22.21.0` par défaut. La CI a donc été exécutée avec
Node `22.22.0` injecté explicitement, conformément au fichier `.nvmrc` et au
minimum requis par React Router 8.3.

## Cycle RED → GREEN

La commande initiale était :

```bash
bash scripts/tests/test-ci-local-failsafe.sh
```

État RED observé avant l'implémentation : `8 passed, 8 failed`. Les huit
échecs correspondaient précisément à l'absence :

- de la fonction et du target `run_cockpit` ;
- du job GitHub Actions `jobs.cockpit` et de sa configuration Node/cache ;
- du fichier `.nvmrc` fixé à `22.22.0` ;
- du helper `require_node_2222`, donc du rejet de Node 22.21 et de
  l'acceptation de Node 22.22 ;
- de l'arrêt de `ci-local.sh` avant tout appel à npm avec une version Node
  incompatible.

État GREEN après implémentation : `16 passed, 0 failed`.

Les contrôles de contenu extraient réellement, par frontières syntaxiques, la
fonction shell `run_cockpit()` et le seul job YAML `cockpit`. Ils exigent dans
chacun `npm ci`, lint, les tests non interactifs, le build, l'audit complet,
l'audit de production et le clean build Git. L'audit complet est contrôlé par
une ligne exacte : l'audit `--omit=dev` ne peut donc pas créer de faux positif.

## Commandes de validation

Validation ciblée et statique :

```bash
bash scripts/tests/test-ci-local-failsafe.sh
bash -n scripts/lib/ci-common.sh scripts/ci-local.sh \
  scripts/tests/test-ci-local-failsafe.sh
git diff --check
python3 - <<'PY'
from pathlib import Path
import yaml

workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
assert "jobs" in workflow and "cockpit" in workflow["jobs"]
PY
```

Validation locale complète du commit fonctionnel :

```bash
/usr/bin/time -p npm exec --yes --package=node@22.22.0 -- \
  bash scripts/ci-local.sh
```

Résultat : code de sortie `0`, `545.88 s` réelles, `460.33 s` utilisateur et
`57.98 s` système.

## Résultat par target

| Target CI locale | Résultat | Preuve principale |
|---|---|---|
| `packages/contracts` | PASS | import du contrat canonique réussi |
| `services/rag-pedago` | PASS | ruff vert, mypy vert sur 73 fichiers, `1151 passed` en `277.24 s` |
| `services/rag-engine` | PASS | installation, lint, typecheck et `603 passed`, `15 deselected` |
| `services/cockpit` | PASS | lint, 3 fichiers de tests et `8 passed`, build de production, deux audits à zéro |
| `governance-locks` | PASS | 18 clés identiques à la baseline |
| `taxonomy-validation` | PASS | 57 taxonomies, 0 erreur, 486 notions et 174 sous-notions |
| `source-evidence-check` | PASS | 11 verdicts couvrent la configuration courante |
| `governance-guard-tests` | PASS | `16 passed, 0 failed` |
| `ci-failsafe-tests` | PASS | `16 passed, 0 failed` |

Résumé produit par le script : `9 passed, 0 failed`.

## Preuves cockpit

Le target local et le job GitHub Actions exécutent, sans fallback :

```text
npm ci
npm run lint
npm test -- --run
npm run build
npm audit
npm audit --omit=dev
bash scripts/tests/test-cockpit-clean-build.sh
```

Résultats de la CI locale :

- `npm ci` : 510 paquets ajoutés, 511 paquets audités, 0 vulnérabilité ;
- tests : 3 fichiers, 8 tests réussis ;
- build : 1857 modules transformés, build Vite réussi ;
- `npm audit` complet : 0 vulnérabilité ;
- `npm audit --omit=dev` : 0 vulnérabilité ;
- clean build : concordance cockpit/Eduscol validée sur 20 sources, nouvelle
  installation `npm ci` depuis l'archive Git et nouveau build réussi.

Le clean build a utilisé `HEAD`, donc l'arbre Git
`e60085f55e00b75229ba491e5699d537d82630bb`, et non les fichiers non suivis du
poste.

## Workflow GitHub Actions

Le job `cockpit` utilise `actions/setup-node@v4` avec
`node-version-file: .nvmrc`, le cache npm et
`cache-dependency-path: services/cockpit/package-lock.json`. Il installe aussi
PyYAML `6.0.3`, requis par le contrôle de concordance du clean build.

Le workflow a été parsé statiquement et son job borné a été couvert par les
tests locaux. **GitHub Actions n'a pas été exécuté dans cette validation** :
aucun résultat distant n'est revendiqué dans ce rapport.

## Écarts et absence d'exception

La CI locale n'accepte aucun échec préexistant, aucune vulnérabilité, aucun
fallback de build et aucune tolérance conditionnelle. Le garde-fou vérifie
Node avant npm ; un faux Node `22.21.0` est rejeté et un faux Node `22.22.0`
est accepté. Le test d'arrêt confirme qu'aucun exécutable npm n'est appelé
après le rejet.

Trois avertissements non masqués sont émis par la suite existante de
`rag-engine` : dépréciation de `crypt`, incohérence annoncée par `requests`
entre ses dépendances installées, et usage de `datetime.utcnow()` dans
`python-jose`. Ils n'ont entraîné ni exception, ni test ignoré supplémentaire,
ni clause d'acceptation dans la CI de ce lot.
