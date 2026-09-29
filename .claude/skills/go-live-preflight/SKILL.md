---
name: go-live-preflight
description: Produit le préflight écrit d'une opération go-live Nexus RAG (staging ou production) — autorité, provenance de release, digests d'images, migrations, cardinalités attendues, rollback et point d'autorisation humain — sans rien exécuter sur un serveur. À utiliser avant toute publication staging, migration live, bascule current ou déploiement.
argument-hint: "<opération> [release_id]"
---

# /go-live-preflight — le plan, pas l'exécution

Lecture du dépôt et de GitHub uniquement. Aucun SSH, aucune connexion à une base réelle.

## Workflow

1. `/project-status` (état live). Identifier le runbook ou `*_EXECUTION_PLAN.md` qui régit
   l'opération et le lire en entier.
2. Autorité : PR, ADR et autorisations (`governance/…`) qui fondent l'opération ; chaque
   autorisation est-elle active (pas seulement `proposed/`) et fusionnée au SHA prévu ?
3. Provenance : manifestes de release (empreintes SHA-256 recalculées avec `sha256sum`),
   images par digest (`docker-compose.production-release.yml`, inventaire de provenance),
   inventaires de modèles. Tout écart = arrêt.
4. Schéma : HEAD des deux chaînes de migrations attendu par l'opération.
5. Cardinalités attendues (collections, artefacts, placements, chunks) dérivées des
   manifestes scellés, avec leur source ; jamais recopiées d'un README.
6. Readiness : `python3 scripts/go_live/check_go_live_readiness.py --assert-ready` (local)
   et son code de sortie.
7. Rollback : procédure exacte et préconditions (sauvegarde vérifiée).
8. Pour une vérification indépendante de la provenance, déléguer à l'agent `go-live-auditor`.

## Arrêt

Préflight écrit et présenté. **Attendre l'autorisation humaine explicite** pour l'opération
précise ; ne pas enchaîner sur `/staging-operation` ou `/production-deploy`.

## Sortie

Cible · SHA `main` · release_id · autorités (PR/ADR/fichier@SHA) · empreintes vérifiées ·
digests · HEAD schéma · cardinalités attendues · commandes exactes prévues · effet attendu ·
rollback · bloquants · question d'autorisation formulée pour l'humain.
