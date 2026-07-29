# Rapport de LOT 35 — ouverture publique multi-matières contrôlée

- **Branche** : `lot-33-go-live-architecture`
- **Base auditée** : `fbd9efc`
- **Date** : 2026-07-29
- **Statut de déploiement public** : **BLOQUÉ PAR CONCEPTION** jusqu’à preuve exhaustive de corpus validés.

## Livraison

- Contrats Pydantic stricts pour recherche publique, conversation, identité et citations ; export JSON Schema déterministe et client TypeScript/Ajv généré.
- `rag-engine` expose le contrôle `/collections/readiness` et un `/chat` OpenRouter qui ne répond que depuis des chunks `reviewed`, avec citations `[S<n>]` validées. Toute source insuffisante, clé absente, erreur fournisseur ou citation invalide produit un refus explicite.
- Le cockpit public de `nexusreussite.academy` passe uniquement par le BFF same-origin. Les routes recherche et chat vérifient elles-mêmes la readiness : l’interface **et** les appels HTTP directs sont fermés si la preuve n’est pas complète.
- Les écrans d’exploitation (ingestion, revue, gouvernance) sont retirés de la navigation publique ; aucun secret OpenRouter ou jeton engine ne transite vers le navigateur.

## Preuves exécutées

| Commande | Résultat |
| --- | --- |
| `PYTHONPATH=src python -m pytest packages/contracts/tests -q` | PASS, 22 tests |
| `services/rag-engine/.venv/bin/python -m ruff check .` | PASS |
| `make typecheck` dans `services/rag-engine` | PASS |
| `PYTHONPATH=src .venv/bin/python -m pytest -q -m 'not integration'` dans `services/rag-engine` | PASS |
| `npm run lint && npm run typecheck && npm test -- --run && npm run build` dans `services/cockpit` | PASS, 19 tests |
| `npm run contracts:check` dans `services/cockpit` | PASS |

### Limite de la CI locale globale

`bash scripts/ci-local.sh` a été interrompu pendant les tests `rag-pedago` :
un sous-processus lance à nouveau `scripts/ci-local.sh` via
`scripts/audit/rag-pr-audit.sh`, ce qui recrée la CI récursivement. Cette
anomalie est antérieure au lot : les SHA-256 de `scripts/ci-local.sh` et
`scripts/audit/rag-pr-audit.sh` sont identiques entre `fbd9efc` et l’arbre de
ce lot (`692da31d…` et `eb75250a…`). Elle reste bloquante pour attester une CI
globale verte ; les vérifications ciblées listées ci-dessus ont néanmoins été
exécutées avec succès.

## Garde-fou de lancement

La configuration déclare 59 collections mais seulement 3 sont aujourd’hui
`instanciee: true`. Ce lot ne modifie aucun verrou de gouvernance et ne prétend
pas rendre le corpus substantiel par simple présence de références. En l’absence
de la preuve DB complète (chunks `reviewed` pour chaque collection, au seuil
`RAG_MIN_COLLECTION_SUBSTANCE_CHUNKS`), `/collections/readiness` est rouge et
les routes publiques refusent recherche et génération.

## Prérequis restant avant bascule réelle

1. Publier les 59 corpus via le circuit `quality → gate → review` et conserver
   les preuves de substance par collection.
2. Vérifier `/collections/readiness` vert sur l’environnement cible, avec le
   seuil de substance retenu, avant d’annoncer l’ouverture.
3. Configurer côté serveur `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, le jeton
   interne BFF et le reverse proxy TLS pour `nexusreussite.academy` ; aucun de
   ces secrets n’est versionné ici.
