# LOT 34 — Baseline CI stricte et intégration du cockpit

Date de validation : 29 juillet 2026.

## Révision testée

- Commit fonctionnel : `0a1a8d557ad90c20b69472fad8b21f643da72455`.
- Arbre Git archivé : `a03529c9b10d30ee68e2b7faa8fd14892ea748ab`.
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

Premier état GREEN après implémentation : `16 passed, 0 failed`.

La revue de conformité a ensuite ajouté deux mutations négatives. Avant le
renforcement du validateur, elles ont produit le RED attendu sur celui-ci :
`16 passed, 2 failed` :

- remplacer `npm ci` dans `run_cockpit()` par `echo "npm ci"` était accepté ;
- remplacer l'étape YAML par un simple label `name: npm ci` et `run: true`
  était accepté.

Deuxième état GREEN après correction : `17 passed, 0 failed`. Les deux
mutations sont désormais rejetées.

La revue qualité a enfin ajouté dix mutations supplémentaires. Avant le
renforcement, le validateur a produit le RED attendu : `17 passed, 10 failed`.
Les faux négatifs démontrés étaient :

- l'absence de `lot-*` ou de `lot-*/**` dans les déclencheurs ;
- `if: false`, `continue-on-error: true` ou un `shell: "true {0}"` au niveau
  du job cockpit ou d'une étape obligatoire ;
- un `defaults.run.shell` personnalisé au niveau du workflow ou du job.

État GREEN avant revue finale : `27 passed, 0 failed`. Les dix mutations sont
rejetées.

La revue finale a ensuite imposé quatre corrections, chacune conduite en
RED → GREEN :

1. le test de rendu de l'aperçu a échoué `1/1` car l'interface affichait
   `8/20` au lieu des `11/20` calculés depuis `sources.json`, puis est passé
   `1/1` après suppression de la constante ;
2. le validateur de snapshots absent a produit `11` assertions en échec,
   puis les `6` tests de cohérence ont couvert les 59 collections, les entrées
   manquantes/surnuméraires, les doublons JSON/YAML et la dérive de chacun des
   sept champs canoniques pertinents ;
3. la matrice des requêtes vides a produit `1` échec sur le cas production
   sans URL (`demo: true`), puis les `10` tests API ont réussi en conservant
   le comportement de développement ;
4. les mutations `return 0` et `exit 0` anticipées ont produit
   `27 passed, 2 failed`, puis `29 passed, 0 failed` après passage à une
   exécution instrumentée.

Les commits fonctionnels correspondants sont respectivement `f294809`,
`09ba167`, `9e1be2e` et `e4db84f`.

La contre-revue a enfin relevé deux faux positifs de pipeline et une
dépendance environnementale :

- supprimer le `set -euo pipefail` propre à `run_cockpit()` était initialement
  accepté (`29 passed, 1 failed`). Le runner de test n'injecte désormais plus
  `set -e` et fait échouer successivement chacun des neuf contrôles. Il exige
  à chaque fois un code final non nul et un journal strictement limité au
  préfixe atteint. État GREEN : `30 passed, 0 failed` ;
- exiger les six tests négatifs de cohérence dans le target local et le job
  GitHub a d'abord produit `28 passed, 2 failed`, puis `32 passed, 0 failed`
  après ajout des deux commandes et des mutations qui prouvent leur caractère
  obligatoire ;
- le choix du Python du clean build dépendait encore du poste. Les tests ont
  produit `32 passed, 2 failed`, puis `34 passed, 0 failed` : le venv
  `rag-pedago`, alimenté par `requirements.lock`, est préféré après
  vérification de `import yaml`, et le fallback `setup-python` est soumis à la
  même vérification.

Les commits de contre-revue sont `9e965c4`, `973cce7` et `225066f`.

