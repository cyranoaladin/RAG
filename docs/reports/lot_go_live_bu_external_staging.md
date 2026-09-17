# Lot BU — Staging externe (STAGING_EXTERNE)

- Lot : `LOT_GO_LIVE_FINAL_BU_QUALIFY_EXTERNAL_STAGING`
- Branche : `go-live/qualify-external-staging` — base `7d93bff46757fc979d7645d3c4dd966b20d09739`
- **Décision : `GO_LIVE_BU_RUNBOOK_ONLY_PR_OPEN`** — STAGING_EXTERNE reste **ouvert**.
- Preuve scellée : `docs/reports/evidence/external_staging_proof.json` (`d3cdd2536b573cd0e019efb67b2073cf59b0502f982f60fe41bb73f80861b65c`), statut `RUNBOOK_ONLY_NOT_QUALIFIED`.

## Mode retenu : C — `runbook_only`

| Mode | Statut |
|---|---|
| A — `nexus-prod` cloisonné | écarté : aucune autorisation SSH explicite |
| B — hôte de staging séparé | écarté : aucun hôte ni accès désigné dans le dépôt |
| **C — runbook + contrôles locaux** | **retenu** |

La condition de fermeture est « un staging externe est ingéré puis qualifié ». Un runbook, même vérifié, n'est pas un
environnement démarré : `verifier_staging_externe` **refuse** `runbook_only`, y compris étiqueté `VERIFIED` (épreuve
dédiée). Aucune preuve d'environnement externe n'a été inventée.

**Pourquoi pas de « rehearsal local » avec conteneurs** : il n'existe sur le poste ni corpus servable ni base vectorielle
de staging, et `prepare_staging_environment.py` refuse — à raison — toute empreinte fabriquée (« en générer une
plausible fabriquerait la preuve que le runtime vérifie »). Démarrer aurait exigé d'inventer ces faits. Le démarrage
Compose isolé et le rollback de release sont par ailleurs déjà éprouvés (blocage ROLLBACK, rehearsal Docker V2).

## Ce qui a réellement été fait

- `docker compose config` sur `docker-compose.v2.yml` avec des valeurs factices non conservées et `--env-file /dev/null` :
  **le Compose se résout**. Un premier passage avait chargé implicitement un `.env` local du poste (ports 8011/5436/19092) ;
  corrigé, la preuve ne dépend plus d'aucun fichier local (ce `.env` n'a pas été lu, il est ignoré par git).
- Dérivé du Compose, jamais recopié : 3 services (`pgvector`, `ingestor`, `prometheus`) ; ports `127.0.0.1:5435`,
  `127.0.0.1:8001`, `127.0.0.1:19091` — **tous liés à la loopback** ; 21 variables requises (noms seuls) ; volumes
  `rag_pgvector_data`, `rag_prometheus_data` ; limites CPU : ingestor **2**, pgvector 2, prometheus 0,5.
- Runbook `docs/runbooks/staging_externe.md` complété de ce qui manquait : **§ 8 rollback du staging** (projet Compose
  dédié, sauvegarde, interdits `down -v` / `--remove-orphans`, critère « éprouvé »), **§ 9 Cockpit et contrôle d'accès**
  (Basic Auth ou allowlist, pas de DNS définitif, aucun secret de production), **§ 10 preuve à rapporter et état final**.
- 0 conteneur démarré, 0 hôte joint, 0 secret produit ou affiché.

## Constats utiles à l'opérateur

1. Le service `ingestor` est **construit** par le Compose (`build:`), pas épinglé par digest : le runbook exige une image
   par digest avant staging — à figer.
2. `ingestor` est limité à **2 CPU** : confirme l'alerte du lot BS (rerank ≈ 3,3 s à 2 threads ; une requête unique
   approcherait le budget de 6 s). Le staging est l'endroit où le mesurer.

## Ce que l'opérateur doit fournir pour passer en mode A ou B

Hôte distinct de la production ; nom DNS de staging + TLS ; Basic Auth ou allowlist ; image par digest ; répertoire de
corpus servables + empreinte d'index ; empreinte du registre de releases ; artefacts de modèles vérifiés.
Ensuite : runbook § 2 → § 10, et la preuve se rescelle en mode A/B avec les mesures réelles.

## Câblage

`verifier_staging_externe` refuse : preuve absente, altérée, stale, mode absent ou incohérent avec `host_kind`,
`runbook_only`, environnement non démarré ou non distinct de la production, exposition non contrôlée, rollback absent ou
non éprouvé, healthchecks/ingestion/retrieval/Cockpit manquants, 0 citation, secret dans les journaux ou exposé,
`production_db_writes`/`production_deployments`/`current_switch` ≠ 0. 12 épreuves + 4 hermétiques.

## Readiness

Inchangé : `go_live_qualification_blockers=4` (C1, STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION),
`GO_LIVE_READY=false`, `--assert-ready=1`, `pii_undecided=149`, `release_promoted_refused_contents=26`,
`current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
