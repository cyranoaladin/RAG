# Unification `release_readiness` — candidat local

```
F_BASE_SHA=90e682f7d586f436f8048317138efd0b92c718f9
F_LOCAL_CANDIDATE=PASS      F_FINAL_INTEGRATION=NOT_YET
PR_OPENED=false             MERGE_ATTEMPTED=false
```

## 1. Objectif structurel atteint

```
RELEASE_READINESS_IMPLEMENTATIONS=1
SERVICE_RELEASE_READINESS_DUPLICATED_LINES=0
DEPLOYMENT_BINDING_IMPLEMENTATIONS=1
RUNTIME_RELEASE_SEMANTICS=C1_RELEASE_SEMANTICS
```

Le service portait 1913 lignes tenues égales octet pour octet par une épreuve.
L'égalité rendait la divergence **détectable**, pas impossible : deux copies du
même contrat restaient deux copies, et une image pouvait partir avec l'une
pendant que le qualificateur lisait l'autre.

## 2. Consommateurs

```
PRODUCTION_CONSUMERS_TOTAL=6
PRODUCTION_CONSUMERS_ALREADY_CANONICAL=1     (build_production_profile_release.py)
PRODUCTION_CONSUMERS_MIGRATED_BY_F=5
PRODUCTION_CONSUMERS_CANONICAL_AFTER_F=6
NON_CANONICAL_RELEASE_READINESS_IMPORTS=0
```

Recherche statique sur **tout** le dépôt — scripts, tests, entrypoints,
workers, outils de déploiement, imports dynamiques :

```
FICHIERS_REFERENCANT_L_AUTORITE=44        LIGNES=669
RELEASE_READINESS_REFERENCES_ACCOUNTED=100%
STALE_SERVICE_IMPORTS=0                   BROKEN_DYNAMIC_IMPORTS=0
```

Se limiter aux six connus aurait laissé un outil importer un module supprimé,
et l'échec ne serait apparu qu'à l'exécution.

## 3. Contrat public — auditable, pas seulement haché

```
PUBLIC_CONTRACT_SYMBOLS=9
CONTRACT_SIGNATURE_SHA256=79f366266186f39714fbb223cb2cf46aa78ee009971c1d07cdb1ba463e1b8893
SIGNATURE_DRIFT=0     EXCEPTION_SEMANTICS_DRIFT=0
```

Ledger complet dans `docs/reports/handoff/release_authority_public_contract.json` :
nom, nature, signature, contrat d'exception, nombre de consommateurs. Le plus
employé est `load_release_registry_file` (5 consommateurs).

## 4. Images — construites et éprouvées

```
READ_RUNTIME_RELEASE_CHAIN_INSTALLED=true    READ_RUNTIME_PYPDF_PRESENT=false
READ_RUNTIME_RELEASE_READINESS=PASS          READ_RUNTIME_RELEASE_REGISTRY_LOAD=PASS
READ_RUNTIME_RELEASE_CONTENTS=319            READ_RUNTIME_PIP_CHECK=PASS

FINAL_IMAGE_EDITABLE_INSTALLS=0    FINAL_IMAGE_REPO_PATHS=0    FINAL_IMAGE_WORKTREE_PATHS=0
FICHIERS_PTH_EDITABLES=0           BUILD_CONTEXT_RESIDUEL=false
C4_RUNTIME_HOST_DEPENDENCIES=0     C4_RUNTIME_WORKTREE_DEPENDENCIES=0
```

Éprouvé depuis `--network none` et un répertoire de travail hors de tout
checkout : l'origine du paquet est `/usr/local/lib/python3.11/site-packages/`.
Le Dockerfile de lecture **vérifie lui-même** que `pypdf` reste absent.

## 5. L'extra PDF — niveau de preuve exact

```
PDF_EXTRA_IMPLEMENTED=true
PDF_EXTRA_PACKAGING_TEST=PASS
PDF_EXTRA_CANONICAL_ENV_TEST=PASS
PRODUCTION_IMAGES_USING_PDF_EXTRA=0
PDF_EXTRA_PRODUCTION_IMAGE_PROOF=NOT_APPLICABLE_CURRENT_ARCHITECTURE
```

Mesuré, pas supposé : **aucune** image n'importe `pdf_extractor`. Ses vrais
consommateurs sont les scripts producteurs de `rag-pedago`, qui tournent sur le
plan de contrôle et installent déjà `pdf-page-policy` explicitement.

Sans l'extra, `pdf_extractor` refuse en nommant `nexus-release-chain[pdf]` — au
lieu d'un `ModuleNotFoundError` nu qui nomme un paquet interne que personne n'a
demandé.

### pypdf — le fail-closed conservé

```
CANONICAL_PYPDF_VERSION=6.14.2
OBSERVED_CANONICAL_ENV_PYPDF_VERSION=6.14.2      PYPDF_VERSION_MATCH=true
UNCONSTRAINED_INSTALL_RESOLVED_PYPDF=6.18.0      require_canonical_pypdf=REFUSED
```

Le contrat est « extra + lock du consommateur ». Une épreuve **statique** lie
désormais le lock du worker à `CANONICAL_PYPDF_VERSION` : la dérive se verra
avant la construction, pas au premier worker qui refuse de démarrer.

## 6. Mutants

```
MUTANTS_TOTAL=7   MUTANTS_KILLED=7   MUTANTS_SURVIVED=0
```

| # | Mutation | Verdict |
|---|---|---|
| 1 | réintroduire une implémentation dans le service | TUÉ |
| 2 | duplicata local sous un autre nom | TUÉ |
| 3 | retirer release-chain de l'image de lecture | TUÉ |
| 4 | rendre la pile PDF obligatoire dans le cœur | TUÉ |
| 5 | pypdf non canonique dans l'image PDF | TUÉ |
| 6 | altérer la sémantique de la liaison de déploiement | TUÉ |
| 7 | altérer une signature publique | TUÉ |

M2 mérite d'être noté : l'épreuve ne cherche pas le nom du fichier supprimé
mais la **signature du contrat** dans tout le service — le fichier pouvait
renaître sous un autre nom.

Mon premier harnais capturait le code de sortie de `tail` au lieu de celui de
pytest : les sept ressortaient « survivants » à tort. Et M5 installait `pypdf`
sans réseau — l'installation échouait en silence, le mutant n'était jamais
appliqué. Les deux corrigés avant de conclure.

## 7. Suite complète

`services/rag-engine` : suite entière verte, lint et typecheck propres.

## 8. Ce qui reste

Après fusion de #153 : `fetch` → rebase → comparaison de surface → run complet →
reconstruction des images → rejeu des 7 mutants → recalcul du
`CONTRACT_SIGNATURE_SHA256`. Aucun résultat de ce HEAD ne vaut pour le HEAD
rebasé.
