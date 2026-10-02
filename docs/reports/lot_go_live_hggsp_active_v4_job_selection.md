# Lot go-live — sélection des anciens jobs V4 HGGSP : attestations actives seulement

## Constat (lecture seule, staging, 2026-10-02)

Le prévol `successor_readiness_install` a refusé : `anciens jobs V4 HGGSP: 148, attendu 74`.
L'observation par les fonctions canoniques du dépôt (`inspect_database`,
`prendre_instantane`), sans SQL ajouté et sans mutation, établit que ces 148 jobs sont
74 placements × 2 générations, sur la seule release V4 :

| Génération | Jobs | Attestations | Origine | Empreinte (`old_job_fingerprint`) |
|---|---|---|---|---|
| revue #257 | 74 `cancelled` | 74 invalidées | annulés puis invalidées par DH le 2026-09-26 (ADR-0033 § 5) | `4ae1a2a5…` |
| revue #262 | 74 `queued` | 74 actives | jobs recréés par DH (`recovery_job_enqueue`) | `fef6d99d…` |

`fef6d99d…` est l'empreinte épinglée par #270 et par le contrôle DI. Elle correspond
exactement à la génération #262. L'état du staging est cohérent ; l'historique #257 est conservé.

## Défaut

`inspect_database`, `enqueue_successor` et `verify_v2_lineage` joignaient `jobs` à
`publication_attestations` sans `invalidated_at IS NULL` et comptaient donc l'historique
invalidé en plus de l'ensemble actif. Le contrôle DI, lui, ne considère que les attestations actives.

## Correctif

Une seule sélection privée, `_active_v4_hggsp_jobs`, utilisée par les trois gardes. Le critère
d'appartenance est l'attestation active (`pa.invalidated_at IS NULL`) ; le statut du job n'est
pas un critère et reste dans la projection de `old_job_fingerprint`, de sorte que toute mutation
d'un des 74 jobs actifs continue de changer l'empreinte.

Inchangés : `old_job_fingerprint`, `OLD_JOBS_SHA256`, le nombre attendu 74, le runbook,
l'autorisation #270, les readiness, les autorités r4, les images et le staging.

## Provenance

`staging_hggsp_complementary.py` n'est pas dans les images : il s'exécute depuis `/repo`, monté
en lecture seule sur le checkout de `AUTH_COMMIT` (`staging_hggsp_complementary.sh`). Aucune
autorisation ne lie ce fichier par empreinte : `FICHIERS_FUSION_HGGSP` exige seulement qu'il soit
identique à `origin/main`. Aucun rebuild d'image n'est requis.

## Qualification

- test pur : les trois gardes partagent la sélection, filtrée sur l'attestation active ;
- PostgreSQL jetable (`NEXUS_HGGSP_PG=1`) : 148 jobs physiques, 74 gouvernés ; même ensemble
  que le contrôle DI ; `inspect_database`, `enqueue_successor` et `verify_v2_lineage` acceptent ce contexte
  sans modifier l'historique ; refus si une attestation active s'ajoute, manque, ou si un job actif change de statut.
