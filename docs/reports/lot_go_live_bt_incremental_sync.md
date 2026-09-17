# Lot BT — Qualification de la synchronisation incrémentale (SYNC_INCREMENTALE)

- Lot : `LOT_GO_LIVE_FINAL_BT_QUALIFY_INCREMENTAL_SYNC`
- Branche : `go-live/qualify-incremental-sync` — base `ca2a2e7395226aececcf910f982e5c91090850cd`
- Décision : `GO_LIVE_BT_PR_OPEN`
- Preuve scellée : `docs/reports/evidence/incremental_sync_proof.json` (`630a6a4c71e8ff5d48042afbff87a572a02873bea82f58e796b5b06f179500f6`), statut `VERIFIED`.

## Ce que « synchronisation incrémentale » veut dire dans ce modèle métier

Le magasin produit est **append-only** : le rôle publisher n'a que `SELECT, INSERT` sur `rag_artifacts`,
`rag_artifact_placements`, `rag_chunks` (`provision_runtime_roles.sh`), et `artifact_id = content_sha256`
(contrainte SQL). Il n'existe **ni remplacement, ni supersession, ni retrait** : aucune colonne, aucun code, aucun
privilège. Le moteur legacy `drive_sync.py` (SQLite, V1) n'est pas servi par le go-live et n'a pas été exercé :
le qualifier aurait prouvé la synchronisation d'un moteur que personne ne déploie.

Le lot prouve donc ce qui existe, et déclare ce qui n'existe pas, sans rien mettre en scène.

**Point soumis au relecteur humain** : le mandat listait une « modification contrôlée d'un contenu » sans condition.
Le modèle ne sait pas modifier ; ce qui est prouvé est que des octets modifiés servis par une source connue sont
**refusés avant tout stockage** et que le magasin reste identique. Si l'exigence produit est un vrai remplacement de
contenu servi, c'est une fonctionnalité à construire (ADR), et ce lot ne la couvre pas.

## Banc réel

`services/rag-engine/tests/integration/test_incremental_sync.py` — PostgreSQL/pgvector éphémères (plan de contrôle et
produit), pipeline gouverné réel (`create_job → worker A → attestation CLI → publication_resume → governed_publisher_v2`),
embeddings E5 réels, release multilevel scellée (`6ec1a4f8…`), aucun mock. Les règles du vérificateur ont été
commitées **avant** la mesure (`1f95cae4` sur la branche de mesure).

| Étape | Observation |
|---|---|
| État vierge | 0 artefact, 0 placement, 0 chunk |
| 1. État initial (8 collections) | 9 artefacts, 9 placements, **279 chunks** = attendu ; ensemble de `chunk_id` = attendu ; 9 embeddings ; release complète **non prête** (3 blocages) : le détecteur de perte voit bien l'état partiel |
| 2. Modification (octets altérés, même source) | source refetchée 1 fois, **refus** `[content] … not in authorization … allowed_content_sha256` ; 0 stockage au plan de contrôle, 0 dans le produit, magasin identique |
| 3. Run incrémental (les **11** sources resoumises) | 11 artefacts, 11 placements, **353 chunks** ; release complète **prête** ; exactement **2** publications (le delta), toutes embeddées ; 0 source de la vague 1 refetchée ; **digest des lignes existantes inchangé** |
| 4. Run répété (11 publications rejouées) | 11 × `succeeded`, **0 ré-embedding** ; magasin strictement identique |
| 5. Retrait | non prévu par le modèle ; privilèges publisher constatés : `INSERT, SELECT` uniquement |
| Doublons | 0 sur `artifact_id`, `placement_id`, `chunk_id`, et 0 ressource dupliquée au plan de contrôle |
| Reset | conteneurs détruits, **0 résidu** compté après sortie de pytest |

## Limites observées (consignées, non masquées)

- **Pas de saut gracieux** : les 9 sources déjà synchronisées, resoumises à l'aveugle, sont rejetées par la contrainte
  `resources_collection_dedup_key_unique` et leurs jobs passent en `retried`. Aucun effet sur le produit, mais du bruit
  au plan de contrôle. Une synchronisation d'exploitation doit passer par `find_or_create_job` / `create_job_cli`
  (idempotents) ou différencier la liste des sources, pas resoumettre en bloc.
- La tentative de modification laisse une ressource `CANDIDATE` et un job en `retried` au plan de contrôle.
- Le delta est une seconde vague de contenus **déjà nommés par les autorités scellées** ; ajouter un contenu inédit
  exige de reconstruire la release (hors périmètre, cf. C1).

## Câblage

`verifier_sync_incrementale` recalcule le verdict depuis les observations brutes. Refus : preuve absente, altérée,
stale, non `VERIFIED`, mock, environnement non vierge, perte (cardinalités, release non prête, ensemble de `chunk_id`),
détecteur de perte vacant, doublon, dérive de digest de l'existant, delta inexact, ré-embedding, run répété non
idempotent, contenu modifié parvenu au produit, append-only non démontré, résidus, production touchée. 20 épreuves.

La mesure a été prise sur la base `52f80f6c` ; `main` a avancé par #211 **sans aucun changement** dans
`services/rag-engine/src` ni `packages` (diff vide vérifié).

## Readiness

`go_live_qualification_blockers` : 5 → **4**. `GO_LIVE_READY=false`, `--assert-ready=1`, `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
Restent ouverts : C1, STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION.
