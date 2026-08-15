# Lot — Correction du périmètre requis par l'autorité (post-PR#124)

## 1. Constat traité

Audit du 2026-08-15, mené après PR#124 (réconciliation PII, réel
`base_disposition=INGEST` = 73 = 64 historiques + 9 promus par la
vérification de currentness de PR#122). Deux défauts structurels ont été
trouvés dans le calcul du périmètre que `_authority_semantic_validation`
exige d'une autorisation LOT41A-V2, avant toute correction :

### Finding #1 — périmètre figé avant promotion currentness

`generate_coverage_report` (`h2b_coverage_report.py`) et
`republish_catalog` (`catalog_republish.py`) appelaient tous deux
`ingest_candidate_facts(physical_objects)` **avant**
`_promote_currentness_verified_candidates`. Le périmètre requis par
l'autorité était donc mesuré sur l'état pré-promotion : les 9 candidats
que PR#122 promeut (`base_disposition` passe à `INGEST` après coup)
n'étaient jamais exigés d'une autorisation. Une autorisation étroite
(ne couvrant que les 64 historiques) aurait silencieusement validé sa
complétude sur un périmètre déjà obsolète, alors que 9 objets réels
restaient non couverts.

### Finding #2 — candidat bloqué PII dans le périmètre requis

`ingest_candidate_facts` sélectionnait sur `base_disposition == INGEST`
seul, sans exiger qu'aucun autre gate indépendant (rights, PII) soit déjà
au vert. Le candidat en permanence bloqué PII (1 des 73) entrait donc
dans le périmètre que l'autorité doit couvrir — alors que
`_promote_authority_cleared_candidates` refuse structurellement de le
promouvoir (il exige `gates.pii == "PASS"`) et que
`ScopeAuthorizationArtifactV2` exige `pii_absence_attested=true` sur tout
son périmètre. Aucune autorisation réelle n'aurait jamais pu satisfaire
les deux exigences à la fois pour cet objet : une contradiction
structurelle, pas seulement théorique — bien qu'inoffensive en pratique
(la promotion refusait déjà, indépendamment, de rendre ce candidat
`INGEST`), elle aurait soit bloqué en permanence toute autorisation
réelle sur la complétude, soit poussé à fabriquer une fausse attestation
d'absence de PII pour la faire passer.

## 2. Ce qui a été construit

Une primitive unique, partagée par les deux producteurs, insérée dans
`h2b_coverage_report.py` (jamais dupliquée dans `catalog_republish.py`,
qui l'importe) :

- `authority_required_candidate_facts(physical_objects)` — reprend
  **exactement** les mêmes conditions que
  `_promote_authority_cleared_candidates` (`base_disposition==INGEST`,
  `disposition != INGEST`, `authority==BLOCKED_NOT_CLEARED`,
  `rights==PASS`, `pii==PASS`, `content_sha256` hex64 valide,
  `currentness==actuel`, chemin `.pdf`, `provenance_status==VERIFIED`,
  attribution complète) — l'invariant recherché : « autorité couvre X »
  ⟺ « X sera promu ».
- `authority_required_set_digest(authority_required_sha256)` — empreinte
  canonique (SHA256 des content_sha256 triés, un par ligne, LF final),
  indépendante de l'ordre d'itération d'un `frozenset` **et** du hash
  seed de l'interpréteur (`PYTHONHASHSEED`).

Les deux producteurs sont restructurés pour appeler cette primitive
**après** toute promotion non liée à l'autorité
(`_promote_currentness_verified_candidates`), jamais avant :

- `generate_coverage_report` : nouveaux champs `CoverageReport`
  (`authority_required_count`, `authority_required_set_sha256`,
  `authority_covered_count`, `final_ingest_count`,
  `non_authority_blocked_final_count`), publiés dans le Markdown et les
  lignes `KEY=value`.
- `catalog_republish.republish_catalog` : nouveau champ
  `CatalogRepublishResult.authority_required_set_sha256`.

`non_authority_blocked_final_count` compte les candidats
`base_disposition==INGEST` bloqués par autre chose que l'autorité
(typiquement PII) — jamais confondus avec un trou dans la complétude de
l'autorisation. Le gate H2 final ne requiert **pas**
`blocked_ingest_candidates == 0` : il prouve `authority_required_count ==
authority_covered_count == final_ingest_count`, et rapporte séparément
`non_authority_blocked_final_count` comme terminal/dispositionné.

## 3. Tests

- **6 fixtures corrigées** (`test_h2b_coverage_report.py` ×5,
  `test_h2_evidence_e2e_rehearsal.py` ×1) : elles pré-fixaient
  `disposition="INGEST"` directement dans le JSON, un raccourci
  irréaliste (« déjà résolu ») qu'un vrai compilateur ne produit jamais —
  corrigées vers l'état réel (`disposition="REVIEW_REQUIRED"`,
  `gate_statuses.authority="BLOCKED_NOT_CLEARED"`).
