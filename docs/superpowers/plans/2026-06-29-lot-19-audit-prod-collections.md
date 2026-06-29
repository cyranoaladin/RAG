# Lot 19 - audit prod, collections et convergence RAG

## Objectif

Produire un lot traçable qui distingue la production historique `rag-ui` du chemin Nexus gouverné, ajoute une architecture cible de collections, ferme les dettes de sécurité admin critiques et prépare la convergence vers le contrat `RetrievalRequest -> RetrievalResponse`.

## Plan d'exécution

1. Consigner l'état initial obligatoire avant toute modification.
2. Lire les documents et modules imposés par le lot 19.
3. Ajouter les tests ciblés pour la configuration de collections, l'auth admin et l'adaptateur retrieval.
4. Ajouter les configurations versionnées `rag_collections.yml` et `legacy_collection_mapping.yml`.
5. Implémenter la résolution serveur des collections et l'adaptateur contractuel sans casser `/search`.
6. Durcir `_admin_guard()` et protéger `/admin/reindex`.
7. Mettre à jour la documentation racine, les docs historiques et les rapports de lot.
8. Exécuter les tests ciblés, puis la CI demandée.
9. Corriger les échecs dans le périmètre ou documenter les dettes restantes avec preuve.
10. Commit, push et PR de lot selon `AGENTS.md`.

## Contraintes

- Ne pas déployer en production depuis ce contexte.
- Ne pas exposer `.env`, tokens, clés Google Drive, secrets HMAC ou PII.
- Ne pas supprimer l'historique Chroma/Streamlit/Ollama ; le baliser comme historique/prod actuelle.
- Ne pas activer de verrou de gouvernance par effet de bord.
- Ne pas renommer physiquement les collections Chroma existantes en production.
