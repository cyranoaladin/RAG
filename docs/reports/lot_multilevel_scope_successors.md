# LOT — Émetteur canonique de scopes de retrieval et succession de subject

- **Branche** : `glr/multilevel-preflight`
- **ADR** : [ADR-0048](../adr/ADR-0048-emetteur-canonique-scopes-retrieval.md), qui référence ADR-0045
- **Dettes** : [`lot_multilevel_scope_successors_dettes.md`](lot_multilevel_scope_successors_dettes.md)

## Le défaut

La release multi-niveaux régénérée (`6ec1a4f8…`, 353 chunks, 11 artefacts,
10 subjects) a délié les dix scopes de retrieval qui désignaient la release
archivée du 2026-08-13 (`d8ee6703…`). Le moteur, qui sélectionne un scope par
le couple exact `(collection, subject_sha256)`, refusait donc de démarrer :
`RuntimeError: scope source SHA differs from subject release`.

**La garde n'a pas été desserrée.** C'est elle qui a découvert la dette : les
trente artefacts de scope V2 packagés n'avaient aucun émetteur reproductible
in-repo. Le correctif est de fournir le bon artefact, produit par un outil qui
sait dire d'où viennent ses valeurs.

## Ce qui a été livré

| Livrable | Chemin |
|---|---|
| Émetteur canonique | `packages/contracts/scripts/build_retrieval_scope_artifacts.py` |
| Autorité de politique | `packages/contracts/authorities/multilevel-retrieval-scope-policy-v1.yml` |
| Dix successeurs `_v2` | `packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-*-v2.json` |
| Registre fermé | `packages/contracts/src/nexus_contracts/scope.py` (+10 entrées) |
| Tests de l'émetteur | `packages/contracts/tests/test_build_retrieval_scope_artifacts.py` (30) |
| Tests de succession et d'immuabilité | `packages/contracts/tests/test_multilevel_scope_successors.py` (85) |

### Le point de sécurité : deux familles d'entrées

Une release dit CE QUI EXISTE ; un scope dit QUI PEUT VOIR QUOI. L'émetteur ne
tire de la release **que** `source_sha256`. Les douze dimensions
d'autorisation — `tenant`, `niveau`, `voie`, `matiere`, `statut_enseignement`,
`candidat`, `audiences`, `visibility`, `rights`, `school_year`,
`programme_version`, `collection` — sont lues dans le scope gouverné que
l'autorité de politique **nomme**, et jamais ailleurs. `audiences` et `rights`
n'ont d'ailleurs aucune contrepartie dans une release : ils ne peuvent
structurellement pas en venir.

L'émetteur croise ensuite les deux : les dimensions déclarées par les
placements du subject doivent coïncider avec la politique. Elles coïncident,
toutes, sur les dix subjects — c'est mesuré, pas supposé.

## Mesures

```
SUBJECT_COUNT=10
NEW_SCOPE_COUNT=10                  (mesuré : EXACT_EXISTING_MATCH == 0 pour les 10 sujets)
HISTORICAL_SCOPE_COUNT=31           (30 artefacts V2 + 1 pilote V1)
REGISTRY_BEFORE=31
NEW_SCOPES=10
REGISTRY_AFTER=41
OLD_SCOPE_BYTES_CHANGED=0
OLD_SCOPE_DIGESTS_CHANGED=0
HISTORICAL_SCOPE_BYTES_CHANGED=0
PROD_SCOPE_BYTES_CHANGED=0
PROD_SCOPE_DIGESTS_CHANGED=0
ZERO_MATCHES=0
MULTIPLE_MATCHES=0
EXACT_MATCHES=10
AUTHORIZATION_SEMANTIC_DIFF=0
SCOPE_EMITTER_DETERMINISTIC=true
V3_ARTIFACTS=0
CONTRACTS_VERSION=0.16.0
ADR=ADR-0048
```

### Comment chaque mesure a été obtenue

- `SUBJECT_COUNT` / `NEW_SCOPE_COUNT` : lus de `multilevel.release.json` et du
  calcul de réutilisation de l'émetteur, jamais codés en dur
  (`test_emitted_scope_count_is_measured_from_the_release`,
  `test_every_subject_of_the_regenerated_release_needs_a_new_binding`).