- **`TestAuthorityRequiredCandidateFactsUnit`** (16 tests) — couverture
  par branche, une par condition, même discipline que
  `TestPromoteAuthorityClearedCandidatesUnit`.
- **`TestAuthorityRequiredSetDigestUnit`** (5 tests) — dont un test
  inter-processus qui exécute l'interpréteur avec des
  `PYTHONHASHSEED` distincts et exige un digest identique (la garantie
  réelle que `sorted()` doit fournir, invisible dans un seul processus).
- **`TestAuthorityRequiredSetTopologyABCDEF`** (7 tests) — topologie
  compacte (2 « bons » candidats stand-in pour les 72, 1 bloqué PII
  stand-in pour le 1) couvrant les 6 cas A-F spécifiés par l'audit :
  autorité ne couvrant rien (A), presque complète (B), exactement
  complète (C), nommant explicitement le candidat bloqué PII sans jamais
  le promouvoir (D), promotion sélective exacte (E), gate final PASS
  sans jamais exiger l'autorisation du contenu bloqué PII (F, exercé de
  bout en bout via `generate_coverage_report` en mode production réel).
- **Digest-equality** (`test_catalog_republish.py`) :
  `H2_AUTHORITY_REQUIRED_SET_SHA256 == REPUBLISH_AUTHORITY_REQUIRED_SET_SHA256`
  prouvé sur le même catalogue promu.
