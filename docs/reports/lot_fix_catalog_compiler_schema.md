# LOT — Correction du schéma incompatible de `corpus_catalog_compiler.py`

## Verdict

`corpus_catalog_compiler.py` compile désormais un catalogue complet
contre le VRAI manifeste scellé et le VRAI fichier de placement du
corpus scellé (`00_ADMIN/{SHA256SUMS.txt,eduscol_affectations.tsv}`,
2583 entrées de manifeste, `SEALED_MANIFEST_SHA256=d7e5caa5...`) — preuve
d'acceptation exécutée et vérifiée, pas seulement contre des fixtures
synthétiques. Aucune régression sur le schéma pédagogique riche
préexistant (112/112 tests verts, y compris tous les tests qui
construisaient déjà ce format). Aucune donnée fabriquée : les champs
sans correspondance réelle dans le corpus (`title`/`source_url`/
`family`/`scope`/`status`) sont explicitement `None`, jamais une valeur
plausible inventée. `GO_LIVE_READY` reste `false`. Aucune mutation live.

## Diagnostic — pas un bug de renommage de colonnes

`_load_eduscol_placements()` exigeait un schéma pédagogique riche
(`annee, chemin_par_niveau, chemin_par_scope, chemin_technique_existant,
famille, matiere_ou_rubrique, niveau, objet_source, scope, statut,
titre, type_document, url_source`) — utilisé par `PedagogicalPlacement`
pour porter `title`/`source_url`/`family`/`scope`/`status` en plus des
champs communs. Le VRAI fichier committé
(`00_ADMIN/eduscol_affectations.tsv`) a un schéma totalement différent :
`sha256, canonical_destination, source_relative, level, subject,
doc_type, year, is_primary, size`.

**Ce n'est pas un renommage tardif de colonnes.** Recherche exhaustive
dans le corpus scellé local (`00_ADMIN/*.tsv`, l'inventaire du
`eduscol-pdf-harvester` local) : aucun fichier ne porte de colonne
`titre`/`url_source`/`famille`/`scope`/`statut` nulle part. Ces données
n'ont simplement jamais été capturées par la chaîne d'acquisition
réelle de ce corpus (`BUILD_INFO.json` : assemblé localement depuis
`eduscol-pdf-harvester`, jamais depuis un catalogue éditorial
pédagogique). Le schéma riche reste un format réel et testé — utilisé
ailleurs dans le dépôt (`currentness_gate.py`, `artifact_placement_
model.py`, fixtures de test) — mais il décrit une source qui n'existe
tout simplement pas pour CE corpus.

**Aucun de ces champs n'est déterminant pour une décision de
gouvernance.** Vérifié par recherche : `title`/`source_url`/`family`/
`scope`/`status` ne sont jamais lus par aucun gate PII/droits/actualité/
routage — seulement portés dans `attribution_metadata`, une annotation
descriptive du catalogue. `_determine_disposition` (zone → disposition)
et `_apply_mandatory_ingest_gates` ne les consultent jamais.

## Ce qui a été fait

1. **`PedagogicalPlacement`** (`artifact_placement_model.py`) : les sept
   champs sans correspondance réelle deviennent `str | None = None` —
   jamais une valeur inventée pour représenter une absence. Ajout de
   `is_primary: bool = True`, seule donnée réelle et supplémentaire du
   schéma technique (désambiguïse les placements multiples).
2. **Détection de schéma à deux voies** dans `_load_eduscol_placements` :
   le header du fichier fourni est confronté aux deux jeux de colonnes
   connus (`_PEDAGOGICAL_PLACEMENT_COLUMNS` — chemin existant, intact,
   zéro régression — et `_TECHNICAL_PLACEMENT_COLUMNS` — nouveau,
   colonnes exactes du fichier réel committé) ; un header qui ne
   correspond à aucun des deux est refusé explicitement, jamais un
   schéma deviné.
