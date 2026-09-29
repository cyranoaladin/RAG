---
paths:
  - "scripts/go_live/**"
  - "scripts/qualification/**"
  - "docs/reports/go_live/**"
  - "docs/runbooks/**"
  - "services/rag-engine/infra/docker-compose*.yml"
  - ".github/workflows/promote.yml"
  - ".github/workflows/production-image-provenance.yml"
---

# Go-live, staging et runbooks

- `GO_LIVE: NO_GO` tant que `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md` n'est pas
  intégralement démontré ; seul `check_go_live_readiness.py --assert-ready`
  exécuté en direct conditionne un déploiement.
- Les fichiers de `docs/reports/go_live/` générés par un script (bannière
  « Fichier derive ») ne s'éditent jamais à la main : relancer le producteur.
- Un instantané committé (`go_live_readiness_state.json`, README, rapports) porte
  son SHA d'évaluation ; il n'est jamais l'état courant.
- Un script go-live échoue fermé : entrée absente ou ambiguë ⇒ code non nul,
  jamais de valeur par défaut permissive. Tout nouveau vérificateur a ses tests
  de refus dans `scripts/tests/` ou `scripts/qualification/tests/`.
- Les plans d'exécution (`*_EXECUTION_PLAN.md`) fixent l'ordre, les SHA, les
  empreintes et les points d'arrêt humains ; les suivre, ne pas les réinterpréter.
- Une autorisation ou attestation s'enregistre pendant que sa PR approuvée est
  OUVERTE, puis on fusionne ; l'inverse échoue définitivement.
- Toute opération serveur passe par `/staging-operation` ou `/production-deploy`,
  invoqués par un humain.
