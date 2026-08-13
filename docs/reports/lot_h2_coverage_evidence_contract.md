# LOT — Preuve H2 machine-lisible et registre de révocation partagés (ADR-0042)

## 1. Verdict du lot

Implémentation de l'ADR-0042 (Proposé — non Accepté, review humaine
requise séparément, même précédent qu'ADR-0035/ADR-0036). Deux
structures de représentation nouvelles dans `packages/contracts`
(`nexus-contracts` 0.11.0 → 0.12.0, additif, aucune rupture) :

- `NEXUS-H2-COVERAGE-EVIDENCE-V1` — projection stricte et canonique du
  sous-ensemble pertinent de `CoverageReport` (H2-B), consommée par
  `rag-engine` (intégration différée, §7).
- Registre de révocation partagé (`NEXUS-AUTHORIZATION-REVOCATIONS-V1`) —
  migration du parseur strict complet, précédemment dupliqué en version
  affaiblie dans PR #100.

`rag-pedago` (`h2b_coverage_report.py`) est mis à jour pour (a) déléguer
au parseur de révocation partagé au lieu de son ancien parseur privé
(comportement identique, prouvé par les 87 tests historiques inchangés),
et (b) émettre, en plus du rapport Markdown existant (jamais à sa place),
la nouvelle preuve JSON canonique via un nouveau flag `--json-output`.
**Aucun nouveau calcul de gate.** `GO_LIVE_READY` reste `false`. Aucune
mutation live.

## 2. Pourquoi maintenant

Deuxième des deux blockers explicitement identifiés pour PR #100
(`GOVERNANCE_EVIDENCE_SEMANTICALLY_VERIFIED=false`) : le signer hache
`catalog`/`sealed_manifest`/`h2b_report` sans jamais les revérifier
sémantiquement. `catalog` et `sealed_manifest` ont déjà des
producteurs/parseurs canoniques ; `h2b_report` n'existait qu'en Markdown.
ADR-0001 interdisant à `rag-engine` d'importer du code métier
`rag-pedago`, la solution est une représentation partagée dans
`packages/contracts` — déjà la frontière existante pour
`production_readiness.py`/`review_binding.py` — jamais un déplacement de
calcul pédagogique.

## 3. Deux bugs réels trouvés et corrigés pendant ce lot, avant tout commit

**Bug 1 — statuts de gate inventés, pas vérifiés contre le producteur
réel.** Le premier jet de `H2CoverageEvidenceV1` déclarait
`rights_gate_status`/`pii_gate_status` comme `Literal["PASS", "FAIL",
"UNKNOWN"]` — une convention supposée, jamais lue dans le code réel.
Vérifié avant d'aller plus loin :

```
$ grep -n 'rights_gate_status\s*=\|pii_gate_status\s*=' h2b_coverage_report.py
rights_gate_status = ("PASS" if ... else "BLOCKED_INGEST_WITHOUT_CLEARANCE")
pii_gate_status = ("PASS" if ... else "BLOCKED_INGEST_WITHOUT_CLEARANCE")
```

Le producteur réel n'émet jamais `"FAIL"` ni `"UNKNOWN"` pour ces deux
champs. Corrigé en `Literal["PASS", "BLOCKED_INGEST_WITHOUT_CLEARANCE"]`
— la première intégration réelle aurait échoué la validation dès le
premier rapport passant, si ce n'avait pas été vérifié maintenant.

**Bug 2 — `input_files` n'est pas uniformément une carte de digests.**
`CoverageReport.input_files` fusionne aussi
`{f"authority_{key}": value for key, value in authority_binding.items()}`
— chemin canonique, SHA-1 de blob Git, identifiant d'autorisation, login
de relecteur : aucun de ces champs n'est un digest SHA-256. Un premier
jet naïf qui aurait copié `input_files` tel quel dans
`input_file_digests` (un champ strictement typé `dict[str, digest
hex64]`) aurait soit fait échouer la validation, soit — pire — accepté
silencieusement des valeurs non-digest si le champ avait été moins
strict. Corrigé par une liste explicite des clés connues comme provenant
réellement de `_file_sha256()` (`catalog`, `pii`, `rights`, `routing`,
`authority`, `authority_revocations`, `golden`), le contrat lui-même
refusant en fail-closed toute forme non-hex64 restante (y compris
`"file_not_found"`, que `_file_sha256` peut renvoyer pour un chemin
optionnel fourni mais absent). Les deux bugs sont couverts par des tests
dédiés, mutation-testés (§5).

