# Lot DA — les onze autorisations r4 de publication de V4

- Branche : `go-live/r4-publication-authorizations`
- Base : `0569aff60092251eef691ed2a730dec3bdf7ec81` (main après #251, lot CZ)
- Fondement : ADR-0060 (autorité de publication liée au contenu) et ADR-0061
  (profils V4), acceptées par la fusion de #251.

## 1. Ce que la PR verse

Onze artefacts `governance/authorizations/lot41a-staging-v4-<collection>-r4.json`,
produits par `scripts/go_live/build_lot41a_r4_authorizations.py` (fusionné
en #251) et vérifiés par son `--check` (code 0). Rien n'est saisi à la main.

Écart de chaque r4 face à la r2 de sa collection, et rien d'autre :

| Champ | r2 | r4 |
|---|---|---|
| `protocol_version` | `LOT41A-V1` | `LOT41A-V2` |
| `allowed_content_sha256` | absent | liste positive : les placements que V4 prescrit dans la collection (479 couples au total) |
| `scope.programme_version` | `EDUSCOL_CORPUS_20260808` | référence officielle de la collection (BOEN) |
| `scope.visibility` | `public` | `internal` (visibilité servie, ADR-0045) |
| `profile_version`, `profile_fingerprint` | profil V2 | profil V4 (`v3_livraison_315`) |
| `manifest_digest` | manifeste de profils V2 | `763c2ad1…`, empreinte canonique du manifeste de profils V4 |
| `pii_absence_evidence` | release `profile_gate_v2` | release `profile_gate_v4` |
| `valid_from` | 2026-09-20 | 2026-09-24 |

Droits, domaines, exclusions et décision sont repris des r2. Les r2 restent
les autorités de l'acquisition passée et ne sont pas modifiées.

## 2. Épreuves

- Banc réel du lot CZ (`test_v4_staging_direct_real_chain.py`, 10/10) : ces
  mêmes r4, dérivées par le même générateur, enregistrées par
  `authorize_scope_cli`, puis Worker A (479 placements), revue batch,
  Worker B qualifié et retrieval ; une r2 à la place d'une r4 n'ingère rien.
- Locales sur cette branche : contrats et qualification (1 400 réussis),
  tests rag-engine lisant `governance/authorizations` (356 réussis),
  unicité des autorités PASS, verrous de gouvernance conformes. Les 4 échecs
  de `scripts/tests/test_go_live_readiness.py` tiennent au disque de la
  machine (40 Go exigés), pas à ce lot.

## 3. Ordre gouverné (enregistrer, puis fusionner)

1. Revue humaine `APPROVED` du HEAD exact de cette PR.
2. Enregistrement des onze r4 dans le plan de contrôle du staging, PR
   ouverte, par `authorize_scope_cli`. **Bloqué** : l'accès réseau au staging
   (Tailscale) est à rétablir.
3. Fusion.

Aucune écriture staging ni production n'a été faite par ce lot.
