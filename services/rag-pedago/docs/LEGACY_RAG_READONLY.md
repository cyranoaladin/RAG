# RAG historique en lecture seule

Le dépôt `/home/alaeddine/Bureau/RAG/rag-local` correspond à un RAG existant.

Pour ce projet, il est traité uniquement comme une source d'inspiration
technique en lecture seule. Il ne doit pas être modifié, importé comme
dépendance, synchronisé automatiquement, ni utilisé comme source de fichiers à
copier.

Les éléments suivants ne doivent pas être copiés depuis le RAG historique ou la
production :

- fichiers `.env` ;
- credentials ;
- `gdrive-sa.json` ;
- dossiers `data/uploads` ;
- dumps de base de données ;
- données Qdrant ou PostgreSQL ;
- fichiers Docker Compose de production ;
- fichiers applicatifs de production.

Le futur déploiement serveur prévu sous `/srv/nexusreussite/rag-pedago` sera
traité dans un lot ultérieur après validation locale.
