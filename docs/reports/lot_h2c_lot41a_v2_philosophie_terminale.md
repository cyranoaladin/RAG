# LOT H2-C — Autorisation LOT41A-V2 réelle, philosophie Terminale (Phase E)

## Contexte

Phase E de la mission de production go-live demandait des autorisations
LOT41A de production réelles, "exact content/release SHA", "aucune fabrication".
PR #96 (`governance/authorizations/h2-initial-philosophie-20260809.json`,
toujours ouverte, jamais approuvée par un reviewer distinct de l'auteur)
affirme 5 artefacts PII-cleared et un digest d'ensemble
(`CLEARED_SHA_SET_DIGEST=a8fab59c...`), mais ce digest et les deux autres
valeurs citées dans son champ `pii_absence_evidence` n'apparaissent **nulle
part ailleurs** dans le dépôt — aucun fichier, aucun test, aucun script ne les
calcule ni ne les référence. Décision explicite du propriétaire du dépôt :
laisser PR #96 intacte (elle reste une décision d'autorité, pas un chantier de
remédiation) et construire une autorisation **distincte**, à partir de preuves
réellement traçables.

## Preuve traçable trouvée et vérifiée indépendamment

`services/rag-engine/configs/h2_initial_placement_policy.yml` — décision
organisationnelle humaine versionnée (`decision_type:
HUMAN_ORGANIZATIONAL_PLACEMENT_APPROVAL`, `decision_maker: Nexus Réussite`,
`decision_date: 2026-08-09`) — contient `approved_artifacts`, un mapping de 5
SHA-256 complets (64 caractères) vers leur métadonnée (source Eduscol,
`source_status: actuel`, collection `rag_nexus_philo_terminale_tc`).

Recoupements indépendants effectués avant construction de l'artefact :

- `corpus_manifest_sha256` de ce fichier (`d7e5caa5...`) == valeur
  `EDUSCOL_RIGHTS_SCOPE_MANIFEST` de
  `docs/reports/lot_h2b_production_readiness.md` == `manifest_digest` déjà
  présent dans PR #96 (V1) — cohérent sur trois sources indépendantes.
- `pii_evidence_sha256` de ce fichier (`3db37e91...`) == "preuve PII externe"
  citée en toutes lettres dans `lot_h2b_production_readiness.md` — et diverge
  du `H2B_PII_EVIDENCE_SHA256=76e6ba3c...` cité dans PR #96. **Correction
  après investigation approfondie (remédiation P1 ci-dessous)** : `76e6ba3c...`
  n'est pas fabriqué — c'est le SHA-256 réel d'un fichier machine-local
  authentique (`h2b_pii_evidence_20260808.json`, scan H2-B original du
  08/08). Mais ses agrégats (63 CLEARED, 0 extraction échouée) ne
  correspondent pas aux chiffres du rapport de production-readiness. Le
  fichier `3db37e91...` (`h2f_pii_evidence_review6_20260810.json`) est la
  révision H2-F finale, postérieure, dont les agrégats (61 CLEARED, 1
  QUARANTINED_PII) correspondent exactement au rapport canonique — c'est
  donc la bonne source, et PR #96 cite un scan superseded, pas un digest
  inventé. Les deux fichiers existent réellement sous
  `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/` (evidence H2 machine-locale,
  jamais commitée, conformément à AGENTS.md).
- Les 5 préfixes SHA-256 (12 caractères) de
  `services/rag-pedago/configs/golden_corpus_h2b.yml` (contrôles golden
  `pos_01_philosophie_evaluation` … `pos_05_philosophie_recommandations`,
  spec active, testée) correspondent exactement aux 5 clés complètes de
  `h2_initial_placement_policy.yml`.
- `profile_fingerprint` recalculé en direct via le code réel
  (`ingestor.ingestion_profiles.registry.profile_fingerprint` sur le profil
  chargé depuis `configs/ingestion_profiles/philosophie_terminale_tc_h2c_v1.yml`)
  == `993b350071ff...`, identique à la valeur déjà portée par PR #96 — cohérence
  supplémentaire, jamais recopiée à l'aveugle.

## Artefact livré

`governance/authorizations/h2c-philosophie-terminale-tc-v2-20260813.json` —
`ScopeAuthorizationArtifactV2` construit et validé round-trip via le contrat
réel (`ScopeAuthorizationArtifactV2` + `parse_scope_authorization_artifact`),
jamais assemblé à la main :

