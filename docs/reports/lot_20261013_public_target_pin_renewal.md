# Lot 2026-10-13 — renouvellement du pin de qualification A2

## Déclencheur et périmètre

Le pin A2 précédent `1bbbe72d0809e5cd77a7e53bba85d26ba286b74e799b055923d9c3a920517d72` a expiré le 12 octobre 2026 à 23:47:31.927082 UTC. Sa validité ne se prolonge ni par une readiness déjà signée, ni par les 377 lignes Worker A et LOT42 de la cible précédente. Le reçu V1 exigé après un nouveau pin porterait une autre date et donc un autre SHA ; le manifeste observé Worker A reconstruit à partir de ce V1 serait différent des 377 valeurs persistées. La revue LOT42 existante est elle-même liée à l'ancien pin et à l'ancienne attestation V2. La cible précédente est préservée pour son historique et ses sauvegardes ; elle n'est pas réécrite.

Ce lot repart de `origin/main=6d26120b6450baec44cbf9bb53444f582d1d0a67`, arbre `d5ba3a25672459c032d97d94ad9cd3234cbd193b`, dans un worktree propre. Il ne modifie ni A2, ni l'ancre de contenu, ni les 253 dérivés, ni le plan de transfert `212385841d6966875f8f20567378bbfeb9afa18f308da4faaf763bd0ee8ee19c`, ni les onze scopes ou droits. Aucune observation V1, attestation V2, ingestion ou publication nouvelle n'a eu lieu pendant ce lot.

## Nouvelle cible isolée, contrôlée le 13 octobre 2026 à 04:10–04:15 UTC

Le dump custom **pré-transfert** `before-transfer-main62523-20261012.dump` a été vérifié contre son SHA-256 `0c34e0a325e1beb25c8bec8e6b390d7bf907e0d1aa4896ecfed0614570d5e92a`, puis restauré avec `pg_restore --clean --if-exists --exit-on-error --single-transaction --no-owner --no-privileges` dans un nouveau projet Docker `nexus-public-qual-20261013`, sans toucher l'ancien projet. Les scripts canoniques ont réappliqué les rôles produit et le provisionnement du contrôle. La configuration PostgreSQL provient de l'archive Git exacte du main ci-dessus, copiée sous la nouvelle racine, sans montage d'un checkout Git.

| Dimension | Nouvelle cible |
| --- | --- |
| Hôte | `korrigo` |
| Conteneur | `bfae3af66a08e11d07d4b78db8f46d8b5c3013c31af094da68b16748e99d4684` |
| DB / port publié | `ragdb_student_public_qual_20261013` / `127.0.0.1:15437` |
| `system_identifier` | `7696000243730169894` — différent de `7695463567278473254` sur l'ancienne cible |
| Volume | `nexus-public-qual-20261013_rag_pgvector_data` |
| Magasin texte | `/srv/nexus-public-qual-20261013/servable-text`, vide au contrôle |
| PostgreSQL | UTF8, collation C, ctype C ; pgvector 0.8.2 |
| Migrations | produit 001–006 ; contrôle 001–020 |
| Autorisations | 22 lignes historiques : 11 A2 V2 actives, une par collection, et 11 précédentes expirées ; aucune révocation |
| Population avant transfert | 0 ressource, 0 job, 0 attestation LOT42, 0 projection, 0 adoption, 0 artefact produit, 0 placement produit, 0 chunk produit |

Une sauvegarde de contrôle de **cette seule nouvelle base**, avant transfert, se trouve à `/srv/nexus-public-qual-20261013/backups/before-transfer-main6d261-20261013.dump`. `pg_restore --list` est lisible ; SHA-256 vérifié `00bae5db7dcc57af47be7d2e3d7fec90531c8517fc4e0db2fbb89d29c54128e9`. L'ancienne cible garde son conteneur, son volume et ses sauvegardes intacts.

## Pin et liaison A2 nouveaux, non approuvés

Le producteur canonique `scripts/go_live/independent_staging_target_pin.py` a été exécuté **sur l'hôte cible** depuis un checkout opérateur propre au SHA `6d26120b6450baec44cbf9bb53444f582d1d0a67`, avec un venv isolé contenant `psycopg==3.2.1`. Il a relu en lecture seule le socket PostgreSQL loopback, son lien au conteneur Docker local et le device/inode du répertoire vide. Il a capturé les octets versionnés sous `governance/staging_target_pins/student-public-successor-release40b-a2-20261013.json` : SHA-256 `256713304e5292486b5e8c881f91c8983d58fcc3166a8f9055dc164170469e5c`, fenêtre `2026-10-13T04:14:46.416537Z` à `2026-10-14T04:14:46.416537Z`, statut **capture non approuvée**. Une seconde sonde physique indépendante après capture a relu la même cible et vérifié les octets du pin (`LIVE_PIN_PHYSICAL_MATCH=true`).

`governance/student_public_rights/public_successor_a2_transfer_binding_20261013.json` est reconstruit par `build_a2_transfer_binding` à partir des octets exacts A2, du nouveau pin et du plan inchangé. Son SHA-256 est `a30e8fc24e7f868f1d94aeb4be7eb19b70716c6dd1950dbf4a221a2c17e8309f` ; son statut reste `REVIEW_CANDIDATE_NOT_AUTHORIZED`. A2 conserve SHA-256 `5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4` et expire le 18 octobre 2026 à 21:54:37.014823 UTC. Aucun contenu ni compte déclaratif n'est modifié : 11 collections, 253 dérivés, 377 placements et 3 975 chunks attendus **après** une nouvelle ingestion, à remesurer réellement.

Le test TDD de continuité a d'abord échoué parce que le nouveau pin et le nouveau binding étaient absents, puis a réussi après leur génération canonique. Les tests ciblés `test_public_successor_a2_transfer_binding.py` et `test_independent_staging_target_pin.py` donnent 51/51 ; l'ensemble des tests du paquet `release-chain` avec le test de pin donne 242/242. Ruff sur le test, `check-authority-uniqueness.sh` et `git diff --check` sont verts. Ces tests ne prouvent pas une review GitHub ni une autorité de publication.

## Gates restants

La PR doit rester ouverte sur un HEAD figé, CI standard verte, puis recevoir la review `abenrhouma` sur son base/HEAD/challenge exact et le statut `trusted-human-review/head-pinned=success`. Le vérificateur `independent_staging_target_pin.py verify` doit relire le blob de ce HEAD et la même cible **avant** la fusion. Après fusion, le reçu historique du pin doit être généré et rejoué, sous la fenêtre de 24 h.

Seulement après ce gate, une nouvelle observation V1 post-pin puis une attestation V2 doivent être produites sur la nouvelle cible. Leurs SHA nouveaux alimenteront une readiness INGESTION signée, Worker A sur la base vide, une nouvelle revue LOT42 exacte des placements réels, les attestations, C et la readiness PUBLICATION. Aucun reçu, job ou attestation de l'ancien staging ne remplace ces étapes. L'expiration du pin ou un changement d'identité avant le gate impose une nouvelle capture et une nouvelle review ; aucun ancien timestamp ne peut être retouché.
