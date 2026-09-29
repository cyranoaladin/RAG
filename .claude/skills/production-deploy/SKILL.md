---
name: production-deploy
description: Déploiement production Nexus RAG — uniquement après GO_LIVE_READY démontré et autorisation production explicite. Commence par un préflight et s'arrête au point d'autorisation humain. Invocation manuelle uniquement.
disable-model-invocation: true
argument-hint: "<release_id> <SHA main> <autorisation production citée>"
---

# /production-deploy — ne rien faire avant la porte humaine

Ce skill n'exécute automatiquement AUCUN SSH, AUCUNE migration, AUCUNE bascule `current`,
AUCUNE fusion ou fermeture de PR.

## Phase 1 — préflight (sans effet)

1. `/project-status`, puis `/go-live-preflight production <release_id>`.
2. Vérifier chaque critère de `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md` et citer sa preuve.
   Un seul critère non démontré ⇒ verdict `NO_GO`, fin du skill.
3. `python3 scripts/go_live/check_go_live_readiness.py --assert-ready` doit rendre 0 sur le
   SHA exact ; sinon `NO_GO`.
4. Présenter : SHA, digests, migrations à appliquer, sauvegarde prévue et vérifiée,
   rollback, fenêtre, commandes exactes.

## Porte humaine

Demander l'autorisation production explicite pour ce SHA et cette release. Sans réponse
explicite dans cette session : fin.

## Phase 2 — exécution (après autorisation seulement)

Suivre `docs/runbooks/go_live.md` et `docs/runbooks/rollback.md` étape par étape, chaque
commande à effet confirmée par l'humain ; sauvegarde vérifiée avant migration ; lecture
de contrôle après chaque étape ; premier écart ⇒ arrêt et décision humaine sur le rollback.

## Sortie

Verdict de préflight, puis journal horodaté des étapes, smoke et sonde de retrieval
production, état final, et ce qui reste à vérifier (G7).
