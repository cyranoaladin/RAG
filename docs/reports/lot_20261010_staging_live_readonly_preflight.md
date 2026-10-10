# Préflight ciblé du staging V4/V5 — lecture seule, 10 octobre 2026

## Portée et verdict

Mesures directes effectuées le **10 octobre 2026, entre 13:53 et 13:58 UTC**. Le point de départ local est un worktree propre de `origin/main` à `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`, arbre `93e9f382fb12bd49ee3489056e0536f4d66c1976`. Les commandes ci-dessous ont uniquement lu la cible staging existante. Aucun déploiement, migration, changement de base, import ou écriture de production n'a été effectué.

| Contrôle | Verdict observé |
| --- | --- |
| `STAGING_RUNTIME_IDENTITY_VERIFIED` | `true` pour la pile `nexus-staging` sur `korrigo` |
| `STAGING_DB_TARGET_VERIFIED` | `true` pour la base **conteneurisée** `ragdb_profile_gate_v4` |
| Union V4 non-HGGSP + V5 HGGSP | 11 collections, 315 artefacts, 479 placements, 8 268 chunks physiques |
| Recherche enseignant directe API sur les 11 collections | 11/11 avec au moins une réponse non vide et une citation, sur 14 requêtes ciblées |
| Recherche élève sur les mêmes scopes | 11/11 réponses HTTP 403, conformément à la visibilité `internal` |
| Successeur public #312 déployé | **Non** : aucune release successeur publique trouvée dans cette cible |

Ces nombres caractérisent exclusivement le **rehearsal V4/V5 internal** actuellement servi en staging. Ils ne sont ni les comptes du candidat textuel public #312, ni une preuve de staging final ou de go-live. Le checkout distant est `5da581b6f56dd3f8edf3ee6883170da9a100c9b6`, et non `fc6b7da6`; aucune identité de build à partir de ce dernier SHA n'est donc revendiquée.

## Identité de cible et versions

Accès SSH existant `nexus-prod` avec `ProxyJump=none`, `BatchMode=yes`, `ConnectTimeout=10`; l'hôte répond `korrigo`. Les conteneurs pertinents portent le projet Compose `nexus-staging`. La base ciblée par toutes les requêtes SQL est `nexus-staging-pgvector-1`, ID `0a3ee7998bdf4c6a0f32ac088908b9236030f8b037d8860dadbbd722e26853d9`, port loopback `127.0.0.1:15435`; **le PostgreSQL natif de l'hôte n'a pas été interrogé**. Le serveur est PostgreSQL 16.14 avec pgvector 0.8.2, `system_identifier=7686759709751865382`. La migration de schéma produit maximale est 5; celle de `ingestion_control` est 20. Chaque session SQL imposait `default_transaction_read_only=on`, avec `BEGIN READ ONLY` puis `ROLLBACK`.

L'ingestor est `nexus-staging-ingestor-1`, sain, exposé seulement sur `127.0.0.1:18003`; `GET /health` renvoie HTTP 200. `GET /collections/readiness` et `GET /collections/v2` sans authentification renvoient HTTP 401. Le runtime déclare `NEXUS_ENVIRONMENT=rehearsal` et `RAG_ENV=production` : ce dernier est un mode applicatif, pas une identité de cible production. Le label OCI de révision du conteneur est vide, ce qui limite la preuve de provenance de l'image.

| Objet lu sur la cible | SHA-256 observé |
| --- | --- |
| Image base pgvector, ID de contenu | `00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc` |
| Image ingestor, ID de contenu | `826a7d086a850cd97bb120c93e6e91d9fe30e575fbedffcaa34c5ac28298a121` |
| Release registry V4/V5, SHA des octets et valeur attendue du runtime | `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6` |
| Manifeste V4, SHA des octets et valeur attendue | `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be` |
| Manifeste V5 HGGSP, SHA des octets et valeur attendue | `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` |
| Index logique du corpus servable, valeur interne et attendue | `c0c7203c73c96cc96b0c0b13a5448a4f5f42c736de2f26722f380f8411caf16c` |

