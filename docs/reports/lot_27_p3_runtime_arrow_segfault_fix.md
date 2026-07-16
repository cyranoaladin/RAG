# LOT 27 P3 — Stabilisation du runtime Streamlit contre le segfault Arrow

## Symptôme et impact

La production a observé des segfaults natifs du processus `streamlit` dans
`libarrow.so.2500`. Ils ont entraîné des redémarrages automatiques de `rag_ui`,
des erreurs 502 du proxy Nginx et l'échec du gate E2E post-déploiement.

## Versions observées et versions validées

| Package | Production observée | Lock validé |
|---|---:|---:|
| Streamlit | 1.39.0 | 1.39.0 |
| PyArrow | 25.0.0 | 24.0.0 |
| pandas | 2.2.3 | 2.2.3 |
| NumPy | 2.4.6 | 1.26.4 |
| protobuf | 5.29.6 | 5.29.6 |
| Tornado | 6.5.7 | 6.5.7 |
| Watchdog | 5.0.3 | 5.0.3 |

## Cause racine

Le Dockerfile de l'UI installait uniquement `src/ui/requirements.txt`. Ce
fichier ne contraignait ni PyArrow ni NumPy, tandis que l'image n'utilisait pas
`services/rag-engine/requirements.lock`. Le résolveur pip a donc choisi des
versions transitives différentes du jeu validé localement.

## Correction

Le build UI utilise désormais la racine du dépôt comme contexte, installe les
requirements UI avec `requirements.lock` comme fichier de contraintes, exécute
`pip check` et lance un smoke d'import/version des dépendances natives.

## Périmètre et non-impact

Cette correction concerne uniquement l'image Streamlit UI. Elle ne modifie ni
backend, ni base de données, ni Nginx, ni ingestion, ni données RAG.

## Validation et déploiement ultérieur

La PR exige les tests de contrat, les validations qualité et un build local de
l'image. Un déploiement ultérieur restera UI-only, par release atomique avec
`RELEASE_READY`, suivi du gate E2E durci. Le rollback vise la release UI
précédente validée.
# Remédiation review inline

Le contexte Compose reste volontairement fermé par défaut, mais réinclut explicitement
`requirements.lock`, les sources `src/ui/**` et le smoke runtime afin que chaque
instruction `COPY` du Dockerfile UI soit disponible lors d'un build depuis la racine.
