# LOT — Promotion d'autorité H2 : fermer la boucle candidat → couvert (Finding C)

## 1. Verdict

`services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` accepte
depuis longtemps une `ScopeAuthorizationArtifactV2` externe, portable,
committée dans Git — mais n'en faisait jusqu'ici **rien** pour un vrai
candidat compilé : `corpus_catalog_compiler.py` ne peut jamais, par
construction explicite, lever lui-même le gate d'autorité (LOT41A réel
n'existe qu'en base, côté rag-engine, jamais reconstruit côté
rag-pedago) — `gate_statuses["authority"]` reste toujours
`"BLOCKED_NOT_CLEARED"` pour un candidat réel, donc `disposition` reste
toujours `REVIEW_REQUIRED`/`QUARANTINE`, jamais `INGEST` (constat déjà
documenté dans `docs/reports/lot_fix_h2_evidence_workflow.md` §6, issu
du rehearsal E2E de PR #109). Ce lot construit le mécanisme manquant côté
gate : `_promote_authority_cleared_candidates`, une fonction dédiée,
nommée, indépendamment testable, qui reconnaît — sur une copie interne
jamais écrite sur disque, jamais le fichier catalogue lui-même — qu'une
preuve d'autorité externe réelle et vérifiée couvre un candidat lorsque
**toutes les autres portes obligatoires sont déjà indépendamment au
vert**. `corpus_catalog_compiler.py`, `packages/contracts` et tout
fichier rag-engine restent intouchés.

En construisant ce mécanisme, un second défaut structurel a été trouvé,
indépendamment, en investiguant *pourquoi* le gate final ne pouvait
jamais devenir vert même avec une autorité valide fournie : le périmètre
de complétude que l'autorité doit couvrir (`ingest_content_sha256`/
`ingest_rights_candidates`) était borné sur `item["disposition"] ==
"INGEST"` — toujours vide pour un candidat réel, puisque c'est
précisément ce que ce défaut empêche — au lieu de
`item["base_disposition"] == "INGEST"`, le véritable ensemble de
candidats qu'un compilateur réel produit. Borner sur `disposition`
rendait le contrôle de complétude **vacuement satisfait** sur un
ensemble toujours vide, pour tout catalogue réel : une autorisation ne
couvrant *rien du tout* passait la vérification de complétude sans
jamais être mise en défaut. **Finding C**, ci-dessous.

Trois tests préexistants encodaient — sans le savoir — ce même défaut
comme s'il s'agissait d'une propriété de sûreté légitime (voir §4) ; ils
ont été corrigés, jamais affaiblis : leurs propriétés de sûreté réelles
(mode `rehearsal` toujours rouge, autorité qui ne couvre pas → refus dur,
catégorie de droits non couverte → refus dur) restent identiques,
inchangées, toujours vérifiées.

## 2. Défaut corrigé n°1 — le mécanisme de promotion manquant

Nouvelle fonction, `_promote_authority_cleared_candidates`
(`h2b_coverage_report.py`), appelée juste après le calcul de
`authority_allowlist`, sur `copy.deepcopy(physical_objects)` — jamais sur
`physical_objects`/`catalog` eux-mêmes, qui doivent rester bit-à-bit
identiques au fichier catalogue sur disque (la validation golden-corpus,
plus bas, compare explicitement `load_catalog(catalog_path) != catalog`
et refuse toute divergence — une mutation en place aurait cassé ce
garde-fou anti-falsification).

Un candidat n'est promu (`disposition="INGEST"`,
`gate_statuses["authority"]="PASS"`) que si **toutes** les conditions
suivantes tiennent :

- `base_disposition == "INGEST"` et `disposition != "INGEST"` (un vrai
  candidat, pas encore ingéré) ;
- `gate_statuses["authority"] == "BLOCKED_NOT_CLEARED"` exactement — le
  seul état qu'un vrai compilateur produit ; toute autre valeur inconnue
  n'est jamais touchée ;
- `gate_statuses["rights"] == "PASS"` et `gate_statuses["pii"] == "PASS"`
  — l'autorité ne couvre que la porte qu'elle nomme, jamais un substitut
  pour une autre porte en échec ;
- `content_sha256` couvert par `authority_allowlist`, et bien formé
  (64 hex) ;
- `currentness == "actuel"`, chemin `.pdf`, `provenance_status ==
  "VERIFIED"`, `attribution_metadata` complet (`source`+`source_url`) —
  les mêmes faits que la boucle d'invariants de sûreté vérifie déjà pour
  tout objet `disposition=="INGEST"`, jamais contournables par
  l'autorité seule.

