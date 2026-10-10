# Lot go-live — restauration isolée du dump staging V4/V5 et tête 006/020

## Résultat et périmètre

Le 10 octobre 2026 à 14:49:52 UTC, la sauvegarde **staging interne V4/V5** du 9 octobre a été restaurée sur `korrigo` dans un conteneur PostgreSQL temporaire distinct. `pg_restore` est sorti avec le code 0 ; l'identité de la base, pgvector, les têtes et les empreintes logiques des données restaurées concordaient avec la source staging lue avant l'exercice. La fixture a été supprimée ; contrôle final : zéro conteneur et zéro volume portant son préfixe, source staging `healthy`. Les lectures de la source ont imposé `default_transaction_read_only=on` ; aucune base ni volume historique n'a été restauré en place.

Cette preuve concerne **seulement le dump 005/020** et le corpus interne 11 collections / 315 artefacts / 479 placements / 8 268 chunks. Elle ne qualifie pas la release publique successeur, le head produit 006, un backup frais du candidat final, le magasin d'artefacts ou le rollback du cutover. `FINAL_RELEASE_RESTORE_REHEARSAL_PASS=false` et `PRODUCTION_READY=false` pour ce lot.

## Ancrage et méthode

| Élément | Observation |
|---|---|
| Checkout source | `origin/main` `84c05e0041b17e59f2b0f99a69193352a8d9dab0`, tree `070bd8f8a5f875df16d2db487833538c3e505d98` |
| Sauvegarde | `/srv/nexus-staging/backups/go-live-v4-v5-20261009T071730Z/ragdb_profile_gate_v4.dump`, 49 061 488 octets, format `pg_dump -Fc` validé par `pg_restore --list` |
| SHA-256 sauvegarde | `b63671f3cc63135685f7a241fdb1369aebc08f672e5b0a69fc2910eab3967f83` ; `sha256sum -c` réussi avant restauration et empreinte inchangée après |
| Source | conteneur `nexus-staging-pgvector-1`, base `ragdb_profile_gate_v4`, lectures SQL seules |
| Cible | conteneur temporaire `nexus-restore-84c-*`, volume nommé neuf `nexus-restore-84c-data-*`, `--network none`, zéro port publié, mémoire limitée à 4 Gio et CPU à 2, sans API ni worker |
| Image cible | `pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`, digest local vérifié |
| Secrets | mot de passe temporaire généré sur l'hôte dans un répertoire privé `0700` avec `umask 077`, jamais imprimé ; fichier détruit avec la fixture |
| Restauration | `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges --format=custom` dans la base cible initialisée en `UTF8|C|C` |

Empreintes lues sur la source **avant** restauration et retrouvées à l'identique sur la cible :

| Mesure | Source = cible |
|---|---|
| Identité PostgreSQL | `UTF8|C|C` |
| Extension vector | `0.8.2` |
| Têtes produit / contrôle | `005` / `020` |
| Collections | `11` |
| `rag_artifacts` | `315`, MD5 logique `d68b7f7c9fbb12d1c04314fd509a8c88` |
| `rag_artifact_placements` | `479`, MD5 logique `1c67ae1dda5cc66ab04eb9862462f3d4` |
| `rag_chunks` | `8 268`, MD5 logique `8597b623cc064a9eb54b1b1f1ce5e8a1` |
| `rag_chunks.text_tsv` | `8 268`, MD5 logique `18fb974ccbfce000fe277bcf5525fea8` |

Les MD5 ci-dessus servent uniquement à l'égalité logique source/cible des lignes SQL ; le SHA-256 scelle les octets du dump. La comparaison n'est pas une vérification exhaustive des fichiers du magasin d'artefacts, des rôles runtime, du registre de release ou du candidat public.

## Correction du runbook

Au checkout `84c05e00`, `services/rag-engine/infra/postgres/migrations/HEAD` déclare `006_public_derivative_attribution` et `ingestion_control/migrations/HEAD` déclare `020_successor_control_resource_identity`. Le runbook de rollback classait encore `005/020` comme final et ne contrôlait que cinq lignes produit : il aurait pu donner un faux verdict final à l'ancien dump et refuser la vraie tête 006. Le présent lot corrige le classificateur et le contrôle du registre à `006/020`, met à jour le runbook go-live et l'introduction opérateur du service. Un dump `005/020` est maintenant `FINAL_SCHEMA_UNVERIFIED`, même si sa restauration technique réussit.

La restauration de la **release finale** devra être rejouée avec un backup frais du candidat à 006/020, son volume d'artefacts et ses digests de release, dans une fixture isolée. Aucun verdict `BACKUP_FRESH`, `FINAL_SCHEMA_VERIFIED`, `ROLLBACK_PASS` ou `GO_LIVE_READY` n'est déduit de cet exercice historique.

## Vérification locale du changement

Le test documentaire `scripts/tests/test-go-live-evidence-refresh.py` a d'abord échoué sur l'ancien classificateur pour `6|20` et `5|20`, puis a réussi **19/19** après correction. L'extraction Bash du bloc de restauration a passé `bash -n` ; `git diff --check` est vert. Aucun code runtime, schéma, dump source ni service staging/production n'a été modifié par ce lot.
