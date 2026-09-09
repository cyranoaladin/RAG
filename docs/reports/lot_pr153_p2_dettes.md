# NEXUS-PR153-MYPY-BASELINE-DEBT-V1

Registre de la dette mypy préexistante constatée pendant le lot P2 de la PR #153.
Mesures du 2026-09-09, environnements hermétiques `venv-engine-testmax` (candidat `cc6bdd5`) et
`venv-testmax-baseline` (baseline `6f450db`), recettes identiques, `pip freeze` de tiers identiques.

```
MYPY_BASELINE_ERRORS=6
MYPY_CANDIDATE_ERRORS=6
MYPY_NEW_ERRORS=0
MYPY_FIXED_ERRORS=0
MYPY_ERROR_SET_EQUALITY=true
MYPY_BASELINE_ERROR_SET_SHA256=710b18a47b68d7da4e3f6510167a951c639b55279a137d9fe0a3a9667d75ccda
MYPY_CANDIDATE_ERROR_SET_SHA256=710b18a47b68d7da4e3f6510167a951c639b55279a137d9fe0a3a9667d75ccda
```

Empreinte calculée sur l'ensemble trié des lignes d'erreur, chemins normalisés relativement à la
racine du dépôt. Les deux empreintes sont égales : aucune erreur ajoutée, aucune supprimée.

| error_id | path | line | symbole | code | message normalisé | baseline | candidat | introduit par P2 | surface | bloquant P2 | bloquant merge | bloquant go-live | cause | lot recommandé |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MYPY-01 | `services/rag-engine/src/ingestor/search_api.py` | 205 | appel à `CrossEncoder.predict` | `arg-type` | argument 1 de type `list[tuple[str, Any]]`, attendu `list[list[str]]` | présent | présent | **false** | INGESTOR_V1 | false | false | false | KNOWN — la paire requête/document est construite en tuples, la stub de `sentence-transformers` attend des listes | typage rag-engine |
| MYPY-02 | `services/rag-engine/src/ingestor/tasks.py` | 205 | fonction déclarée `-> str` | `no-any-return` | retour `Any` depuis une fonction déclarée `str` | présent | présent | **false** | INGESTOR_V1 | false | false | false | KNOWN — valeur issue d'une structure non typée, sans transtypage explicite | typage rag-engine |
| MYPY-03 | `packages/release-chain/src/nexus_release_chain/ingestion_profiles/registry.py` | 22 | `import nexus_contracts.ingestion` | `import-untyped` | module installé, marqueur `py.typed` absent | présent | présent | **false** | RELEASE_CHAIN | false | false | false | KNOWN — `packages/contracts` n'expose pas de `py.typed`, alors que `release-chain` et `pdf-page-policy` en portent un | typage/packaging contracts |
| MYPY-04 | `packages/release-chain/src/nexus_release_chain/ingestion_profiles/registry.py` | 26 | `import nexus_contracts.profile_manifest` | `import-untyped` | idem | présent | présent | **false** | RELEASE_CHAIN | false | false | false | KNOWN — même cause | typage/packaging contracts |
| MYPY-05 | `packages/release-chain/src/nexus_release_chain/ingestion_profiles/manifest.py` | 16 | `import nexus_contracts.ingestion` | `import-untyped` | idem | présent | présent | **false** | RELEASE_CHAIN | false | false | false | KNOWN — même cause | typage/packaging contracts |
| MYPY-06 | `packages/release-chain/src/nexus_release_chain/ingestion_profiles/manifest.py` | 17 | `import nexus_contracts.profile_manifest` | `import-untyped` | idem | présent | présent | **false** | RELEASE_CHAIN | false | false | false | KNOWN — même cause | typage/packaging contracts |

Quatre des six ont une cause unique et mécanique : `packages/contracts` ne livre pas de marqueur
`py.typed`, contrairement à `packages/pdf-page-policy` et `packages/release-chain` qui en portent un.
Le commentaire du `pyproject.toml` de `release-chain` explique d'ailleurs pourquoi ce marqueur
compte : sans lui, mypy refuse d'analyser le paquet chez ses consommateurs.

## Les fichiers du correctif P2 sont propres

```
P2_CHANGED_FILES_MYPY_ERRORS=0
```
Deux mesures indépendantes, toutes deux à zéro :
- filtrage du run complet sur les deux chemins modifiés par `cc6bdd5` : aucune erreur ;
- `mypy` lancé directement sur chacun des deux fichiers : `Success: no issues found in 1 source file`.

## Portée de ce registre

`AGENTS.md` autorise la livraison d'un lot avec des échecs **préexistants** « à condition qu'ils
soient tracés dans `docs/reports/*_dettes.md` avec antériorité prouvée contre le commit parent ».
L'antériorité est ici prouvée par égalité d'ensembles contre le commit parent, à environnement
identique. Le présent document est l'artefact de traçage ; il n'a **pas** été committé dans
`docs/reports/`, pour ne pas élargir le périmètre du commit P2 scellé (`cc6bdd5`, deux fichiers).

Ce document EST ce dépôt. Il est committé après le correctif P2, dans un commit séparé de
gouvernance qui ne touche aucun code métier : le commit `cc6bdd5` et son empreinte de diff restent
inchangés. Verdict :

```
PR153_P2_FUNCTIONAL_STATUS=CLEAN
PR153_GLOBAL_MYPY_STATUS=PREEXISTING_DEBT
PR153_LOCAL_REPAIR_CANDIDATE=CLEAN_WITH_GOVERNED_PREEXISTING_DEBT
```
et jamais `GLOBAL_MYPY=PASS`.

Les quatre erreurs `import-untyped` ont une cause unique, à traiter dans le lot dépendances et
packaging, jamais ici :

```
MYPY_PYTYPED_ROOT_CAUSE_COUNT=4
CONTRACTS_PYTYPED_PRESENT=false
RECOMMENDED_LOT=DEPENDENCY_PACKAGING_REMEDIATION
```
