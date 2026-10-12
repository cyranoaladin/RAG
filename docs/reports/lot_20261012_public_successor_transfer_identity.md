# Lot 2026-10-12 — identités du plan et du transfert observé du successeur public

## Déclencheur et observation LIVE

Snapshot **LIVE au 12 octobre 2026 à 06:58:16–06:59:21 UTC**, non reconductible
sans nouvelle lecture : `origin/main=62523de5dcf61063a3e058a21fc03fbb290e8287`
(tree `32550e9743e89f143f4075b98e850763c7c9fd1b`), relu avec
`git ls-remote origin refs/heads/main` ; base isolée interrogée en lecture
seule par `ssh nexus-prod-direct` → conteneur
`nexus-public-qual-20261011-pgvector-1` → DB
`ragdb_student_public_qual`, `system_identifier=7695463567278473254`.
Le transfert public isolé V1/V2 a été vérifié puis Worker A a ingéré les 377 placements du successeur
`student-public-successor-20261010-40b956c6f5ec0c60`. Les 377 ressources sont
`NEEDS_REVIEW` ; les 377 lignes d'artefacts représentent 253 SHA distincts ;
la même lecture donne zéro job, zéro attestation LOT42 et zéro adoption. Les
artefacts, placements et chunks de produit étaient absents au contrôle
post-Worker A antérieur. La base historique et la production n'ont pas été
modifiées par ce lot.

Lecture exacte sur la cible, via `docker exec ... psql -U
rag_public_qual_admin -d ragdb_student_public_qual -Atc` :

```sql
SELECT now() AT TIME ZONE 'UTC', current_database(),
       (SELECT system_identifier FROM pg_control_system()),
       (SELECT count(*) FROM ingestion_control.resources),
       (SELECT count(*) FROM ingestion_control.resources
        WHERE resource_state = 'NEEDS_REVIEW'),
       (SELECT count(*) FROM ingestion_control.artifacts),
       (SELECT count(DISTINCT sha256) FROM ingestion_control.artifacts),
       (SELECT count(*) FROM ingestion_control.publication_attestations),
       (SELECT count(*) FROM ingestion_control.sealed_release_adoptions);
-- 2026-10-12 06:58:16.30623|ragdb_student_public_qual|7695463567278473254|377|377|377|253|0|0
SELECT now() AT TIME ZONE 'UTC', count(*) FROM ingestion_control.jobs;
-- 2026-10-12 06:59:09.231516|0
```

La proposition LOT42 en lecture seule a refusé avant toute écriture :
`public batch transfer manifest differs from release`. Le plan A2 est scellé
avec SHA-256 `212385841d6966875f8f20567378bbfeb9afa18f308da4faaf763bd0ee8ee19c`.
Le manifeste d'observation effectivement remis à Worker A et enregistré dans
chacune de ses 377 lignes a SHA-256
`61fc1d7199baf69fcac2da61013fe6b9903aee768e7576a5720934dcf379ac16`.
Le second manifeste inclut le SHA du premier et celui du reçu V1. Confondre ces
deux identités rendait LOT42, C et Worker B impossibles malgré des octets de
transfert cohérents. La reconstruction canonique depuis le plan et le reçu V1
réels donne exactement `61fc…` ; le fichier Worker A présent sur la cible a été
rehaché indépendamment et concorde.

## Correction

Le plan reste l'autorité A2 scellée et le reçu V1/V2 reste lié au pin. Une
fonction partagée reconstruit l'empreinte du manifeste Worker A depuis le plan
et le reçu V1 canoniques, refuse une population divergente, puis les contrôles
LOT42, C, Worker B et API comparent cette empreinte reconstruite aux lignes
mesurées. La revue LOT42 conserve deux liaisons distinctes : son champ
`artifact_transfer_manifest_sha256` contient l'observation Worker A et sa note
`TRANSFER_SHA256` contient le plan A2. Le verdict C conserve le SHA du plan ;
le contrôle DB reconstruit le SHA Worker avant de comparer les 377 lignes et
attestations. Aucun filtre, droit, scope, compte, contenu ni budget n'a changé.

Le correctif ne réécrit pas les lignes déjà ingérées. LOT42 doit être reproposé
sur la cible isolée après fusion et déploiement du code exact, puis une seule
revue exacte du reçu LOT42 reste nécessaire. Il serait incorrect de traiter le
présent rapport ou la réussite de ses tests comme une autorité de publication.

## Vérification et limites

Le code testé était le commit `9020fbafaa5d7d58d038cada3aade214841c8f2a`
(tree `01ad4dec1dc34ae770f08be4ea8248456df5f658`). Commandes depuis la
racine, dans un venv propre installé depuis **ce worktree**, sauf mention :

```bash
PYTHONPATH=services/rag-engine/src python -m pytest -q \
  packages/release-chain/tests/test_public_successor_activation.py \
  services/rag-engine/tests/test_public_successor_batch_proposal.py \
  services/rag-engine/tests/test_public_successor_db_guard.py \
  services/rag-engine/tests/test_public_successor_db_guard_pg.py \
  services/rag-engine/tests/test_public_text_worker_b_cli.py \
  services/rag-engine/tests/test_public_successor_signing_publication.py \
  services/rag-engine/tests/test_sealed_release_ingestion.py \
  scripts/tests/test_public_text_transfer.py
# 221 tests ; exit 0
(cd packages/release-chain && python -m pytest -q tests)
# 186 tests ; exit 0
(cd services/rag-engine && python -m ruff check .)
# Ruff 0.6.4 ; exit 0
(cd services/rag-engine && make typecheck \
  VENVDIR=/home/alaeddine/.venvs/nexus-lot42-transfer-62523)
# 153 fichiers ; exit 0
git diff --check
# exit 0
```

- TDD : le cas des deux SHA distincts et la dérivation du SHA Worker ont échoué
  avant correction, puis réussi ; la substitution d'un SHA de fichier V1 est
  refusée.
- Les 221 tests ciblés comprennent les deux tests PostgreSQL sur schéma 020.
  Le lint du service et le typecheck complet (153 fichiers) ont réussi.
- La cible isolée reste au dernier gate valide `WORKER_A_PASS` jusqu'à la revue
  LOT42. `LOT42_PASS`, `WORKER_B_PASS`, `C_SEMANTIC_PASS` et go-live restent
  **faux**. Aucun rollback n'est requis pour les lignes `NEEDS_REVIEW`.
- Le pin de cible actuellement scellé expire le 12 octobre 2026 à 23:47:31 UTC
  et A2 le 18 octobre 2026 à 21:54:37 UTC. Leur validité doit être rejouée au
  moment de chaque opération ; aucune inscription DB ne prolonge ces fenêtres.

La revue ciblée a relevé une fixture PostgreSQL à adapter et l'absence de test
croisé avec le producteur du manifeste Worker A ; les deux points ont été
corrigés et rejoués. Une validation exacte du HEAD de la PR technique et une
nouvelle image par digest sont requises avant la reprise des étapes mutantes
de publication.
