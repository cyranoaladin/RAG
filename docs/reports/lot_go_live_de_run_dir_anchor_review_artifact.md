# Lot DE — répertoire de travail, ancre de readiness, artefact de revue batch

- Branche : `go-live/de-run-dir-anchor-review-artifact`
- Base : `e2545d0ff9b6dfbc59510421a8b5ab326a95156f` (main après #255, lot DD)

## 1. Ce que l'exécution de DC a établi

Reprise de l'exécution du plan DC après #255, le 2026-09-24. Faits sur le
staging, `ragdb` revérifiée **inchangée** après chaque écriture :

| Étape | Résultat |
|---|---|
| pré-vol | base dédiée présente et vierge ; `ragdb` identique au premier pré-vol |
| `database_creation` | reprise : `ragdb_profile_gate_v4` revérifiée vierge, `createdb` non rejoué |
| `product_migrations` | tête 5 |
| `control_migrations` | tête 19 (`PROVISION_AND_BOOTSTRAP_COMPLETE`) |
| `role_env_derivation` | 5 fichiers écrits (0600, répertoire 0700), chacun authentifiant son rôle sur la base dédiée |
| `model_artifact_install` | `e5-large-prerentree-2026-2027-20260828-materialise`, inventaire `58ad18db…`, revérifié sur l'hôte |
| `readiness_manifest_install` | `staging-readiness-v4.json`, sha256 `368ed1ea…` |
| `transfer_manifest_v4` | 315 objets rehachés sans écart ; **arrêt** au dépôt : `/srv/nexus-staging/run-db` n'existe pas |

## 2. Les défauts, dont deux trouvés à l'avance

1. **Répertoire de travail.** `run-db` n'était créé qu'au premier lancement
   d'un worker, donc après le dépôt du manifeste de transfert. Il est
   désormais créé en 0700 juste avant ce dépôt.
2. **Ancre de readiness.** `readiness.env` désigne l'ancre par son chemin sur
   l'**hôte** (`/srv/nexus-staging/repo/governance/trust-anchors/rehearsal-readiness-v1.json`).
   Dans le conteneur, le dépôt n'est monté que sous `/repo` : la garde de
   readiness de Worker A aurait refusé. L'orchestrateur passe maintenant le
   chemin conteneur du même fichier, identique à celui du dépôt (sha256
   `3604f052…`), et vérifie sa présence sur l'hôte.
3. **Artefact de revue batch.** `propose-release-batch-review` imprime le
   chemin canonique, le digest, puis les octets canoniques, et n'écrit rien.
   L'orchestrateur extrait désormais ces octets et exige :
   - qu'ils portent **exactement** le digest annoncé (sha256 des octets
     canoniques) ;
   - un chemin canonique `governance/publication-reviews/<id>-<digest>.json`.

   Il écrit alors l'artefact sous ce chemin dans `STATE_DIR`. Un écart, un
   doublon ou une absence est un refus.

## 3. Épreuves

- 8 nouveaux tests, rouges sur `main` et verts ici ; 204 tests V4 réussis.
- Aucune garde n'est relâchée.

Après fusion, le plan reprend au dépôt du manifeste de transfert. Les étapes
faites ne sont pas rejouées.