Une dernière contre-revue Bash a révélé que l'appel `if "$@"` dans
`run_target()` désactivait implicitement `errexit` pendant toute l'exécution
de `run_cockpit()`. Le RED `33 passed, 1 failed` a prouvé qu'un échec injecté
sur `node` était suivi des huit contrôles cockpit restants et enregistré à
tort comme un succès. L'instrumentation extrait et exécute désormais ensemble
les vraies fonctions `run_target()` et `run_cockpit()`, puis un target
sentinelle : elle vérifie à la fois l'arrêt immédiat du target cockpit, la
poursuite de la matrice vers la sentinelle et le code final non nul décidé par
le résumé. La correction appelle `"$@"` hors de toute condition, capture
immédiatement son statut, incrémente les compteurs par affectation arithmétique
et retourne neutrement afin que seul le résumé tranche. État GREEN :
`35 passed, 0 failed`. Commit correspondant : `0a1a8d5`.

Le contrôle shell extrait réellement les fonctions `run_target()` et
`run_cockpit()` par frontières syntaxiques, exige chaque commande comme ligne
shell complète, puis les exécute avec de faux `npm`, `bash` et Python. Il
compare les neuf appels, leur ordre et leur répertoire de travail attendu.
Aucun vrai pipeline n'est lancé par ce test ; une sortie anticipée ou une
branche qui rendrait une commande inatteignable laisse une trace incomplète et
est rejetée. Les faux exécutables sont ensuite configurés pour échouer un par
un ; le contrôle prouve la propagation fail-fast dans `run_cockpit()`, la
poursuite du target suivant et l'échec du résumé final, sans créer
artificiellement ces propriétés dans son runner.
Le contrôle du workflow parse le YAML avec PyYAML. Il exige sémantiquement
`main`, `lot-*` et `lot-*/**` pour `push` comme pour `pull_request`, inspecte
exclusivement `jobs.cockpit.steps`, vérifie que `run` est une chaîne égale à
la commande attendue et contrôle son `working-directory`. Il interdit aussi
`if`, `continue-on-error` et `shell` sur le job ou ses étapes, ainsi que tout
`defaults.run.shell` applicable. Un label, un booléen YAML, un `echo`, une
commande placée dans un autre job ou une neutralisation du shell ne peut donc
satisfaire le garde-fou. L'audit complet et l'audit `--omit=dev` restent deux
étapes distinctes et exactes.

## Commandes de validation

Validation ciblée et statique :

```bash
bash scripts/tests/test-ci-local-failsafe.sh
python3 scripts/tests/test-cockpit-snapshot-coherence.py -v
npm --prefix services/cockpit test -- --run
npm --prefix services/cockpit run lint
bash -n scripts/lib/ci-common.sh scripts/ci-local.sh \
  scripts/tests/test-ci-local-failsafe.sh \
  scripts/tests/test-cockpit-clean-build.sh
git diff --check
python3 - <<'PY'
from pathlib import Path
import yaml

workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
assert "jobs" in workflow and "cockpit" in workflow["jobs"]
triggers = workflow.get("on", workflow.get(True))
required = {"main", "lot-*", "lot-*/**"}
for event in ("push", "pull_request"):
    assert required <= set(triggers[event]["branches"])
PY
```

Validation locale complète du commit fonctionnel :

```bash
/usr/bin/time -p npm exec --yes --package=node@22.22.0 -- \
  bash scripts/ci-local.sh
```

Résultat : code de sortie `0`, `537.53 s` réelles, `467.35 s` utilisateur et
`58.19 s` système.

## Résultat par target

| Target CI locale | Résultat | Preuve principale |
|---|---|---|
| `packages/contracts` | PASS | import du contrat canonique réussi |
| `services/rag-pedago` | PASS | ruff vert, mypy vert sur 73 fichiers, `1151 passed` en `280.72 s` |
| `services/rag-engine` | PASS | installation, lint, typecheck et `603 passed`, `15 deselected` |
| `services/cockpit` | PASS | lint, 4 fichiers/`13` tests Vitest, `6` tests snapshots, build et deux audits à zéro |
| `governance-locks` | PASS | 18 clés identiques à la baseline |
| `taxonomy-validation` | PASS | 57 taxonomies, 0 erreur, 486 notions et 174 sous-notions |
| `source-evidence-check` | PASS | 11 verdicts couvrent la configuration courante |
| `governance-guard-tests` | PASS | `16 passed, 0 failed` |
| `ci-failsafe-tests` | PASS | `35 passed, 0 failed`, dont dix-huit mutations anti-contournement |

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
services/rag-pedago/.venv/bin/python \
  scripts/tests/test-cockpit-snapshot-coherence.py  # local
