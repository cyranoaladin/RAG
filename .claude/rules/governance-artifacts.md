---
paths:
  - "governance/**"
  - "services/rag-pedago/configs/**"
  - "scripts/governance-locks.baseline"
  - "scripts/authority-uniqueness.baseline"
  - "scripts/github/**"
  - "docs/adr/**"
---

# Artefacts de gouvernance

- Autorisations, décisions PII, revues de publication et ancres de confiance sont
  des décisions humaines scellées : un agent ne les rédige qu'en proposition
  (`proposed/`, `PROPOSED_INACTIVE`) et ne les active jamais lui-même.
- Activer = `git mv` de la proposition vers l'emplacement actif, dans une PR
  dédiée, avec l'ADR qui l'autorise et une approbation humaine sur le head exact.
- Ne jamais modifier une autorisation déjà fusionnée : la révoquer ou la
  remplacer par une nouvelle, référencée.
- Un verrou `*_allowed` ou une ligne de `governance-locks.baseline` ne change
  jamais par effet de bord ; `scripts/check-governance-locks.sh` doit rester vert.
- Un ADR accepté n'est pas réécrit : un nouvel ADR le remplace. Le numéro suit le
  registre des ADR (`ls docs/adr`) ; vérifier qu'aucune PR ouverte ne l'occupe.
- Jamais d'auto-approbation de PR ; la revue de confiance est définie par
  `scripts/github/trusted-reviewers.json` et `trusted_human_review.py`.
- Aucune PII élève ni valeur de secret dans ces fichiers : des empreintes seulement.
