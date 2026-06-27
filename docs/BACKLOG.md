# Backlog des dettes techniques

## Tests préexistants en échec (rag-pedago)

| Test | Symptôme | Antériorité | Action |
|---|---|---|---|
| `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` | Assertion de statut (`ready_for_human_locked_metadata_validation` != `blocked`) | Prouvé sur commit `e16cbed` (avant Lot 0) | Lot dédié |
| `test_real_draft_unlock_gate` (tous) | ~~INTERNALERROR pytest~~ **Résolu** (lot-0.7.1). Cause : monkeypatch global de `Path.exists` interceptait pytest <9.x reporting. Fix : sous-classe `Path` injectée dans le module sous test (pas `pathlib.Path` global). Assertion `pathlib.Path("/").exists()` prouve le scope. 11/11 pass. | Prouvé sur commit `e16cbed` | Résolu — monkeypatch réellement scopé (lot-0.7.1) |

## Garde-fou de gouvernance

| Point | Détail | Action |
|---|---|---|
| Test « exception ADR » non automatisé | Le cas 5 (verrou retiré + ADR référencé sur ligne ajoutée → exit 0) nécessite un dépôt git temporaire pour être testé automatiquement | P2 cubic — dette tracée, vérifié manuellement (lot-0.2) |

## Outillage monorepo

| Point | Détail | Action |
|---|---|---|
| Distribution `nexus-contracts` | Non publié sur PyPI ; installé en éditable via `make install`. `pip install -e ".[dev]"` seul échoue. | Industrialiser via `uv workspace` (Phase 6) |
| Lockfiles sans hashes | `requirements.lock` de rag-pedago et rag-engine générés par `pip freeze` (pas `pip-compile --generate-hashes`) car nexus-contracts n'est pas sur PyPI. Contracts a des hashes (pip-compile). | Hashes possibles après passage à `uv workspace` |

## Audience / statuts hors-cible (Phase 5)

| Point | Détail | Action |
|---|---|---|
| Mapping `audience` incomplet | `status_detail == unknown` ou statuts hors-cible (système tunisien, double cursus, hors-AEFE) produit `aefe` par défaut sans warning | Affiner le mapping et émettre un warning pour les cas ambigus |

## Typecheck — inline `# type: ignore` ciblés (lot-0.7)

### rag-pedago (12 occurrences, plus d'overrides par module)
| Fichier | Ligne(s) | Code | Raison |
|---|---|---|---|
| `rag_pedago/project_doctor.py` | 105,121,124 | `assignment` | Variable reuse (str→Path, str→Pattern) |
| `rag_pedago/project_doctor.py` | 109,122,125 | `attr-defined` | Idem — .parts/.search sur str inféré |
| `rag_pedago/imports/real_draft_guard.py` | 105,150 | `union-attr` | yaml.safe_load returns Any/dict/None |
| `rag_pedago/imports/real_draft_unlock_gate.py` | 42,45 | `union-attr` | Idem |
| `rag_pedago/imports/pilot_manifest_template.py` | 170 | `union-attr` | Idem |
| `scrapers/discovery.py` | 263 | `union-attr` | enum .value on Optional |

## Divergence d'outils entre services

| Outil | rag-pedago | rag-engine | Risque |
|---|---|---|---|
| ruff | 0.15.19 | 0.6.4 | Règles différentes sur le contrat partagé |
| mypy | 2.1.0 | 1.11.2 | Idem |
| pytest | 9.1.1 | 8.3.3 | Comportement test subtil (cf. monkeypatch) |
| pydantic | 2.13.4 | 2.9.2 | Contrat compilé différemment selon le service |

**Plan** : unifier au prochain lot de maintenance. rag-engine a des contraintes runtime (py39 compat, dépendances transitives lourdes) qui rendent la montée non triviale.

## Lint legacy isolé (per-file-ignores)