- **Régression d'ordonnancement**, deux fois — une fois dans
  `test_currentness_verification_promotion.py` (via la vraie fixture
  d'intégration currentness + `generate_coverage_report`), une fois dans
  `test_catalog_republish.py` (via `republish_catalog` +
  `currentness_verification_path`) : une autorité qui ne couvre que
  l'ancien candidat (jamais celui promu par currentness) est refusée.

Suite complète : **2575 tests passent** (+32 par rapport à la baseline
avant ce lot), `ruff check`/`mypy` propres sur tous les fichiers touchés.

## 4. Mutation-testing

Chaque branche neuve/modifiée a été désactivée puis restaurée, en
confirmant que le test attribué (et lui seul, ou un refus par ailleurs
correct) échoue pour la bonne raison :

| Mutation | Résultat |
|---|---|
| 7 conditions de `authority_required_candidate_facts` (base_disposition, disposition, authority, rights, pii, currentness, provenance) inversées une à une | **CAUGHT** — 7/7 |
| `sorted()` retiré de `authority_required_set_digest` | **CAUGHT** par le test inter-processus (hash seed) |
| Ordonnancement inversé dans `generate_coverage_report` (périmètre mesuré avant promotion currentness) | **CAUGHT** par les 2 tests de régression d'ordonnancement du fichier H2 |
| Même inversion dans `catalog_republish.republish_catalog` | **CAUGHT** — refus différent mais tout aussi fail-closed (divergence de digest catalogue détectée en aval, avant toute écriture) |

Toutes les mutations restaurées, suite complète reconfirmée verte après
chaque restauration.

## 5. Vérification contre les données réelles

Exécuté pour de vrai (`h2b_coverage_report` CLI) contre le vrai
catalogue compilé (`compile_governed_sealed_catalog`, 2584 objets), la
vraie évidence PII réconciliée (PR#124), le vrai registre de droits
(`configs/rights_evidence_registry.yml`), la vraie évidence de
currentness (`configs/prerentree_2026_2027/multilevel_currentness_evidence.yml`),
et le vrai manifeste scellé (`SEALED_MANIFEST_SHA256=d7e5caa5...`) —
**sans autorité, aucune fabriquée** :

```
BLOCKED_INGEST_CANDIDATES=73
AUTHORITY_REQUIRED_COUNT=72
AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
AUTHORITY_COVERED_COUNT=0
FINAL_INGEST_COUNT=0
NON_AUTHORITY_BLOCKED_FINAL_COUNT=1
DECISION_COVERAGE_COMPLETE=true
GOLDEN_VALIDATION_PASS=true (13/13)
H2_COVERAGE_GATE_PASS=false   # honnête -- aucune autorité fournie
```

`AUTHORITY_REQUIRED_COUNT=72` est **calculé**, jamais codé en dur —
confirme précisément la prédiction de l'audit (73 base candidates − 1
bloqué PII = 72).

Vérification indépendante du §8 (identité H2 / republish) : un script
autonome a rejoué exactement les mêmes étapes que `republish_catalog`
(promotion currentness avec droits/PII réellement réévalués, puis
`authority_required_candidate_facts` +
`authority_required_set_digest`) sur les mêmes données réelles, sans
fabriquer de campagne ni d'autorité :

```
REPUBLISH_STYLE_AUTHORITY_REQUIRED_COUNT = 72
REPUBLISH_STYLE_AUTHORITY_REQUIRED_SET_SHA256 = 3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
MATCHES_H2_REPORT_DIGEST = True
```

## 6. Constat hors périmètre — signalé, non corrigé

En exécutant le CLI avec `--json-output` mais sans `--authority`,
`report_to_h2_coverage_evidence` lève `KeyError:
'authority_authorization_id'` (`h2b_coverage_report.py:2223`, lecture de
`report.input_files["authority_authorization_id"]`, une clé qui n'est
jamais renseignée dans `input_files` quand aucune autorité n'est
fournie). Confirmé **pré-existant** à ce lot (présent à l'identique dans
`git show HEAD:.../h2b_coverage_report.py`, ligne 2062) — aucune
modification de ce lot n'y touche. Conformément à la règle d'escalade
d'AGENTS.md, ce constat est signalé ici plutôt que corrigé de ma propre
initiative : il est hors du périmètre de ce lot (projection vers
`H2CoverageEvidenceV1`, jamais touchée ici). Contournement utilisé pour
la vérification réelle du §5 : omettre `--json-output` dans un run sans
autorité (le rapport Markdown, seul concerné par ce lot, est intact).

## 7. Ce qui n'a délibérément pas changé

- Aucune autorisation LOT41A-V2 réelle n'a été créée, fabriquée ou
  réutilisée.
- Aucune campagne de republication réelle n'a été exécutée.
- Aucune écriture pgvector.
- `H2CoverageEvidenceV1`/`packages/contracts` : non touchés (nouveaux
  champs uniquement dans `CoverageReport`/Markdown pour l'instant).
- Tier A (`TIER_A_REAL_POPULATION=1252`) reste non fermé —
  `FINAL_AUTHORITY_REQUIRED_COUNT` reste `UNKNOWN` tant que Tier A n'est
  pas résolu ; `AUTHORITY_REQUIRED_COUNT=72` ci-dessus est l'état
  **courant**, pas final.
- PR#96/#98 : aucune décision prise ici.

## 8. Booléens finaux

```
AUTHORITY_REQUIRED_SET_ORDERING_FIX_APPLIED=true
AUTHORITY_REQUIRED_SET_EXCLUDES_PII_BLOCKED=true
AUTHORITY_PERIMETER_POST_CURRENTNESS=true
H2_REPUBLISH_AUTHORITY_SET_IDENTICAL=true
BASE_INGEST_CANDIDATES=73
CURRENT_AUTHORITY_REQUIRED_COUNT=72          # calculé, jamais codé en dur
CURRENT_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
NON_AUTHORITY_BLOCKED_COUNT=1
PII_BLOCKED_COUNT=1
FINAL_AUTHORITY_REQUIRED_COUNT=UNKNOWN_PENDING_TIER_A_CLOSURE
NO_REAL_AUTHORITY_CREATED=true
NO_REAL_CAMPAIGN_EXECUTED=true
FULL_SUITE_GREEN=true
FULL_SUITE_TEST_COUNT=2575
RUFF_CLEAN=true
MYPY_CLEAN=true
MUTATION_TESTED=true
VERIFIED_AGAINST_REAL_DATA=true
```