## 3bis. Deuxième round Codex — deux vulnérabilités structurelles réelles, corrigées

Après un premier passage CI vert (10/10), Codex a signalé deux
faiblesses P1 sur `H2CoverageEvidenceV1`, toutes deux vérifiées contre
le producteur réel avant correction :

**Finding 1 — un verdict de succès global n'était pas lié à ses propres
prérequis.** Rien n'empêchait un document de déclarer
`h2_coverage_gate_pass=true` tout en enregistrant, dans le même
document, `coverage_complete=false` ou `rights_gate_status=
"BLOCKED_INGEST_WITHOUT_CLEARANCE"` — une preuve falsifiée ou
substituée aurait pu revendiquer un succès contredit par ses propres
champs. Vérifié contre le producteur réel
(`h2b_coverage_report.py:~1284-1294`) :

```python
h2_coverage_gate_pass = (
    decision_coverage_complete
    and golden_pass
    and rights_gate_status == "PASS"
    and pii_gate_status == "PASS"
    and authority_review_binding_verified
    and authority_revocations_checked
    and final_mode
    and all(value == 0 for value in safety_invariants.values())
)
```

Corrigé par un `model_validator(mode="after")`
(`_gate_pass_implies_its_own_prerequisites`) qui refuse tout document où
`h2_coverage_gate_pass=true` contredit l'un des six prérequis qu'il
représente — une cohérence structurelle entre verdicts déjà rendus,
jamais un recalcul du gate lui-même (ADR-0001 respecté).

**Finding 2 — `input_file_digests` n'exigeait qu'une seule clé
arbitraire.** La seule contrainte (`min_length=1`) laissait passer
`{"placeholder": <hex64>}` : un document formellement valide mais lié à
aucune des quatre preuves d'entrée qu'il prétend représenter
(`--catalog`/`--routing`/`--rights`/`--pii`, toutes obligatoires côté
producteur `argparse`, jamais optionnelles). Corrigé par
`_REQUIRED_INPUT_FILE_KEYS = frozenset({"catalog", "routing", "rights",
"pii"})` et un second `model_validator(mode="after")` qui refuse toute
`input_file_digests` où l'une des quatre clés manque.

Les deux validateurs sont mutation-testés directement (désactivation
temporaire de chacun → les tests dédiés de `TestCrossFieldConsistency`
passent au rouge comme attendu → restauration → suite repassée verte) :

```
$ python3 -m pytest -q tests/test_h2_coverage_evidence_contract.py -k TestCrossFieldConsistency
11 passed
# (mutation 1 désactivée : 2 tests rouges — clé requise manquante /
#   clé arbitraire seule — restaurée, verte)
# (mutation 2 désactivée : 6 tests rouges — un par prérequis testé
#   individuellement via parametrize — restaurée, verte)

$ cd packages/contracts && python3 -m pytest -q
260 passed in 1.09s

$ python3 -m ruff check src/nexus_contracts/h2_coverage_evidence.py \
    tests/test_h2_coverage_evidence_contract.py
All checks passed!

$ python3 -m mypy src/nexus_contracts/h2_coverage_evidence.py
Success: no issues found in 1 source file

$ cd services/rag-pedago && .venv/bin/python -m pytest tests/test_h2b_coverage_report.py -q
90 passed in 1.26s
# Le producteur réel satisfait déjà les deux nouveaux invariants —
# vérifié, pas supposé.
```

## 3ter. Troisième round Codex — la même faiblesse structurelle, plus profonde