### rag-pedago
| Règle | Fichiers | Raison de l'isolation |
|---|---|---|
| UP042 (str+Enum → StrEnum) | 9 fichiers governance/schema | Migration StrEnum sur code sensible, risque régression |
| B017 (bare pytest.raises) | 3 fichiers test ledger | Raffinement des assertions nécessaire |

### rag-engine
| Règle | Fichiers | Raison de l'isolation |
|---|---|---|
| F401/F841/B007 | `.windsurf/tmp/*`, `tests/*` | Scripts temporaires et fixtures de test legacy |

## Correspondance programme (lot 9.1)

| ID | Détail | Action |
|---|---|---|
| DETTE-9.1-A | `find_notion_in_text` — un label mono-mot ≥ 8 caractères compté `found_exact` même hors-sujet. Ex: "continuite" matcherait n'importe quel texte mathématique. | Rétrograder en `found_partial` ou exiger co-occurrence avec un terme du thème parent |
| DETTE-9.1-B | `_extract_bo_headings` ramasse le bruit structurel ("Annexe", "Sommaire", "Contenus Capacités attendues"). | Ajouter une stop-list de headings structurels ; cibler les sections "Contenus"/"Capacités attendues" |

## Agents (lot 10.1)

| ID | Détail | Action |
|---|---|---|
| DETTE-10.1-A | `_load_correspondence` cherche `{matiere}_{niveau}_*.pdf` ; le nommage produit par `programme_fetcher` est `{matiere}_{niveau}_{statut}.pdf`. Le pattern glob fonctionne mais la convention n'est pas documentée. | Aligner/documenter la convention de nommage |
| DETTE-10.1-B | Matching titre pédagogique → article : devine un titre exact au lieu de chercher. Résolu au Lot 11 (recherche réelle). | Résolu |
| DETTE-11.5-A | Filet troncature `(en)` / biblio peut sur-tronquer un article où « (en) » apparaît en plein contenu dans le dernier quart. Non observé sur les 16 fichiers actuels. | Motif plus strict à envisager à l'élargissement |
| DETTE-11.5-B | Sections « culture populaire / œuvres » conservées (faible valeur pédagogique, pas du chrome). | Relève de la curation de source, pas de l'extraction |

## Parsing/gating (lot 11.1)

| ID | Détail | Action |
|---|---|---|
| DETTE-11.1-A | `build_correspondence_report`/`extract_text_from_pdf` ne sont pas gated au niveau fonction. | Défense en profondeur si second appelant |

## Chunking (lot 12)

| ID | Détail | Action |
|---|---|---|
| DETTE-12-A | `<sup>` unwrap espace les exposants (`x²` → `x 2`). Contenu LaTeX dominant. | Raffiner vers `x^2` si besoin |
| VIGILANCE-RETRIEVAL | `statut_enseignement` non porté par `ChunkMetadata`. Filtrage par statut (spé/tronc/option) impossible. | Étendre contrat au lot retrieval |
| DETTE-9.1-B | `bo_only` : stop-list structurelle + filtre non-mots appliqués (lot 12.3). | Résolu |

## pgvector / indexation (lot 14)

| ID | Détail | Action |
|---|---|---|
| DETTE-14-RAGENGINE | Indexation+retrieval pgvector résident dans rag-pedago ; doivent migrer dans rag-engine (plan de données, AGENTS.md) AVANT toute exposition derrière le contrat d'API. | Lot dédié de refactoring structurel |

## Périmètre acquisition

| Point | Détail | Action |
|---|---|---|
| notion_articles.yml | 40 entrées pour ~420 notions. | Élargissement à planifier (lot dédié) |
| Sources conceptuelles/examen | STEM 100%, conceptuel 80%, examen 13%. | Décision Drive à trancher sur constat chiffré 11.3 |

## Process

| Point | Détail |
|---|---|
| Commit ROADMAP hors PR | Le commit `93f5ba8` a été poussé directement sur `main` — écart de process noté, historique non réécrit |
