# Plan d'exécution DH — reprise de la publication V4 après la fermeture de #257

Orchestrateur : `scripts/go_live/staging_v4_publication_recovery.sh`.
Outil : `scripts/go_live/staging_v4_publication_recovery.py`.
Identité de la revue périmée : `docs/reports/go_live/recovery/dh_stale_review_257.json`.
Autorisation : `docs/reports/go_live/authorizations/staging_v4_publication_recovery_authorization.json`
(**absente** tant que la PR d'activation n'est pas approuvée et fusionnée ; la
PR DH n'en porte qu'une proposition sous `authorizations/proposed/`).

## 0. Principes

- Même base dédiée `ragdb_profile_gate_v4`, mêmes ressources, mêmes artefacts,
  même projection, mêmes r4. Ni nouvelle base, ni réingestion, ni nouvelle
  release. `ragdb` mesurée au pré-vol et revérifiée après chaque écriture.
- Aucune ligne supprimée, aucun ancien job réaffecté. Anciennes attestations
  invalidées (motif `DH-RECOVERY …`), anciens jobs annulés (`payload.
  recovery_cancellation`, `last_error` de Worker B conservé).
- Rôles existants, droits existants : `ingestion_control_app` annule,
  `ingestion_control_attestor` invalide. Worker B inchangé.
- Même image worker épinglée que la V4 (aucune reconstruction) : `src/` est
  identique entre son commit de build `0569aff6` et `e8d125ea`. L'outil DH et
  la mise en file sont exécutés depuis `/repo` (dépôt de l'hôte au commit de
  l'autorisation DH) dans cette image ; ils n'importent que des primitives
  qu'elle porte déjà.
- Chaque écriture est une transaction : ensemble re-dérivé sous verrou,
  empreintes de l'aperçu exigées, compte exact exigé ; un rejeu identique
  n'écrit rien et conserve motifs et horodatages.

## 1. Étapes

| # | Étape | Rôle | Écrit | Arrêt humain |
|---|---|---|---|---|
| 1 | `recovery_preflight` | app (lecture seule) | non | **oui** : relire `preview.json`, relancer avec `DH_PREVIEW_ACK=<attestation_set_sha256>` |
| 2 | `stale_job_cancellation` | app | `jobs` (statut, bail, `payload.recovery_cancellation`) | non |
| 3 | `stale_attestation_invalidation` | attestor + jeton GitHub | `publication_attestations.invalidated_*` | non |
| 4 | `recovery_review_proposal` | attestor | projection (rejeu sans écriture) | **oui** : ouvrir une NOUVELLE PR avec l'artefact, la faire approuver au head exact, la laisser OUVERTE |
| 5 | `recovery_review_record` | attestor + jeton | 479 nouvelles attestations | non |
| 6 | `recovery_job_enqueue` | app + jeton | 479 nouveaux jobs, après `review-precondition --stage enqueue` | non |
| 7 | `recovery_worker_b_publication` | app + publisher + jeton | produit, après `review-precondition --stage worker-b` | non |
| 8 | `recovery_independent_verification` | reader | non | non |
| 9 | `recovery_review_closure_check` | app (lecture seule) | non | **oui** : fusion ou fermeture de la PR de revue, décision humaine |

## 2. Pré-vol (étape 1)

Refus si : conteneur pgvector absent ; `ragdb_profile_gate_v4` absente ; une
ligne produit (`rag_artifacts`, `rag_artifact_placements`, `rag_chunks`) dans
la base dédiée ; un conteneur Worker B **en cours** (`nexus-v4-worker-b`,
`nexus-v4-worker-b-dh`) ; manifeste de transfert V4 de l'hôte différent de
celui consigné par l'exécution V4 ; jeton GitHub absent ou mal protégé.

Un conteneur Worker B **arrêté** est conservé (preuve) ; son journal est
recopié dans l'état DH. Worker B relancé porte un autre nom
(`nexus-v4-worker-b-dh`) : l'ancien n'est jamais retiré par DH.

Puis `preview` : refus au moindre écart (liste complète dans `preview.json`) —
mauvaise base, identité de revue, release ou empreinte différentes, ligne
étrangère, ressource hors `NEEDS_REVIEW`, bail de ressource ou de job ACTIF,
pin de commit ou job `succeeded` sous #257, compte différent de 479.

Un bail de job **expiré** n'est pas une annulation : il est constaté
(`running_lease_expired`) puis annulé explicitement à l'étape 2, jamais
réclamé à nouveau (Worker B, qui moissonne les baux expirés à chaque
itération, reste arrêté jusque-là).

## 3. Cycle de vie de la nouvelle revue

- Les r4 (LOT41A-V2) sont des preuves **scellées** : la fusion de #252 ne les
  affecte pas.
- L'attestation batch exige une revue GitHub vérifiée **en direct** à chaque
  usage (ADR-0033 § 5, inchangé) : la nouvelle PR reste ouverte, approuvée au
  head exact et inchangée pendant les étapes 5 à 7 et toute reprise.
- Préconditions (étapes 6 et 7) : une seule revue derrière les 479 attestations
  actives, différente de #257, approuvée en direct au head nommé par
  l'opérateur, artefact relu au head identique au blob attesté ; avant Worker B,
  chaque job vivant nomme une attestation de cette revue.
- `closure-check` (étape 9) : toutes les ressources `RETRIEVAL_ELIGIBLE`, un pin
  de commit par attestation active à son head, aucun job de publication en
  file ou en cours. Avant cela, une reprise (bail expiré, écriture produit
  interrompue) refait la vérification live et échouerait sur une PR fermée.
- Aucune fusion automatique après Worker B.

## 4. Conditions d'arrêt

Tout écart de l'aperçu ; toute ligne étrangère ; tout bail actif ; tout pin ou
placement produit déjà présent ; toute revue non approuvée en direct ; toute
variation de `ragdb`. Arrêt sans suppression de ligne, de base ni de preuve.

## 5. Reprise après interruption

Chaque étape faite est marquée dans `$STATE_DIR` (défaut
`~/nexus-staging-v4-recovery-dh`). Les outils sont idempotents : relancer une
étape interrompue re-dérive l'ensemble, constate ce qui est déjà fait
(`deja_annules`, `deja_invalidees`, `already_present`, `deja_en_file`) et
n'écrit que le reste — dans une transaction unique.
