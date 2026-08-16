# Lot — Refus typé de `report_to_h2_coverage_evidence` sans autorité

## 1. Constat

`report_to_h2_coverage_evidence` (`h2b_coverage_report.py`), la projection
d'un `CoverageReport` déjà calculé vers le contrat partagé
`NEXUS-H2-COVERAGE-EVIDENCE-V1` (ADR-0042), levait un `KeyError` brut —
`report.input_files["authority_authorization_id"]` — chaque fois qu'elle
était appelée sur un rapport produit **sans autorité fournie**
(`authority_path=None` côté `generate_coverage_report`). Confirmé
pré-existant à toute modification de ce lot (identique à `git show
HEAD:.../h2b_coverage_report.py` avant tout changement).

Reproduit concrètement via le CLI : `--json-output` sans `--authority`
crashe au lieu de refuser proprement.

## 2. Pourquoi ce n'est pas une simple validation manquante

`H2CoverageEvidenceV1.authorization_id` (`packages/contracts`) est un
champ **non-nullable** par construction (ADR-0042 round 4) : ce format de
preuve existe spécifiquement pour prouver qu'une autorité de production a
été vérifiée — jamais pour décrire une exécution qui n'en avait aucune.
Rendre ce champ optionnel aurait changé la sémantique du contrat V1 sans
ADR ni bump SemVer, ce qui n'a **pas** été fait ici.

## 3. Correctif

Un refus explicite et typé, symétrique au refus d'environnement déjà en
place trois lignes au-dessus (`H2CoverageEvidenceError`, jamais un
nouveau type d'erreur) : si `"authority_authorization_id"` est absent de
`report.input_files`, `report_to_h2_coverage_evidence` refuse
immédiatement avec un message explicite, avant tout accès dict qui
lèverait autrement un `KeyError`.

- Le rapport **Markdown** (`render_markdown`) n'a jamais exigé d'autorité
  et reste inchangé — refus strictement local à la projection JSON de
  preuve de production.
- Aucune évolution de `H2CoverageEvidenceV1` — le contrat reste
  `NEXUS-H2-COVERAGE-EVIDENCE-V1` tel quel.

## 4. Tests

- `test_production_report_without_authority_is_an_explicit_typed_refusal`
  — dataclass construite directement (même style que
  `test_rehearsal_report_is_refused`, déjà en place).
- `test_real_production_report_without_authority_path_is_refused` — vrai
  pipeline bout en bout (`generate_coverage_report` sans `authority_path`),
  exactement le scénario CLI `--json-output` sans `--authority` qui
  crashait ; confirme aussi que le rapport Markdown reste utilisable.
- Mutation-testing : la garde neuve désactivée reproduit exactement le
  `KeyError` d'origine, les deux tests neufs l'attrapent ; fichier
  restauré, suite reconfirmée verte.
- Suite complète rag-pedago : **2577 tests passent** (+2), `ruff
  check`/`mypy` propres sur le fichier touché.

## 5. Booléens finaux

```
H2_COVERAGE_EVIDENCE_NO_AUTHORITY_KEYERROR_FIXED=true
H2_COVERAGE_EVIDENCE_V1_CONTRACT_UNCHANGED=true
AUTHORIZATION_ID_MADE_NULLABLE=false
MARKDOWN_REPORT_WITHOUT_AUTHORITY_STILL_ALLOWED=true
FULL_SUITE_GREEN=true
FULL_SUITE_TEST_COUNT=2577
MUTATION_TESTED=true
```