Le SHA brut du fichier d'index est `09206c417dadc55009e9499b9388bf56fac3107ebda3bef20645f42875df451c` : il diffère de son digest **logique auto-référencé**, sans constituer une discordance de contrôle.

## Populations réellement observées dans la base staging

Les requêtes ont compté les lignes physiques de `public.rag_artifacts`, `public.rag_artifact_placements` et `public.rag_chunks`, ainsi que les collections distinctes des placements, puis séparé les collections V4 non-HGGSP des deux collections HGGSP V5. Elles ont aussi contrôlé les enregistrements de `ingestion_control` et le statut des jobs. Les comptes de chunks par collection ci-dessous sont des chunks accessibles via ses placements : un même artefact peut être placé dans plusieurs collections et ces valeurs **ne doivent pas être additionnées** pour déduire le total physique.

| Population | Collections | Artefacts | Placements | Chunks physiques |
| --- | ---: | ---: | ---: | ---: |
| V4 non-HGGSP | 9 | 263 | 405 | 5 678 |
| V5 HGGSP | 2 | 52 | 74 | 2 590 |
| Union staging | **11** | **315** | **479** | **8 268** |

| Collection | Artefacts | Placements | Chunks accessibles |
| --- | ---: | ---: | ---: |
| DGEMC terminale | 12 | 12 | 343 |
| HGGSP première | 39 | 39 | 1 858 |
| HGGSP terminale | 35 | 35 | 1 874 |
| HLP première | 115 | 115 | 1 984 |
| HLP terminale | 89 | 89 | 1 599 |
| NSI première | 29 | 29 | 483 |
| NSI terminale | 47 | 47 | 904 |
| SES première | 30 | 30 | 726 |
| SES terminale | 28 | 28 | 804 |
| SVT première | 19 | 19 | 663 |
| SVT terminale | 36 | 36 | 1 078 |

Aucun artefact sans placement ou sans chunk n'a été trouvé. Les 479 placements sont tous `internal`, `reviewed` et `active`; les droits des artefacts portent la valeur historique `officiel_public`, qui **ne vaut pas** autorisation de visibilité étudiant. Les 13 autorisations de scope actives sont `internal` avec action `AUTHORIZE_INGESTION_SCOPE`; aucune autorisation de scope `public` active et aucune révocation de scope ni ligne dans `revoked_review_evidence` n'ont été observées.

Le contrôle V5 montre 74 adoptions scellées, portant 52 identités de contenu distinctes, avec protocole `SEALED-RELEASE-ADOPTION-V2`; 74 attestations de publication V5 actives et 74 jobs V5 `succeeded`, zéro `failed`. Côté V4, les 405 jobs non-HGGSP sont `succeeded` et 74 anciens jobs HGGSP restent `queued`; 479 autres lignes de reprise sont `cancelled`. Les 74 anciens jobs HGGSP ont conservé le fingerprint canonique `fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31`, recalculé en lecture seule et égal à la référence du code. Les attestations V4 comptent 479 actives et 479 invalidées. Les références de review/head/challenge sont renseignées pour 479/479 attestations V4 actives et 74/74 V5; la validité **actuelle** des reviews GitHub n'a pas été rejouée ici. La base ne contient que les releases V4 et HGGSP V5.

## Sonde HTTP réelle et limites

Les trois fichiers de code interrogateur du checkout distant ont les mêmes SHA que dans le worktree `fc6b7da6` : `rag_query.py` = `73f61d4019899f5ff9184eef73758477d24ee19884d3eac114b0a0e96590ae0e`, `rag_query_external.py` = `cf7ac19d6f0d1942812bd19f79af7321bd8f31a187f8fbdf703f30a0044e42fd`, `final_retrieval_acceptance.py` = `a0c23e013f3f65563794d373bde90a4d0fcf8f95b7be0400b1b61423d1a6c78d`. La fixture de requêtes V4/V5 a le SHA brut `89faa10de47134f005c81bc71d8ee879d246af9a2be1d50276253cce4aba5419` des deux côtés.

