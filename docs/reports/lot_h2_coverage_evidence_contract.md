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
249 passed in 1.03s

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

Couverture adversariale contrat `H2CoverageEvidenceV1` (34 tests
`packages/contracts`, dont 20 dédiés) : canonicalisation déterministe et
insensible à l'ordre des champs d'entrée ; round-trip via le parseur
strict ; **champ inconnu → refusé** ; **champ manquant → refusé** ;
**`protocol_version` erroné → refusé** ; **environnement non-production
→ refusé** ; **`git_commit` mal formé → refusé** ; **`manifest_sha256`
mal formé → refusé** ; **`input_file_digests` vide → refusé** ;
**statut de gate hors énumération réelle → refusé** ; **total négatif →
refusé** ; **JSON malformé/non-UTF8/non-objet → refusé** ; **octets non
canoniques → refusés** ; **digest malformé dans `input_file_digests` →
refusé** ; **bascule de `h2_coverage_gate_pass` → digest change** ;
**changement de `manifest_sha256` → digest change**. Registre de
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