- `authorization_id`: `h2c-philosophie-terminale-tc-v2-20260813` (distinct de
  PR #96 — aucune collision, aucun chemin partagé)
- `protocol_version`: `LOT41A-V2` (dès la construction, jamais une migration
  V1→V2 de PR #96)
- `allowed_content_sha256`: les 5 SHA-256 complets ci-dessus, triés, uniques
- `scope`: identique à PR #96 (même collection, même profil réel) — le scope
  lui-même n'a jamais été le problème identifié par ADR-0034, seule la liaison
  de contenu positive manquait
- `pii_absence_evidence`: cite les chemins de fichiers réels et les digests
  vérifiés ci-dessus, jamais une valeur libre

## Portée

- Ceci **prépare** une autorisation ; elle n'est pas encore vivante. Le
  chemin d'enregistrement réel (`authorize_scope_cli.py
  record-authorization`) exige une review GitHub `APPROVED` d'un reviewer
  distinct de l'auteur sur le head exact de la PR portant ce fichier — même
  mécanisme irréductible qu'ADR-0025, non contourné ici.
- PR #96 n'est ni modifiée, ni fermée, ni dismissée par ce lot.
- Cette autorisation ne couvre que les 5 documents ci-dessus. Le reste du
  corpus scellé (2 584 objets physiques, 61 PDF `CLEARED` au total d'après
  `docs/reports/lot_h2b_production_readiness.md`) reste hors périmètre —
  seuls les 5 documents dont la trace complète (SHA individuel + décision de
  placement + digest agrégé indépendamment vérifiables) existe réellement
  dans ce dépôt ont été retenus. Étendre cette autorisation aux ~56 autres PDF
  `CLEARED` est un lot séparé, à mener seulement si leurs identités SHA-256
  individuelles sont retrouvées avec la même traçabilité.

## Remédiation Codex P1 — evidence PII vérifiable (2026-08-13)

Finding réel de `chatgpt-codex-connector[bot]` sur PR #98 : `pii_absence_evidence`
ne citait qu'un digest en texte libre ; le fichier source réel
(`$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2f_pii_evidence_review6_20260810.json`)
est machine-local, non commité — un reviewer GitHub ne pouvait ni recalculer
le digest, ni vérifier que les 5 SHA autorisés y sont réellement `CLEARED`.

Ajouts :

- `services/rag-pedago/rag_pedago/imports/pii_evidence_extract.py` — module
  pur + CLI déterministe. Relit la source octet à octet, recalcule et compare
  son SHA-256 **avant** tout parsing JSON, exige `corpus_manifest_sha256`
  identique à l'attendu, exige chacun des SHA autorisés présent avec
  `status=CLEARED`, `pii_detected=false`, `error_code=null` — refus fermé
  sinon. Ne projette que les champs déjà garantis PII-safe par
  `pii_scanner.result_to_dict_sanitized` (jamais `match_text`/`context`) et
  balaie récursivement le document produit à la recherche de toute clé
  interdite avant de le retourner.
- `services/rag-engine/configs/h2c_philosophie_terminale_tc_v2_pii_evidence.json`
  — extrait produit par cet outil (jamais écrit à la main), committable :
  aucune PII brute, digest `3697a64f36b4660a8fac172679e94b0939841ca18c16eba24837186fd84be974`.
  Les 5 SHA autorisés y apparaissent tous avec `status: CLEARED`.
- `governance/authorizations/h2c-philosophie-terminale-tc-v2-20260813.json`
  mis à jour : `pii_absence_evidence` référence désormais ce fichier committé
  (chemin + digest), plus la chaîne de dérivation complète (source externe +
  son digest + module de dérivation). `authorization_digest` recalculé via
  le contrat réel : `b134ba853bf38089ab7cce14f0261b78c5732b0d01e3a0eca04f3f46a15c741f`
  (change nécessairement, les octets ont changé).
- `services/rag-pedago/tests/test_pii_evidence_extract.py` — 13 tests :
  chemin vert, déterminisme (deux exécutions, octets identiques), et neuf
  canaris de mutation prouvant un vrai rouge (digest source erroné, SHA
  autorisé absent, statut `QUARANTINED_PII`, statut `REVIEW_REQUIRED`,
  `pii_detected=true` malgré un statut correct, scan incomplet
  (`error_code` non nul), `corpus_manifest_sha256` divergent, fuite de PII
  brute injectée dans la source (jamais reproduite en sortie), doublons/
  ensemble vide de SHA requis) — plus un test d'intégration contre le vrai
  fichier externe (skip si absent de la machine).

## Preuves

```
$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ pytest tests/test_lot41a_authority_artifacts.py tests/test_lot41a_scope_enforcement.py \
         tests/test_lot41a_github_authority_transport.py -q   # rag-engine
131 passed

$ pytest tests/test_h2b_coverage_report.py tests/test_pii_scanner.py \
         tests/test_remote_pii_scan.py tests/test_h2f_golden_final_gate.py \
         tests/test_corpus_campaign.py tests/test_pii_evidence_extract.py -q   # rag-pedago
229 passed

$ pytest packages/contracts/tests -q
215 passed

$ ruff check rag_pedago/imports/pii_evidence_extract.py tests/test_pii_evidence_extract.py
All checks passed!

$ mypy rag_pedago/imports/pii_evidence_extract.py
Success: no issues found in 1 source file

$ gitleaks detect --source . --no-git   # full repo
226 pre-existing findings, none in any file touched by this lot (verified
by name-matching the finding paths against the changed-file list)
```

## Prochaine étape (frontière humaine)

Ouvrir une review GitHub sur la PR portant ce fichier, approuvée par
`@abenrhouma` (distinct de l'auteur), sur le head exact — puis
`authorize_scope_cli.py record-authorization` peut enregistrer la décision en
base après revérification live complète. Jamais avant.
