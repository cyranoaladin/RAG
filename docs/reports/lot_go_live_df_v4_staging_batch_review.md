# Lot DF — revue batch de publication de V4 sur le staging dédié

- Branche : `go-live/df-v4-staging-batch-review`
- Base : `80180bf029013457c73fdd0849b827882895c1d9` (main après #256)
- Autorisation d'exécution : `staging_v4_publication_authorization.json` (lot DC, #254)

## 1. L'artefact soumis

`governance/publication-reviews/lot42-release-batch-v4-staging-20260924-19ba49a2b56b3075b0f26ac75998cadcc696dab44864e6940d4f004c862279b9.json`
(2 327 octets, sha256 `19ba49a2…79b9`, égal au digest canonique). Il a été
produit par `propose-release-batch-review` sous le rôle
`ingestion_control_attestor`, sur la base dédiée `ragdb_profile_gate_v4`.
L'orchestrateur l'a extrait et vérifié au digest exact.

| Champ | Valeur |
|---|---|
| `protocol_version` / `decision` | `LOT42-RELEASE-BATCH-V1` / `AUTHORIZE_SEALED_RELEASE_PUBLICATION` |
| release | `production-profile-gate-2026-2027-v4`, manifeste `bab9c398…` |
| comptes attendus | 11 sujets, 315 artefacts, 479 placements, 8 268 chunks |
| autorisations | les onze r4 (`lot41a-staging-v4-*-r4`), et elles seules |
| placements | `official_snapshot`, `active`, `reviewed` |
| transfert / inventaire / registre | `d6cd4c22…` / `1aeda3d2…` / `9f848512…` |
| validité | du 2026-09-24T22:00:14Z au 2026-10-24T22:00:14Z |
| évaluateur | `abenrhouma` (relecteur de confiance gouverné) |

## 2. État du staging au moment de la proposition

- Base dédiée : têtes 5 et 19 ; 479 ressources en `NEEDS_REVIEW` (11 runs,
  4 790 événements) ; 479 projections ; **0 attestation, 0 placement produit,
  0 chunk**.
- `ragdb` : identique à la référence du premier pré-vol (têtes 4 et 15 ;
  479/479/26/730 ; empreintes).

## 3. Ce que l'approbation de cette PR permet

Enregistrer l'attestation batch (`record-release-batch-attestation`) au HEAD
exact de cette PR, pendant sa fenêtre de validité. Ensuite seulement : Worker
B, puis la vérification et la sonde de retrieval, toutes déjà autorisées par
#254.

Rien n'est publié tant que cette revue n'est pas approuvée et enregistrée.