python3 scripts/tests/test-cockpit-snapshot-coherence.py  # GitHub
bash scripts/tests/test-cockpit-clean-build.sh
```

Résultats de la CI locale :

- `npm ci` : 510 paquets ajoutés, 511 paquets audités, 0 vulnérabilité ;
- tests : 4 fichiers, 13 tests réussis ;
- build : 1857 modules transformés, build Vite réussi ;
- `npm audit` complet : 0 vulnérabilité ;
- `npm audit --omit=dev` : 0 vulnérabilité ;
- tests snapshots : 6 tests réussis dans le target cockpit, avant le clean
  build ;
- clean build : concordance cockpit/Eduscol validée sur 20 sources et
  concordance exhaustive des 59 collections cockpit/rag-engine, puis nouvelle
  installation `npm ci` depuis l'archive Git et nouveau build réussi.

Le contrôle des 59 collections prouve uniquement l'identité exhaustive du
catalogue versionné : unicité, absence d'entrée manquante ou surnuméraire et
égalité de `matiere`, `niveau`, `voie`, `statut`, `domain`, `taxonomy_file` et
`instanciee`. Il ne mesure pas et ne revendique pas la substance du corpus,
qui relève des gates des lots ultérieurs.

Le clean build a utilisé `HEAD`, donc l'arbre Git
`a03529c9b10d30ee68e2b7faa8fd14892ea748ab`, et non les fichiers non suivis du
poste.

## Workflow GitHub Actions

Le job `cockpit` utilise `actions/setup-node@v4` avec
`node-version-file: .nvmrc`, le cache npm et
`cache-dependency-path: services/cockpit/package-lock.json`. Il installe aussi
PyYAML `6.0.3`, requis par le contrôle de concordance du clean build.
Il exécute aussi explicitement
`python3 scripts/tests/test-cockpit-snapshot-coherence.py`. La CI locale
exécute le même fichier avec
`services/rag-pedago/.venv/bin/python`, dont PyYAML est verrouillé par le
target précédent ; aucun Python global opportuniste n'est requis.

Les événements `push` et `pull_request` couvrent `main`, les branches plates
`lot-*` et les branches imbriquées `lot-*/**`. Une PR empilée ciblant une
branche de lot déclenche donc la même CI.

Le workflow a été parsé sémantiquement et les valeurs `run` réellement
exécutables du job borné ont été couvertes par les tests locaux. Les clés qui
pourraient rendre le job conditionnel, tolérer un échec ou remplacer le shell
sont refusées par présence. **GitHub Actions n'a pas été exécuté dans cette
validation** : aucun résultat distant n'est revendiqué dans ce rapport.

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

## Réconciliation avec `main` (PR #76)

Après l'intégration des lots 31 et 35 dans `main`, la branche du lot 34 a été
fusionnée avec ce nouveau parent. Les conflits provenaient du remplacement du
cockpit Vite par le cockpit Next.js/BFF. La résolution conserve les routes BFF,
les contrats générés et les tests de frontière de `main`, ainsi que les
garde-fous CI et snapshots du lot 34.

Le client direct `src/lib/api.ts` et ses dix tests Vite ont été supprimés : ils
étaient incompatibles avec l'architecture BFF et leur couverture de sûreté est
remplacée par `src/lib/bff-client.test.ts` (route same-origin, absence de jeton
navigateur, validation de réponse, erreur opaque et délai borné). Les preuves
ciblées post-fusion sont :

- `SearchSection.test.tsx` : 2 tests réussis ;
- `test-ci-local-failsafe.sh` : 35 assertions réussies ;
- `test-cockpit-snapshot-coherence.py -v` : 6 tests réussis ;
- cockpit sous Node 22.22.0 : contrats, lint, 21 tests et build Next.js
  réussis.

La CI locale complète est relancée après ce rapprochement ; son résultat est
consigné avec le commit de merge avant publication de la branche.