La boucle d'invariants de sûreté itère désormais sur cette copie promue
(`promoted_physical_objects`), pas sur `physical_objects` — elle évalue
donc correctement l'état **post-promotion**. `validate_golden_corpus`
continue de recevoir le `catalog` original, intouché.

## 3. Défaut trouvé n°2 (Finding C) — périmètre de complétude vacuement satisfait

`ingest_content_sha256`/`ingest_rights_candidates` (lignes ~1091-1113,
avant correctif) filtraient sur `item.get("disposition") == "INGEST"`.
Pour tout catalogue produit par le vrai compilateur, cet ensemble est
**toujours vide** — exactement ce que le défaut n°1 documente. Une
autorité ne nommant *aucun* `content_sha256`, ne couvrant *aucune*
catégorie de droits, passait donc la vérification `_authority_semantic_
validation` sans jamais être mise en défaut : la complétude n'était
jamais réellement exercée contre un vrai périmètre.

**Investigation avant correction** (pas supposé, vérifié) :
`git blame`/lecture de `_apply_mandatory_ingest_gates` confirment que ce
choix n'a jamais été une garantie de sûreté intentionnelle — c'est un
oubli mécanique de portée (`disposition` au lieu de `base_disposition`),
symétrique à celui déjà corrigé côté boucle de blocage
(`blocked_ingest_candidates`, qui utilisait déjà correctement
`base_disposition`). Corrigé : `item.get("disposition") == "INGEST"` →
`item.get("base_disposition") == "INGEST"` aux deux emplacements.

**Preuve empirique, pas seulement lecture** :
`test_authority_not_covering_the_real_base_disposition_ingest_candidate_
is_rejected` construit un candidat réel (`base_disposition="INGEST"`,
`disposition="REVIEW_REQUIRED"`) et une autorité qui **ne couvre pas**
son `content_sha256`. Avant le correctif : `DID NOT RAISE ValueError`
(le bug, prouvé). Après : `SEMANTIC_VALIDATION failed: the authority
allowlist does not cover ...`, exactement comme
`test_h2f_defaut5_content_not_in_authority_allowlist_fails` le prouve
déjà pour le cas — moins réaliste — où `disposition` vaut aussi déjà
`"INGEST"` dans la fixture brute.

## 4. Trois tests préexistants corrigés — le même défaut, découvert trois fois

Aucun test de sûreté n'a été affaibli. Dans chaque cas, l'assertion
originale décrivait fidèlement le comportement **d'avant ce lot** — pas
une propriété de sûreté que ce lot devait préserver — et a été corrigée
pour refléter le nouveau comportement correct, jamais pour faire passer
un test au vert par accommodement.

