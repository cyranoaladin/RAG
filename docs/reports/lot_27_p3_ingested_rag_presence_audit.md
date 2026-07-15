# LOT 27 P3 — audit de présence des données RAG ingérées

Date de l'audit : 2026-07-16 (UTC).
Périmètre : lecture seule. Aucune ingestion, restauration, migration, suppression de volume ou modification de base de données n'a été effectuée.

## Release auditée

- Release active : `rag-v2-main-27a4558-lot27p3-20260715T133534Z`.
- Commit de release : `27a4558a1abca304d415240b9ec0c06000cd2db5`.
- Marqueur `RELEASE_READY` présent.
- `PG_RAG_DSN` n'est pas défini dans l'environnement de la stack auditée ; les paramètres pgvector sont fournis par les variables dédiées. L'hôte n'est pas consigné dans ce rapport.

## pgvector v2

La base `ragdb` contient les tables `rag_api_keys`, `rag_chunks` et `rag_eval_runs` dans le schéma `public`.

| Table | Estimation de lignes | Constat |
|---|---:|---|
| `rag_api_keys` | 0 | Aucune donnée auditée. |
| `rag_chunks` | 0 | Aucun chunk dans pgvector v2. |
| `rag_eval_runs` | 0 | Aucune donnée auditée. |

La requête exacte `count(*)` sur `rag_chunks` retourne **0**. Le groupement par collection ne retourne aucune ligne. Il n'existe pas d'autre table candidate contenant `rag`, `chunk`, `collection`, `embedding` ou `document` dans la base auditée.

Conclusion : `DATA_PRESENT_IN_PGVECTOR` est exclu pour l'instance v2 actuellement connectée.

## API v2 et retrieval

| Contrôle | Résultat |
|---|---|
| `GET /catalogue/v2` | HTTP 200 ; 35 collections déclarées. |
| `GET /collections/v2` | HTTP 200 ; 2 collections retrievable exposées. |
| Collections retrievable | `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`. |
| 4 recherches de fumée par collection NSI | HTTP 200, 0 hit, `returned=0`, génération de réponse non autorisée pour les 8 requêtes. |

Les collections v2 sont donc déclarées et l'API reste accessible, mais la donnée de retrieval n'est pas présente dans pgvector v2.

## Backups disponibles

Les sauvegardes suivantes ont été trouvées sans restauration ni extraction :

| Artefact | Preuve | Qualification |
|---|---|---|
| `compose_rag_ui_chroma_data.tgz` du 2026-07-13 | 232 372 886 octets ; 61 entrées ; contient `chroma.sqlite3` et des index HNSW | Backup Chroma exploitable à analyser dans un environnement isolé. |
| Dumps `ragdb-before-migrations` | Plusieurs archives de 9 095 octets | Présents mais trop petits pour constituer une preuve de corpus ingéré ; analyse hors production requise. |
| Backup Ollama/admin | Archives présentes | Hors preuve de retrieval. |

Le backup Chroma n'a pas été restauré, monté ni modifié.

## Chroma legacy et volumes

Le conteneur legacy `compose-chroma-1` est en cours d'exécution, sur `127.0.0.1:8000`, avec le volume `compose_rag_ui_chroma_data`. L'API Chroma v2 locale a été interrogée en lecture seule.

| Collection Chroma | Nombre de vecteurs |
|---|---:|
| `nsi_corpus_v2` | 5 992 |
| `rag_education` | 7 181 |
| `rag_maths_premiere` | 0 |
| `rag_math_correction` | 67 |
| `rag_divers` | 0 |
| `ressources_pedagogiques_terminale` | 0 |
| `nsi_corpus` | 4 716 |
| `rag_francais_premiere` | 5 948 |
| **Total** | **23 904** |

Les volumes potentiellement pertinents restent présents et n'ont pas été touchés : `compose_rag_ui_chroma_data`, `compose_rag_ui_admin_data`, `compose_rag_ui_ollama_data`, `infra_rag_pgvector_data` et les volumes RAG v2 associés.

Conclusion : les données ingérées sont **présentes dans Chroma legacy**. Cette preuve n'autorise ni arrêt du conteneur legacy ni migration automatique.

## Sources versionnées

La release active contient le répertoire `corpus` et les données de staging. Cinq manifestes NSI Terminale ont été trouvés sous `services/rag-pedago/data/staging/agents/terminale/nsi/` : arbres, fichiers, graphes, listes et piles.

Ces fichiers constituent une source versionnée à qualifier dans un lot de réingestion gouvernée ; ils ne prouvent pas, à eux seuls, l'équivalence complète avec les 23 904 vecteurs Chroma.

## Plan de reprise requis (non exécuté)

1. Créer une procédure de migration ou de réingestion dédiée, avec ADR et autorisation de gouvernance.
2. Travailler hors production sur une copie du backup Chroma et comparer collections, cardinalités, métadonnées et sources versionnées.
3. Définir la correspondance explicite entre collections legacy et catalogue v2 ; ne pas exposer de collection legacy en v2 par défaut.
4. Restaurer ou réingérer uniquement après approbation, puis vérifier les chunks pgvector, les recherches NSI et les gates E2E durcis.

## Conclusion

`DATA_PRESENT_IN_CHROMA`.

Le blocage P1 persiste : pgvector v2 est vide et les recherches NSI ne retournent aucun hit. Toute reprise doit être traitée dans un lot distinct, approuvé et réversible. Aucune opération de récupération n'est réalisée par cet audit.
