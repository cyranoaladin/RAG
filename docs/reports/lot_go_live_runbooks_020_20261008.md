# Lot go-live — runbooks alignés sur le head `020`

**Date du lot :** 2026-10-08 (UTC). **Base après rebase :**
`1ab971838e90c876bf185da03b67423f9f0a32c9`.

Le runbook `go_live.md` prescrivait encore `ingestion_control` `001..013`,
alors que `services/rag-engine/infra/postgres/ingestion_control/migrations/HEAD`
déclare `020_successor_control_resource_identity`. La migration `019` lie
l'autorisation de publication aux placements adoptés ; `020` ajoute les
identités distinctes du successeur et leurs contraintes. Le runbook renvoie
désormais au `HEAD` du code effectivement déployé et exige un registre
contigu avec SHA-256 concordants, actuellement `1..20`. Le runbook de rollback
distingue explicitement la restauration d'une ancienne base de la preuve du
schéma final et interdit d'employer ses anciennes commandes Docker pour la
release gouvernée V2.

**Observations non vérifiées, exclues des preuves de go-live :** le compte
rendu opérateur initial mentionnait une lecture de `rag_pgvector/ragdb` sur
`korrigo` à 04:59 UTC et la restauration isolée d'un dump daté de 00:20 UTC.
Cette PR ne contient ni transcript expurgé, ni commandes exactes, ni identité
de l'opérateur, ni empreinte du dump ou de la sortie de `pg_restore`. Elle ne
permet donc de vérifier ni l'identité de la cible à ces instants, ni le
contenu du dump, ni le succès de la restauration. Une nouvelle lecture
directe rapportée à 12:21–12:23 UTC indique le conteneur RAG `rag_pgvector`,
la base `ragdb`, vector 0.8.2 et zéro `rag_chunks`, mais sa trace n'est pas
versée ici : ce constat reste lui aussi non opposable pour cette PR. Ne pas
confondre ces indications avec le PostgreSQL natif de l'hôte.

`RESTORE_REHEARSAL_PASS=UNVERIFIED` et
`BACKUP_SHA256_VERIFIED=UNVERIFIED` pour l'ancien dump. La qualification
finale devra archiver la provenance et l'empreinte du backup, puis rejouer
une restauration de la base **et** des artefacts de la release finale sur
une cible isolée, avec commandes et sorties expurgées liées au SHA final.

**Vérification locale après correction :**
`python3 -m pytest -q scripts/tests/test-go-live-evidence-refresh.py` :
12 tests et 47 sous-tests réussis. Le garde documentaire lit le `HEAD`
canonique au lieu de figer `013` et exige les clauses `019`/`020`, la
continuité `1..20`, les SHA-256 et `SCHEMA_HEAD=20`.
`git diff --check` : réussi.
`bash scripts/check-governance-locks.sh` : 18 verrous conformes.

**Production et staging :** aucune mutation effectuée par ce lot.