- `REGISTRY_BEFORE` : `git show HEAD:…/scope.py`, comptage des entrées → 31.
  `REGISTRY_AFTER` : même comptage sur l'arbre → 41.
- `OLD_SCOPE_BYTES_CHANGED` / `PROD_SCOPE_BYTES_CHANGED` : `sha256sum` des 31
  fichiers d'artefact avant/après (`comm -23`) → 0 ; et
  `git status --porcelain packages/contracts/src/nexus_contracts/artifacts/`
  → 0 modification, 10 ajouts.
- `OLD_SCOPE_DIGESTS_CHANGED` : `git diff HEAD -- scope.py | grep '^-'` → aucune
  ligne supprimée hors en-tête ; et table gelée des 31 digests dans
  `test_a_historical_scope_keeps_its_pinned_digest`.
- `EXACT_MATCHES` / `ZERO_MATCHES` / `MULTIPLE_MATCHES` :
  `test_the_release_subjects_have_exactly_one_matching_scope_each`, qui rejoue
  la sélection du runtime sur les 10 subjects.
- `AUTHORIZATION_SEMANTIC_DIFF` : `authorization_semantic_diff()` sur chaque
  couple (successeur, politique source), exclusions explicites de `scope_id` et
  `source_sha256` — le digest changeant par construction.
- `SCOPE_EMITTER_DETERMINISTIC` : deux exécutions du CLI dans deux répertoires,
  comparaison octet à octet des artefacts et de l'index de registre.
- `V3_ARTIFACTS` : aucun `RetrievalScopeArtifactV3` dans le registre.

### Mesure de cartographie, rectifiée

Le brief annonçait « 20 artefacts `prod_*` et 10 de la famille diagnostic ». La
mesure donne **18 `prod_*`** (cohérent avec ADR-0045, qui publie dix-huit
scopes pour dix-huit collections) et **12** de la famille diagnostic, dont 10
liaient la release multi-niveaux du 2026-08-13 ; les deux autres
(`entree_seconde_maths_v1`, `entree_seconde_francais_v1`, collections
troisième) relèvent de Wave 0 et ne sont pas concernés. Total 30 V2 + 1 pilote
V1 = 31, comme annoncé.

## Liaisons émises

| Collection sujet | Politique reconduite | Successeur émis |
|---|---|---|
| `rag_nexus_maths_seconde_tc` | `entree_premiere_maths_v1` | `entree_premiere_maths_v2` |
| `rag_nexus_francais_seconde_tc` | `entree_premiere_francais_v1` | `entree_premiere_francais_v2` |
| `rag_nexus_maths_quatrieme_tc` | `entree_troisieme_maths_v1` | `entree_troisieme_maths_v2` |
| `rag_nexus_francais_quatrieme_tc` | `entree_troisieme_francais_v1` | `entree_troisieme_francais_v2` |
| `rag_nexus_maths_premiere_gen_specialite` | `entree_terminale_maths_v1` | `entree_terminale_maths_v2` |
| `rag_nexus_nsi_premiere_specialite` | `entree_terminale_nsi_v1` | `entree_terminale_nsi_v2` |
| `rag_nexus_francais_premiere_tc` | `eaf_premiere_francais_v1` | `eaf_premiere_francais_v2` |
| `rag_nexus_maths_terminale_gen_specialite` | `terminale_maths_v1` | `terminale_maths_v2` |
| `rag_nexus_nsi_terminale_specialite` | `terminale_nsi_v1` | `terminale_nsi_v2` |
| `rag_nexus_pc_terminale_specialite` | `terminale_physique_chimie_v1` | `terminale_physique_chimie_v2` |

Le décalage de niveau des noms `entree_*` (entrée en N, contenu de N−1) est
l'intention métier du diagnostic. Il est désormais **verrouillé par un test
discriminant** sur toute la famille, et le test complémentaire vérifie que les
scopes hors diagnostic restent, eux, sur leur propre niveau.

## Mutations prouvées

