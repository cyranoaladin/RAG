# Lot go-live — mise en file des 74 jobs successeur sous les privilèges réels du rôle applicatif

## Constat (staging, 2026-10-03)

Après l'enregistrement de la revue batch (74 attestations successeur écrites) et `successor_attestations`, `successor_publication_job_enqueue` a échoué avant toute écriture :

> `psycopg.errors.InsufficientPrivilege: permission denied for table publication_attestations` (`enqueue_successor`, `staging_hggsp_complementary.py`)

Relu en lecture seule après l'échec : 958 jobs `publication_resume` (aucun job successeur créé), 74 attestations successeur actives, 74 adoptions.

## Cause

La requête de sélection des 74 attestations adoptées se terminait par `FOR SHARE OF pa, r, ad`. Un verrou de ligne `FOR SHARE` exige, en plus de `SELECT`, le droit `UPDATE` sur chaque table verrouillée.
Le rôle applicatif (`ingestion_control_app`) a, sur le staging :

| table | privilèges de `ingestion_control_app` |
|---|---|
| `publication_attestations` | `SELECT` |
| `sealed_release_adoptions` | `SELECT` |
| `resources` | `INSERT, SELECT, UPDATE` |

La requête ne pouvait donc jamais s'exécuter sous ce rôle. Les deux tests PostgreSQL qui l'exercent accordaient `SELECT, INSERT, UPDATE` sur **toutes** les tables à ce rôle, ce qui masquait le défaut.

## Correctif

- `FOR SHARE OF pa, r, ad` devient `FOR SHARE OF r` : seule `resources`, où le rôle écrit, est verrouillée. Le périmètre sélectionné est inchangé (mêmes jointures, même filtre `invalidated_at IS NULL`).
- Raison de sécurité de ne pas verrouiller `pa` et `ad` : elles sont écrites par d'autres rôles ; une attestation invalidée entre la lecture et la publication est refusée par le claim de Worker B (jointure sur `invalidated_at IS NULL`) et par la revérification live de la revue. Le recomptage final des 74 jobs de `enqueue_successor` est conservé.
- **Autre défaut de l'orchestrateur corrigé dans le même lot** : `--evaluator "Alaeddine Ben Rhouma"` était coupé en trois arguments par la reconstruction de la commande avec `$*` (`unrecognized arguments: Ben Rhouma`), comme `--adopted-by` et `--bound-by` avant #279. Il est validé puis échappé (`arg_shell`).

## Qualification

- Les deux tests PostgreSQL utilisent désormais les **privilèges réels** du rôle : `SELECT` seulement sur les attestations, les adoptions, les artefacts et les pins ; `SELECT, INSERT, UPDATE` sur `resources` et `jobs`.
- **Rouge avant correctif** : contre le code actuel, ils échouent avec exactement l'erreur du staging (`permission denied for table publication_attestations`). **Vert après** : 41 passed (`NEXUS_HGGSP_PG=1`, PostgreSQL jetable).
- Test statique : le verrou de la requête ne nomme que `resources` (ni `pa`, ni `ad`, ni `FOR UPDATE`).
- Test de l'évaluateur : validé avant l'appel distant, échappé, aller-retour exact comme **un seul argument**.
- 185 tests des suites autorisation, supersession, orchestrateur et garde Worker B ; ruff propre ; `bash -n` propre.

Limites : le test PostgreSQL utilise un schéma réduit et un `create_job` de test ; il prouve l'accès avec les privilèges réels sur les tables de cette requête, pas l'ensemble du chemin `find_or_create_job` (qui a déjà tourné sous ce rôle pour les 479 jobs de V4). Aucune empreinte gouvernée n'est modifiée.
