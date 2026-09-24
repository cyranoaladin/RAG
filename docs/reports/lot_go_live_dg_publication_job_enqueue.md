# Lot DG — mettre en file la publication d'une release attestée

- Branche : `go-live/dg-publication-job-enqueue`
- Base : `5c69c0416c554b9fc1fecf0554cbef6327dd2d6b` (main après #257)

## 1. Ce que l'exécution de DC a établi, puis où elle s'est arrêtée

Faits sur le staging, `ragdb` revérifiée **inchangée** après chaque écriture,
et identique à sa référence initiale à la fin :

| Étape | Résultat |
|---|---|
| r4 | onze enregistrées (LOT41A-V2, preuve scellée de #252 à `2590a172`, 479 contenus au total) |
| `sealed_ingestion_v4` | `runs=11 resources=479 candidates=479 artifacts=479 workflow_events=4790 terminal_state=NEEDS_REVIEW published_rows=0` |
| `batch_review_proposal` | 479 projections ; artefact `…-19ba49a2….json` (#257) |
| `batch_review_record` | après approbation de #257 : `RELEASE_BATCH_ATTESTATIONS_RECORDED written=479` ; #257 fusionnée (`5c69c041`) |
| `worker_b_publication` | Worker B a démarré en `RELEASE_BOUND_STAGING_QUALIFICATION` (attestation `ingestion_control_app` OK) **et n'a rien eu à faire** |

**Cause.** Worker B ne publie que ce que lui désignent des jobs
`publication_resume`. Or aucune opération du plan ne les créait, et le dépôt
n'avait aucun outil pour le faire : le banc les créait par un utilitaire de
test (`creer_les_jobs`), en superutilisateur. Le conteneur, inactif, a été
arrêté (arrêt de sécurité prévu par le plan). L'étape n'a pas été marquée :
0 job, 0 placement, 0 chunk ; les 479 attestations restent actives.

Créer ces jobs est une écriture que l'autorisation DC ne nommait pas. Elle
n'a donc pas été faite hors autorisation.

## 2. Ce que la PR ajoute

| Pièce | Rôle |
|---|---|
| `scripts/go_live/staging_v4_enqueue_publication.py` | un job `publication_resume` par attestation batch **active** de la release nommée, sur ressource `NEEDS_REVIEW`, dans la collection de l'attestation, pour l'artefact de la release. Le job nomme ce que Worker B exige : ressource, run, version d'état, attestation, artefact. Idempotent (`find_or_create_job`, clé `publication:<attestation>`) ; une ressource déjà publiée n'est pas remise en file ; compte exact exigé, sinon rien n'est validé. Rôle `ingestion_control_app` vérifié : **aucun droit nouveau** (ce rôle a déjà `INSERT` sur `jobs`). |
| autorisation (DG, remplace DC `c2b41000…`, non consommée) | nouvelle opération `publication_job_enqueue` (rôle applicatif, `publication_resume`, 479 jobs attendus), entre l'attestation et Worker B |
| orchestrateur | étape de mise en file : dépôt de l'hôte au commit autorisé, outil exécuté depuis `/repo` dans l'image worker épinglée, avec le seul fichier `ingestion-control-app.env` |
| Worker B | conteneur **détaché et nommé** (`nexus-v4-worker-b`) : ni session SSH longue, ni plafond d'outil. L'orchestrateur suit son état, exige `exited 0` et le mode qualifié, récupère le journal, puis retire le conteneur. `--max-iterations` = jobs + 3, comme au banc ; un conteneur de ce nom déjà présent est un refus. |
| boucle `run` | se termine en succès sans `--until` (défaut latent, jamais atteint jusqu'ici) |
| banc réel V4 | crée désormais ses jobs par **cet outil**, sous le rôle applicatif. Il vérifie aussi qu'un compte faux est refusé et qu'un rejeu ne recrée rien. |

## 3. Épreuves

- `test_staging_v4_enqueue_publication.py` : charge utile exacte, rejeu,
  ressource déjà publiée, compte différent refusé, ressource hors revue
  refusée, attestation en double refusée, filtre de release et de collection.
- `test_staging_v4_orchestrator.py` :
  - essai à blanc au-delà de l'attestation ;
  - mise en file sous le seul rôle applicatif ;
  - Worker B détaché, nommé et borné (`--max-iterations 482`) ;
  - suivi exigeant la sortie nulle et le mode qualifié.
- Autorisation : la mise en file n'accepte que le rôle applicatif, 479 jobs,
  V4 et la base dédiée.
- 223 tests V4 et 644 tests de qualification réussis ; unicité des autorités,
  verrous de gouvernance et `ruff` conformes.
- Banc réel V4 (`test_v4_staging_direct_real_chain.py`) : 10 réussis sur 10
  (25 minutes). Les jobs sont créés par l'outil sous `ingestion_control_app` :
  `crees=60`, puis un rejeu donne `deja_en_file=60` ; un compte faux est
  refusé. Worker B les publie tous ; l'identité des chunks et la sonde de
  retrieval sont conformes.

## 4. Après fusion

L'exécution reprend à `publication_job_enqueue`. Les étapes faites ne sont pas
rejouées. Viennent ensuite Worker B, puis la vérification indépendante et la
sonde de retrieval.