Protocole pour chacune : vert → garde neutralisée → rouge → garde restaurée →
vert. Script rejouable, exécuté sur le venv CI de `packages/contracts`.

| Garde neutralisée | Effet mesuré |
|---|---|
| baseline (intacte) | `30 passed` |
| croisement politique / sujet | `6 failed, 24 passed` |
| refus d'autorité de politique absente | `1 failed, 29 passed` |
| convention de succession `_v<N>` → `_v<N+1>` | `1 failed, 29 passed` |
| collision de `scope_id` entre deux liaisons | `1 failed, 29 passed` |
| refus de deux scopes pour le même sujet | `1 failed, 29 passed` |
| reproduction stricte d'un `scope_id` du registre | `2 failed, 28 passed` |
| refus d'élargissement d'autorisation | `4 failed, 26 passed` |
| vérification de digest des entrées | `2 failed, 28 passed` |
| refus de correspondances exactes multiples | `1 failed, 29 passed` |
| restaurée | `30 passed` |

Verrou sémantique, prouvé séparément en « corrigeant » le décalage de niveau de
`entree_premiere_maths_v2` (niveau cible aligné sur la collection, digest
ré-épinglé) : `85 passed` → `2 failed, 83 passed` → restauré `85 passed`.

### Les cinq mutants d'autorisation exigés

| Mutant | Test | Résultat |
|---|---|---|
| A — `visibility` élargie à `public` | `test_mutant_a_…`, `test_mutant_a_bis_…` | refusé |
| B — audience ajoutée | `test_mutant_b_an_added_audience_is_refused` | refusé |
| C — collection changée | `test_mutant_c_…`, `test_refuses_a_subject_whose_collection_differs…` | refusé |
| D — `candidat` changé | `test_mutant_d_…`, `test_mutant_d_bis_…` | refusé |
| E — deux scopes pour le même `(collection, subject_sha256)` | `test_mutant_e_…` | refusé |

Les mutants A à D sont éprouvés des deux côtés : par la release (croisement des
dimensions déclarées par les placements) et par la politique (recalcul de
`AUTHORIZATION_SEMANTIC_DIFF` après construction).

## Qualité

| Cible | Résultat |
|---|---|
| `packages/contracts` — pytest (venv CI, depuis la racine) | **683 passed** |
| `packages/contracts` — `export_schemas.py --check` | **OK** (aucun schéma modifié) |
| `packages/contracts` — `ruff check` | **All checks passed** |
| `services/rag-engine` — `make test` (`-m "not integration"`) | **3384 passed, 7 skipped** |
| `services/rag-engine` — `make lint` | **All checks passed** |
| `services/rag-engine` — `make typecheck` | **Success: no issues found in 132 source files** |
| `services/rag-pedago` — `make test` | 3122 passed, **1 failed** (dette tracée, antériorité démontrée) |

Au départ du lot, `services/rag-engine` portait **huit** échecs dus à la
régénération de la release (digests et comptes épinglés sur `d8ee6703…` /
359 chunks, et absence de scope lié). Tous sont au vert. Aucun test vert n'est
passé au rouge.

`REAL_MULTILEVEL_INGESTION` **n'a pas été lancé** : réservé au tronc consolidé.

## Ce qui n'a pas été touché

- la garde runtime `scope source SHA differs from subject release` ;
- l'API externe de la PR #148 (`/search/v2`, portées, taxonomie, OpenAPI,
  filtres de notion) ;
- la garde de motif d'autorité et le mappage scellé du banc de la PR #147 ;
- la release archivée `multilevel-superseded-20260813/` ;
- les dix-huit scopes `prod_*` de la porte de profils production ;
- les schémas publics de `packages/contracts/schema/` (seul `packageVersion`
  du lock suit la version du paquet).

## Point d'attention pour le reviewer

Aucune autorisation n'a changé, et l'émetteur est construit pour refuser qu'une
autorisation change à l'occasion d'une régénération de release. Si une
autorisation doit réellement évoluer — visibilité élargie, audience ajoutée,
droits étendus, tenant ou collection modifiés —, c'est une décision distincte,
à instruire séparément : ni ce lot, ni ADR-0048 ne la portent.