Une seconde revue fraîche sur le HEAD `225040c` a signalé un troisième
finding P1, distinct des deux premiers (les deux autres commentaires de
cette revue étaient des ré-ancrages GitHub du round 1, déjà corrigés —
distingués via `pull_request_review_id`, même discipline que PR #102/
#103).

**Finding 3 — `coverage_complete` ne peut jamais faire office de preuve
indépendante.** Le validateur du round 1 vérifie `self.coverage_
complete` comme l'un des prérequis de `h2_coverage_gate_pass=true`.
Mais vérifié dans le producteur réel (`h2b_coverage_report.py`,
construction de `CoverageReport`) :

```python
h2_coverage_gate_pass = (
    decision_coverage_complete and golden_pass and rights_gate_status == "PASS"
    and pii_gate_status == "PASS" and authority_review_binding_verified
    and authority_revocations_checked and final_mode
    and all(value == 0 for value in safety_invariants.values())
)
...
coverage_complete=h2_coverage_gate_pass,   # <- pas decision_coverage_complete
```

Le champ nommé `coverage_complete` sur `CoverageReport` est en réalité
`h2_coverage_gate_pass` lui-même — jamais `decision_coverage_complete`
(la vraie conjonction brute `sum_equals_total and zero_overlap and
zero_gap and corpus_match`). Et `report_to_h2_coverage_evidence` copie
ce champ tel quel. Conséquence : dans toute donnée réelle,
`evidence.coverage_complete == evidence.h2_coverage_gate_pass` toujours
— un contrôle qui compare une valeur à elle-même ne peut jamais détecter
d'incohérence. Un document falsifié pouvait donc déclarer
`h2_coverage_gate_pass=true` avec `coverage_complete=true` (cohérents
l'un avec l'autre, donc acceptés par le round 1) tout en portant
`corpus_match=false` ou des totaux de corpus différents — sans jamais
être détecté.

Corrigé en exigeant, en plus des six prérequis du round 1, que
`corpus_match`, `sum_equals_total`, `zero_overlap`, `zero_gap` soient
tous vrais et que `corpus_total_expected == corpus_total_actual`
lorsque `h2_coverage_gate_pass=true` — les quatre sous-vérifications
brutes dont `decision_coverage_complete` est la conjonction côté
producteur, indépendamment de ce que porte `coverage_complete`. Un test
dédié (`test_gate_pass_true_with_coverage_complete_true_but_a_false_
subcheck_is_rejected`) exerce précisément le cas où `coverage_complete=
true` mais `corpus_match=false`, pour prouver que ce round ne se
contente pas de redemander la même chose que le round précédent.

```
$ cd packages/contracts && python3 -m pytest -q tests/test_h2_coverage_evidence_contract.py
37 passed in 0.40s

$ python3 -m pytest -q
266 passed in 1.05s
```

Les cinq nouveaux conjoints (`corpus_match`, `sum_equals_total`,
`zero_overlap`, `zero_gap`, égalité des totaux) sont mutation-testés un
par un (retrait individuel de chacun → au moins un test dédié passe au
rouge → restauré → suite repassée verte).

```
$ cd services/rag-pedago && .venv/bin/python -m pytest tests/test_h2b_coverage_report.py -q
90 passed in 1.38s
# Le producteur réel satisfait déjà ce troisième invariant aussi.

$ cd ../.. && bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).
```

## 4. Ce que ce lot ne fait pas

- N'intègre pas le signer (`sign_production_readiness_manifest_cli.py`,
  PR #100) à ces deux contrats — commit séparé, après acceptation
  d'ADR-0042 (§7).
- Ne déplace aucun calcul pédagogique (`_derive_rights_clearances`,
  `_derive_pii_clearances`, `verify_catalog_evidence_bindings`) hors de
  `rag-pedago` — ADR-0001 respecté explicitement.
- Ne modifie la sémantique d'aucun champ existant de `CoverageReport` ni
  d'aucun contrat déjà publié.

## 5. Tests — résultats exacts

```
$ cd packages/contracts && python3 -m pytest -q
266 passed in 1.05s

$ python3 -m ruff check src/nexus_contracts/authorization_revocations.py \
    src/nexus_contracts/h2_coverage_evidence.py \
    tests/test_authorization_revocations_contract.py \
    tests/test_h2_coverage_evidence_contract.py
All checks passed!

$ python3 -m mypy src/nexus_contracts/authorization_revocations.py \
    src/nexus_contracts/h2_coverage_evidence.py
Success: no issues found in 2 source files

$ cd services/rag-pedago && .venv/bin/python -m pytest tests/test_h2b_coverage_report.py -q
90 passed in 1.27s
# (87 historiques, inchangés — preuve que la délégation du parseur de
# révocation est bien comportementalement identique — + 3 nouveaux)

$ .venv/bin/python -m pytest tests/test_h2b_coverage_report.py tests/test_h2f_manifest_and_rights_exactness.py tests/test_h2f_golden_final_gate.py -q
120 passed in 1.52s

$ .venv/bin/python -m ruff check rag_pedago/imports/h2b_coverage_report.py tests/test_h2b_coverage_report.py
All checks passed!

$ .venv/bin/python -m mypy rag_pedago/imports/h2b_coverage_report.py
Success: no issues found in 1 source file

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source <chaque fichier modifié> --no-git   (×7)
no leaks found (×7)
```

Couverture adversariale contrat `H2CoverageEvidenceV1` (31 tests dédiés
dans `tests/test_h2_coverage_evidence_contract.py`, 260 au total pour
`packages/contracts`) : canonicalisation déterministe et insensible à
l'ordre des champs d'entrée ; round-trip via le parseur strict ; **champ
inconnu → refusé** ; **champ manquant → refusé** ; **`protocol_version`
erroné → refusé** ; **environnement non-production → refusé** ;
**`git_commit` mal formé → refusé** ; **`manifest_sha256` mal formé →
refusé** ; **`input_file_digests` vide → refusé** ; **statut de gate
hors énumération réelle → refusé** ; **total négatif → refusé** ;
**`input_file_digests` privé d'une des quatre clés requises (ou ne
portant qu'une clé arbitraire) → refusé** ; **`h2_coverage_gate_pass=
true` incohérent avec l'un de ses six prérequis → refusé (6 cas
paramétrés, un par prérequis)** ; **JSON malformé/non-UTF8/non-objet →
refusé** ; **octets non canoniques → refusés** ; **digest malformé dans
`input_file_digests` → refusé** ; **bascule de `h2_coverage_gate_pass`
→ digest change** ; **changement de `manifest_sha256` → digest
change**. Les deux nouveaux validateurs structurels sont mutation-testés
directement (§3bis). Registre de
révocation partagé (14 tests) : comportement identique à l'ancien
parseur privé, canaris de mutation portés fidèlement (clé inconnue,
protocole erroné, ID non-liste/non-chaîne/vide/espaces, doublon).

Côté `rag-pedago`, deux garde-fous propres à la projection
mutation-testés directement : le refus hors environnement production
(retirer la condition → le test `test_rehearsal_report_is_refused`
échoue) et le filtrage des clés non-digest (le retirer → les deux tests
concernés échouent, l'un parce que le contrat refuse un digest malformé
en aval, prouvant que la protection est réellement nécessaire et pas
seulement décorative). Suite repassée verte après chaque retrait de
mutation.

## 6. Réutilisation du parseur de révocation — preuve de non-régression

`_parse_revocation_registry` (nom et signature conservés pour ne rien
changer aux appelants existants) délègue désormais entièrement à
`nexus_contracts.authorization_revocations.parse_revoked_authorization_
ids`. Les 87 tests historiques de ce fichier (dont plusieurs testent
explicitement les messages d'erreur exacts, ex.
`match="REVOCATION_REGISTRY_INVALID.*repeats"`) passent sans
modification — preuve que le comportement du parseur partagé est
byte-for-byte identique à l'ancien, pas seulement « suffisamment
proche ».

## 7. Prochaines étapes (hors de ce lot)

1. Trusted-human review + merge d'ADR-0042 (documentaire, comme
   ADR-0035/ADR-0036) — un lot séparé, après ce lot.
2. Intégration du signer PR #100 (commit séparé) :
   `sign_production_readiness_manifest_cli.py` remplace son parseur de
   révocation minimal par `nexus_contracts.authorization_revocations`,
   et parse/vérifie `--h2b-report-file` avec
   `nexus_contracts.h2_coverage_evidence.parse_h2_coverage_evidence`,
   exigeant `h2_coverage_gate_pass=true` avant signature.
3. Lot B (déploiement wrapper hôte) continue en parallèle,
   indépendamment de celui-ci.

## 8. Booléens finaux

```
NEXUS_CONTRACTS_VERSION=0.12.0
H2_COVERAGE_EVIDENCE_PROTOCOL=NEXUS-H2-COVERAGE-EVIDENCE-V1
AUTHORIZATION_REVOCATIONS_SHARED=true
CATALOG_CANONICAL=true   # producteur préexistant, non modifié ici
SEALED_MANIFEST_CANONICAL=true   # producteur préexistant, non modifié ici
H2_EVIDENCE_CANONICAL=true
REVOCATION_REGISTRY_STRICTLY_VERIFIED=true   # côté rag-pedago ; intégration signer différée (§7)
RAG_ENGINE_TO_RAG_PEDAGO_IMPORT=false   # ADR-0001 respecté
GOVERNANCE_EVIDENCE_SEMANTICALLY_VERIFIED=false   # reste false tant que §7.2 n'est pas fait
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
