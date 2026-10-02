# Lot go-live — garde « aucun Worker B actif » avant la migration 020

## Constat (staging, 2026-10-02)

`successor_control_schema_020_and_adopter_role` a refusé avant toute écriture :
`WORKER_ACTIF : aucune migration pendant un Worker`. La garde faisait
`docker ps -q --filter name=worker`, c'est-à-dire « tout conteneur dont le nom contient `worker` ».
Trois services sans rapport sont actifs sur ce serveur : `rag_worker`, `math-correction-worker-1`,
`nexus-npc-worker-prod`. Aucune connexion n'était ouverte sur `ragdb_profile_gate_v4` et les anciens
Worker B V4 (`nexus-v4-worker-b`, `-dh`, `-di-1`) étaient arrêtés.

## Correctif

`scripts/go_live/worker_b_guard.py` lit le `docker inspect` des conteneurs en cours et refuse si l'un
d'eux est un Worker B de publication, identifié par :

- l'image du runtime de publication (`rag-multilevel-worker-production`, tout digest) ;
- le module lancé (`multilevel_publication_resume_cli`) ;
- les noms canoniques (`nexus-v4-…worker-b`, `nexus-hggsp-…worker-b`).

Un Worker B renommé est donc identifié par son image ou son module. Un service sans rapport ne bloque pas.

Refus par défaut (code 5) : sortie illisible, entrée vide, conteneur sans `Config`/nom, champ de forme
inattendue. L'orchestrateur refuse aussi si `docker ps` ou `docker inspect` échouent (`set -euo pipefail`).
Toutes les autres gardes de l'étape (disque, sauvegarde lisible, `pg_restore --list`) sont inchangées.

## Provenance

Le script s'exécute depuis `/repo`, monté en lecture seule sur le checkout de `AUTH_COMMIT` ; il n'est dans
aucune image. Ni l'autorisation #270, ni le runbook, ni la provenance des images ne lient
`staging_hggsp_complementary.sh` ou `worker_b_guard.py` par empreinte : `FICHIERS_FUSION_HGGSP` exige
seulement l'identité avec `origin/main`. Aucun rebuild n'est requis.

## Qualification

`scripts/qualification/tests/test_worker_b_guard.py` (29 tests, hermétiques : ni Docker, ni SSH, ni orchestrateur) :
les trois services sans rapport ne bloquent pas ; les cinq noms de Worker B bloquent ; un Worker B renommé est
identifié par son image ou son module ; toute inspection ambiguë est refusée ; l'étape ne contient plus le
filtre par nom et place la garde avant la sauvegarde.
Validé en lecture seule sur le serveur réel : conteneurs en cours → autorisé ; les trois Worker B arrêtés → identifiés.
