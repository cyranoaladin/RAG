# Base de vectorisation dédiée — provisionnement

- kind : `NEXUS-DEDICATED-VECTOR-DB-PROVISIONING-V1`
- base dédiée : `nexus_vector_staging_a_20260912T060731Z`
- conteneur : `nexus-vector-staging-a-20260912T060731Z`
- hôte/port : `127.0.0.1:55436`
- schéma : `drive_staging`
- tables : `drive_staging.authorized_content`, `drive_staging.chunk_embeddings`

## Séparation d'avec la base de revue

- base de revue source : `drivestaging`
- source_review_db_readonly : `True`
- pgvector dans la base dédiée : `True` (version `0.8.2`)
- pgvector dans la base de revue : `False`
- écriture en base de revue : `False`

> nexus-drive-staging-v2 porte le texte canonique qui rend rejouables 149 décisions PII, dont 23 sur des contenus déjà promus

## Entrée vectorisable

- périmètre : `SERVABLE_CANDIDATE_SET`
- effectif : **2264**
- empreinte : `227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd`
- lignes de liste blanche chargées : 2264
- refusés par le gate (hors périmètre) : 266
- intersection refusés : **0**
- intersection PII non tranchée : **0**
- intersection actualité refusée : **0**

## Ce lot ne vectorise pas

- vector_rows : **0**
- vectorization_executed : `False`
- production_touched : `False`
- current_switch : `False`

## Retour arrière

```
docker rm -f nexus-vector-staging-a-20260912T060731Z && docker volume rm $(docker inspect nexus-vector-staging-a-20260912T060731Z --format '{{range .Mounts}}{{.Name}}{{end}}')
```

la base dédiée et son volume, rien d'autre : aucune table de revue n'est touchée, aucune sauvegarde n'est consommée

## Ce que ceci ne prouve pas

- aucun vecteur n'existe : la recherche reste impossible
- target_scope_searchable reste faux
- le blocage RAG_SEARCHABILITY reste ouvert