1. **`test_h2b_coverage_report.py::TestRightsCategoriesAreCoveredExhaustively::
   test_non_ingest_objects_are_outside_this_perimeter`** — sa fixture ne
   modifiait que `disposition` (`REVIEW_REQUIRED`), laissant
   `base_disposition` à son défaut `INGEST` : avant le correctif de
   périmètre, cela ne prouvait rien de plus que le défaut bogué
   lui-même. Corrigé pour utiliser un objet réellement hors périmètre
   (`base_disposition="EXCLUDE"`), conforme à son propre docstring
   (« Un objet EXCLUDE n'est pas publié »).
2. **`test_h2f_golden_final_gate.py::test_coverage_gate_executes_golden_
   and_separates_decision_coverage` / `test_perfect_counts_with_one_
   golden_failure_keep_coverage_red`** — la fixture `_object()` ne
   portait jamais `rights_category_candidate`, alors que l'autorité de
   test (`_authority_document`) couvre déjà `_sha(1)` et la catégorie
   `officiel_public` — champ manquant, jamais exercé avant ce lot. Le
   propre docstring de `_authority_document` affirmait « le catalogue
   golden ne route aucun objet vers l'ingestion » : vrai pour
   `disposition`, jamais pertinent pour le périmètre réel
   (`base_disposition`) que Finding C corrige. Ajouté :
   `rights_category_candidate="officiel_public"` sur le seul objet
   `base="INGEST"`.
3. **`test_h2_evidence_e2e_rehearsal.py::test_gate_correctly_blocks_the_
   real_compilers_honest_output`** — le VRAI compilateur, chaîné pour de
   vrai (`compile_governed_sealed_catalog`), ne recevait aucune
   configuration `rights_category` sur sa zone_rule ; son objet compilé
   avait donc `rights_category_candidate=None`, jamais propagé dans le
   dict reconstruit à la main pour le gate. Corrigé (config + dict) ;
   renommé `test_gate_correctly_recognizes_real_authority_over_the_
   real_compilers_output` car l'assertion originale (`blocked_ingest_
   candidates == 1`, "le gate doit refuser de le compter comme
   couvert") décrivait exactement l'absence du mécanisme que ce lot
   construit. Preuve empirique que la promotion fonctionne contre une
   **vraie** sortie de compilateur, pas seulement une fixture JSON écrite
   à la main : `blocked_ingest_candidates` passe de 1 à 0,
   `mandatory_gate_blockers == {}`, tandis que `coverage_complete` reste
   correctement faux (mode `rehearsal`, jamais vert par construction —
   propriété de sûreté inchangée, indépendante de la promotion).

## 5. Garde-fou de non-régression

```
$ .venv/bin/python -m pytest tests/test_h2b_coverage_report.py -q
112 passed   (baseline 90 — +22 nets)

$ .venv/bin/python -m pytest tests/test_h2f_golden_final_gate.py \
    tests/test_h2_evidence_e2e_rehearsal.py -q
31 passed    (0 nouveau test — fixtures corrigées uniquement)

$ .venv/bin/python -m pytest -q          # suite rag-pedago complète
2486 passed  (baseline 2464 — +22 nets, 0 régression)

$ .venv/bin/python -m ruff check \
    rag_pedago/imports/h2b_coverage_report.py \
    tests/test_h2b_coverage_report.py tests/test_h2f_golden_final_gate.py \
    tests/test_h2_evidence_e2e_rehearsal.py
All checks passed!

$ .venv/bin/python -m mypy rag_pedago/imports/h2b_coverage_report.py
Success: no issues found in 1 source file
```

Nouveaux tests ajoutés à `test_h2b_coverage_report.py` (TDD strict —
écrits rouges contre le code non modifié avant implémentation) :

- `test_real_authority_covering_a_blocked_candidate_promotes_it_to_ingest`
  (renommage + réécriture de l'ancien
  `test_expected_authority_blocked_candidate_can_pass_inert_h2_gate`,
  dont les assertions décrivaient le défaut, pas une garantie).
- `test_no_authority_evidence_at_all_leaves_the_candidate_blocked`.
- `test_authority_covers_candidate_but_rights_gate_still_blocks_promotion`
  (unitaire, direct sur `_promote_authority_cleared_candidates` — un
  scénario passant par la chaîne complète aurait nécessité de fabriquer
  une non-clairance de droits réelle dans le registre, sans rapport avec
  ce qui est testé ici).
- `test_authority_covers_candidate_but_stale_currentness_still_blocks_promotion`.
- `test_authority_not_covering_the_real_base_disposition_ingest_candidate_is_rejected`
  (garde-fou de régression Finding C).
- `TestPromoteAuthorityClearedCandidatesUnit` — 18 tests, un par branche
  conditionnelle de `_promote_authority_cleared_candidates` (baseline
  promue, allowlist vide/`None`, entrée non-dict, `base_disposition`
  hors périmètre, `disposition` déjà `INGEST`, `gate_statuses` absent,
  autorité pas exactement `BLOCKED_NOT_CLEARED`, droits/PII pas au vert,
  contenu hors allowlist, SHA malformé, actualité périmée, format non
  PDF, provenance non vérifiée, attribution absente/incomplète, contrat
  de mutation en place).

**Mutation-testing** — chaque branche neuve invertie/désactivée
temporairement (`if False:`), test dédié relancé, confirmé rouge pour la
bonne raison (jamais une autre), fichier restauré, suite reconfirmée
verte :

```
if not authority_allowlist            -> TypeError (NoneType not iterable) sur test_none_allowlist_promotes_nothing
isinstance(item, dict)                -> AttributeError sur test_non_dict_entries_are_skipped
base_disposition != "INGEST"          -> assert 1 == 0 sur test_non_ingest_base_disposition_is_not_promoted
disposition == "INGEST"               -> assert 1 == 0 sur test_already_ingest_disposition_is_left_untouched
isinstance(gates, dict)               -> AttributeError sur test_missing_gate_statuses_is_not_promoted
authority != "BLOCKED_NOT_CLEARED"    -> assert 1 == 0 sur test_authority_gate_not_blocked_not_cleared_is_not_promoted
rights != "PASS"                      -> assert 1 == 0 sur test_rights_not_pass_is_not_promoted
pii != "PASS"                         -> assert 1 == 0 sur test_pii_not_pass_is_not_promoted
content_sha256 not in allowlist       -> assert 1 == 0 sur test_content_sha256_outside_the_allowlist_is_not_promoted
SHA hex-format regex                  -> assert 1 == 0 sur test_malformed_content_sha256_is_not_promoted
currentness != "actuel"               -> assert 1 == 0 sur test_stale_currentness_is_not_promoted
path .pdf suffix                      -> assert 1 == 0 sur test_non_pdf_path_is_not_promoted
provenance_status != "VERIFIED"       -> assert 1 == 0 sur test_unverified_provenance_is_not_promoted
attribution_metadata complet          -> assert 1 == 0 (x2) sur test_missing_attribution_is_not_promoted / test_incomplete_attribution_is_not_promoted
```

Périmètre de complétude (Finding C) mutation-testé séparément : les deux
occurrences `base_disposition` restaurées à `disposition`,
`test_authority_not_covering_the_real_base_disposition_ingest_candidate_
is_rejected` repasse à `Failed: DID NOT RAISE ValueError` (le bug
reproduit exactement), `TestRightsCategoriesAreCoveredExhaustively`
(8 tests) reste vert (comportement inchangé pour ce sous-ensemble),
fichier restauré, suite reconfirmée verte.

Deux itérations de mutation-testing ont elles-mêmes révélé des défauts
dans les tests neufs, corrigés avant la version finale ci-dessus :
`test_already_ingest_disposition_is_left_untouched` masquait la
mutation de sa propre branche cible via une seconde branche (`authority
== "PASS"` déclenchait un refus plus tôt, quelle que soit la première
mutation) — corrigé en isolant le champ exact ; deux tests
`mandatory_gate_blockers` (rights, currentness) avaient une valeur
attendue erronée, corrigée après relecture du calcul réel (ce champ ne
reflète que les trois clés de `gate_statuses`, jamais `currentness` —
jamais une clé de ce dict par construction).

## 6. Ce que ce lot ne fait pas — limite honnête, pas silencieuse

- **`corpus_catalog_compiler.py` reste intouché** : le fichier catalogue
  produit par un vrai compilateur ne portera jamais lui-même
  `disposition="INGEST"` pour un candidat sous autorité — c'est
  toujours vrai après ce lot, par construction (aucune autorité réelle
  n'est jamais injectée dans ce compilateur candidat). Ce que ce lot
  change : le **gate**, en aval, reconnaît désormais qu'une preuve
  d'autorité externe réelle couvre un tel candidat, sur une copie
  jamais écrite sur disque — jamais le fichier catalogue lui-même.
- **`GOVERNED_REPUBLISH_STEP_EXISTS` reste `false`** — aucune étape
  automatisée qui réécrirait un vrai catalogue candidat en
  `disposition="INGEST"` n'existe encore dans ce dépôt (constat déjà
  documenté, `docs/reports/lot_fix_h2_evidence_workflow.md` §7). Hors
  périmètre de ce lot, qui porte spécifiquement sur le mécanisme de
  reconnaissance côté gate, pas sur la republication du catalogue.
- **`packages/contracts` et tout fichier rag-engine restent intouchés**
  — aucune évolution de contrat, aucun accès direct à pgvector.
- Aucune donnée d'autorisation réelle fabriquée ou committée — fixtures
  de test uniquement, suivant les patterns `_install_governed_root`/clé
  de test déjà établis.

## 7. Booléens finaux

```
AUTHORITY_PROMOTION_MECHANISM_BUILT=true
FINDING_C_SCOPING_DEFECT_FOUND_AND_FIXED=true
PROMOTION_FUNCTION_INDEPENDENTLY_TESTABLE=true
PROMOTION_MUTATION_TESTED=true                    # 14/14 branches, rouge pour la bonne raison, restauré vert
SCOPING_FIX_MUTATION_TESTED=true
NO_EXISTING_SAFETY_TEST_WEAKENED=true              # 3 tests corrigés, sûreté inchangée -- voir §4
CATALOG_FILE_NEVER_MUTATED=true                    # copy.deepcopy, validate_golden_corpus reçoit l'original
CORPUS_CATALOG_COMPILER_UNTOUCHED=true
CONTRACTS_PACKAGE_UNTOUCHED=true
RAG_ENGINE_UNTOUCHED=true
GOVERNED_REPUBLISH_STEP_EXISTS=false               # inchangé, hors périmètre -- voir §6
RAG_PEDAGO_FULL_SUITE_GREEN=true                   # 2486 passed, 0 failed (baseline 2464, +22 nets)
RUFF_CLEAN=true
MYPY_CLEAN=true
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