La sonde a utilisé le venv distant existant et ses fichiers d'identifiants opérateur **lus uniquement en mémoire**, sans afficher de valeur secrète. Elle a signé une identité `teacher`, envoyé les en-têtes de sécurité requis et appelé directement `POST /search/v2` dans chaque collection avec une requête factuelle de la fixture, puis le cas `no_accent` uniquement si le résultat factuel était vide. Les 14 réponses sont HTTP 200. Une réponse non vide a finalement été obtenue dans chacune des 11 collections, avec l'identité de contenu attendue et, dans les résultats observés, collection exacte, `source_uri`, `source_label` et page de citation présents; aucun résultat hors scope observé. Les trois requêtes factuelles initialement vides étaient HGGSP terminale, HLP première et SVT première. Le test `student` signé, répété sur les 11 scopes actuels, a reçu 11 réponses HTTP 403. Les latences séquentielles observées étaient d'environ 2,3 à 2,8 secondes par requête.

Cette sonde ne couvre **ni** le Cockpit/BFF, **ni** la suite qualité finale, **ni** une charge C0, **ni** les 253 dérivés textuels publics, **ni** la validité GitHub des reviews, **ni** un chemin étudiant positif. Elle prouve seulement la disponibilité ciblée du rehearsal interne à l'instant de mesure.

## Rejeu et blocages de promotion

Les commandes de qualification étaient de la forme suivante; les requêtes `SELECT` ont été exécutées sur la base conteneurisée ciblée, et aucun contenu d'identifiant n'a été imprimé :

```bash
git fetch origin
git rev-parse origin/main
git rev-parse HEAD^{tree}
ssh -o ProxyJump=none -o BatchMode=yes -o ConnectTimeout=10 nexus-prod hostname
ssh -o ProxyJump=none -o BatchMode=yes -o ConnectTimeout=10 nexus-prod 'docker ps --filter label=com.docker.compose.project=nexus-staging'
ssh -o ProxyJump=none -o BatchMode=yes -o ConnectTimeout=10 nexus-prod 'docker inspect nexus-staging-pgvector-1 nexus-staging-ingestor-1'
ssh -o ProxyJump=none -o BatchMode=yes -o ConnectTimeout=10 nexus-prod "docker exec -e PGOPTIONS='-c default_transaction_read_only=on' nexus-staging-pgvector-1 psql -U raguser -d ragdb_profile_gate_v4 -v ON_ERROR_STOP=1"
```

Le protocole SQL de chaque invocation était `BEGIN READ ONLY; SELECT …; ROLLBACK;`. Les lectures HTTP étaient `GET /health`, deux `GET` non authentifiés de contrôle, puis des `POST /search/v2` **sans effet d'écriture** avec identité signée. Les digests des manifests ont été comparés aux variables attendues à l'intérieur du conteneur. La population totale vient de `COUNT(*)` sur chacune des trois tables physiques et de `COUNT(DISTINCT collection)` sur les placements; les partitions viennent des liens collection–placement–artefact et de leurs releases. Aucun chiffre de l'audit historique local n'a été substitué à une mesure live.

Pour qualifier le successeur public, il reste à déployer sur une cible staging finale propre ses nouveaux manifests, autorisations `public`, dérivés textuels et index scellés; vérifier la provenance des images; puis rejouer sur ce candidat les chemins étudiant/BFF, citations et refus, la suite qualité finale et C0. Les comptes du successeur doivent être recalculés depuis ses propres artefacts et placements. **`STAGING_FINAL_PASS`, `STUDENT_PUBLIC_PATH_PASS`, `QUALITY_PASS` et `LOAD_PASS` ne sont pas établis par ce rapport.**
