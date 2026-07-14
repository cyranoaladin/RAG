# LOT 27 P3 — UX, E2E et clôture Ops

## Objectif

Clore les dettes P3 post-go-live sans changer la logique métier, les contrats, les endpoints, les données ou la production.

## Décisions validées

- La sidebar publique affiche `API connectée · Backend RAG v2`, jamais l'URL interne `http://ingestor:8001`.
- Le polissage reste local à l'interface Streamlit existante : titres, sous-titres, regroupement visuel et libellés métier.
- Les appels restent limités aux endpoints RAG v2 existants. Aucun flux legacy ni endpoint Drive ne sera ajouté.
- La PR #56 reste ouverte et non mergée. La nouvelle PR porte les assertions E2E complètes et le libellé `Catalogue v2 complet`, car elle couvre aussi le nouveau polissage frontend.
- Les conteneurs `infra-web-1`, `infra-postgres-1` et `infra-minio-1` sont documentés seulement. Aucune commande Docker destructive n'est autorisée.

## Interfaces

`services/rag-engine/src/ui/app_v2.py` conserve les appels à `/catalogue/v2`, `/collections/v2`, `/search/v2`, `/ingest/v2/upload-files` et `/ingest/v2/urls`. Les changements affectent uniquement les textes et la présentation Streamlit.

## Validation

Des tests statiques vérifient l'absence de l'URL interne et des routes/collections legacy, ainsi que les libellés UX requis. L'E2E versionné vérifie Dashboard, Recherche, Ingestion et Administration ainsi que les absences obligatoires. La qualité `rag-engine` et les garde-fous de gouvernance restent requis.
