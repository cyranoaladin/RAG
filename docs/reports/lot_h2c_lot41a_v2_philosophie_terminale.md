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
  citée en toutes lettres dans `lot_h2b_production_readiness.md` — **et
  diverge du `H2B_PII_EVIDENCE_SHA256=76e6ba3c...` cité dans PR #96**, qui ne
  correspond à rien de traçable. Confirmation supplémentaire que PR #96 ne
  doit pas servir de source pour cette autorisation.
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

## Preuves

```
$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ pytest tests/test_lot41a_authority_artifacts.py tests/test_lot41a_scope_enforcement.py \
         tests/test_lot41a_github_authority_transport.py -q
131 passed

$ pytest tests/test_h2b_coverage_report.py tests/test_corpus_campaign.py -q   # rag-pedago
113 passed

$ pytest packages/contracts/tests -q
215 passed
```

## Prochaine étape (frontière humaine)

Ouvrir une review GitHub sur la PR portant ce fichier, approuvée par
`@abenrhouma` (distinct de l'auteur), sur le head exact — puis
`authorize_scope_cli.py record-authorization` peut enregistrer la décision en
base après revérification live complète. Jamais avant.