3. **`_load_technical_eduscol_placements`** (nouveau) : strict — colonne
   manquante OU colonne inattendue refusées (même discipline « strict by
   construction » que `h2_evidence.py`). Multi-placement réel accepté :
   un même `sha256` peut apparaître sur plusieurs lignes partageant la
   MÊME `canonical_destination` (un seul emplacement physique) mais des
   `source_relative`/`subject` différents — motif vérifié directement
   sur le fichier réel (`000069ef34...` : deux lignes, `ETLV` vs
   `LANGUES_VIVANTES`, même destination). `is_primary` désambiguïse :
   exactement une ligne à `1` par groupe `sha256`, sinon refus (zéro ou
   plusieurs primaires est un défaut d'intégrité de la source). Une
   ligne strictement dupliquée (même `sha256` ET même `source_relative`)
   est refusée séparément.
4. **`_placement_attribution`** : gère `source_url is None` (chemin
   technique) sans jamais inventer d'URL — marqueur explicite
   `"UNKNOWN"`, jamais une chaîne vide silencieuse ni un `null` JSON qui
   passerait inaperçu. Le chemin pédagogique riche produit toujours une
   vraie URL et ne déclenche donc jamais ce marqueur (aucune régression).

## Ce qui n'a pas été fait, et pourquoi

- **Aucune tentative de reconstituer `title`/`source_url` depuis
  l'évidence brute du `eduscol-pdf-harvester`** (`~/Téléchargements/
  eduscol-pdf-harvester-release-v1.10.0/evidence/*.tsv`, qui contient
  potentiellement des URLs par run). Une jointure fiable par
  `content_sha256` vers ces preuves brutes est un travail de
  réconciliation distinct et plus profond, hors périmètre de cette
  correction de schéma — signalé, pas éludé.
- **Aucune modification de `packages/contracts`** : `PedagogicalPlacement`
  vit dans `rag_pedago.imports`, un modèle interne au service, jamais le
  contrat partagé cross-service. Élargir des champs `str` en `str | None`
  y est un changement interne sans ADR requis (AGENTS.md).

## Tests — résultats exacts

```
$ cd services/rag-pedago && PYTHONPATH=$(pwd):$PYTHONPATH \
    .venv/bin/python -m pytest tests/test_corpus_catalog_compiler.py \
    tests/test_corpus_review_view.py tests/test_artifact_placement_model.py -q
112 passed

$ .venv/bin/python -m ruff check rag_pedago/imports/corpus_catalog_compiler.py \
    rag_pedago/imports/artifact_placement_model.py tests/test_corpus_catalog_compiler.py
All checks passed!

$ .venv/bin/python -m mypy rag_pedago/imports/corpus_catalog_compiler.py \
    rag_pedago/imports/artifact_placement_model.py
Success: no issues found in 2 source files
```

**Preuve d'acceptation — vrai corpus, pas une fixture** :

```python
catalog = compile_sealed_catalog(
    Path.home() / "Téléchargements/NEXUS_RAG_GDRIVE_READY/00_ADMIN/SHA256SUMS.txt",
    Path.home() / "Téléchargements/NEXUS_RAG_GDRIVE_READY/00_ADMIN/eduscol_affectations.tsv",
    yaml.safe_load(Path("configs/corpus_zone_routing.yml").read_text()),
)
# manifest_entries=2583, physical_objects=2584, artifacts=2583, verification_passed=True
```

`physical_objects=2584` = 2583 entrées de manifeste + l'auto-exclusion du
manifeste lui-même. `artifacts=2583` = 2582 `content_sha256` uniques
parmi les 2583 entrées de manifeste (un contenu dupliqué à deux chemins
physiques, cohérent avec la réconciliation déjà établie dans PR #108)
**plus** le `content_sha256` propre du manifeste, distinct. Ce calcul
est dérivé directement de l'exécution réelle ci-dessus, jamais codé en
dur.

Nouveau test dédié (`test_real_2583_entry_corpus_compiles_end_to_end`)
ignoré explicitement (`pytest.mark.skipif`) si le corpus local est
absent — jamais un test faussement vert.

## Mutation-testing

```
1. contrôle colonne inattendue désactivé → rouge (DID NOT RAISE), restauré → vert
2. contrôle ligne dupliquée désactivé → rouge (message erroné, la ligne
   dupliquée en question a d'abord été rattrapée par le contrôle
   is_primary, preuve que les deux contrôles sont indépendants et
   complémentaires), restauré → vert
3. contrôle « exactement un is_primary=1 » désactivé → rouge (DID NOT
   RAISE, x2 : zéro et deux primaires), restauré → vert
```

## Round 2 — régression mypy réelle trouvée par la CI, corrigée

La CI (`make typecheck`, `mypy schema pipeline retrieval services
rag_pedago scrapers agents` — le périmètre complet du service, plus
large que les fichiers directement touchés par ce lot) a trouvé 3
erreurs réelles dans `rag_pedago/governance/corpus_review_view.py`,
un fichier que ce lot n'avait pas touché mais dont le typage dépend de
`PedagogicalPlacement.scope_path`, élargi ici de `str` à `str | None` :

```
corpus_review_view.py:363: Invalid index type "tuple[str, str | None]"
  for "dict[tuple[str, str], Any]"
corpus_review_view.py:470: Argument "key" to "sorted" has incompatible
  type "Callable[[PedagogicalPlacement], str | None]"
```

Ni la revue indépendante initiale (mypy limité aux deux fichiers de ce
lot) ni la vérification locale du lot lui-même n'avaient exercé le
périmètre mypy complet du service — la régression n'était donc visible
que dans la CI réelle. Corrigé en réutilisant `_plain()`, le helper de
normalisation `None → ""` déjà établi dans ce même fichier pour
exactement cette classe de champ, aux deux points d'usage
(construction de clé de dict, clé de tri) plutôt que d'assouplir le
typage du dict ou du tri.

```
$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m mypy schema pipeline retrieval services rag_pedago scrapers agents
Success: no issues found in 92 source files

$ PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/test_corpus_review_view.py \
    tests/test_corpus_catalog_compiler.py tests/test_artifact_placement_model.py -q
112 passed
```

## Booléens finaux

```
CATALOG_COMPILER_SCHEMA_MISMATCH_ROOT_CAUSE=DATA_NEVER_CAPTURED_NOT_A_RENAME
CATALOG_COMPILER_TECHNICAL_SCHEMA_SUPPORTED=true
CATALOG_COMPILER_PEDAGOGICAL_SCHEMA_REGRESSION=false
REAL_2583_ENTRY_CORPUS_COMPILE_REHEARSAL_PASSED=true
FULL_SERVICE_MYPY_CLEAN=true
NO_FABRICATED_EVIDENCE=true
CONTRACTS_MODIFIED=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
