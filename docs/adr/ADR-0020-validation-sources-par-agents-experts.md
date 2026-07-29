# ADR-0020 — Validation des sources par agents experts (substitution à la validation humaine)

- **Statut** : proposé (LOT 31, revue PR #74 round 10)
- **Date** : 2026-07-27
- **Décideur** : Alaeddine BEN RHOUMA (fondateur, Nexus Réussite)
- **Amende** : `services/rag-pedago/AGENTS.md` (interdiction « validation humaine »)
- **Complète** : ADR-0018 (revue par agents experts), ADR-0019 (validation agentique des sources)

## Contexte

Directive fondatrice (lots 29-31, juillet 2026) : « les reviews et les
vérifications humaines doivent être remplacées obligatoirement par des reviews
et de validation par des agents experts et spécialisés ».

L'interdiction historique de `services/rag-pedago/AGENTS.md` exigeait une
« validation humaine » avant toute nouvelle lecture de `source_uri`. La revue
PR #74 (round 10) a objecté — à juste titre — que l'activation de sources ne
peut reposer que sur des verdicts d'agents *non enregistrés comme approbation*.

Le présent ADR **est** cet enregistrement : la décision humaine est prise ici,
une fois, à niveau fondation ; son exécution est déléguée à une chaîne
agentique gouvernée, vérifiable et révocable.

## Décision

1. **Substitution.** La validation agentique gouvernée **remplace** la
   validation humaine pour l'activation des sources (`to_verify` → `verified`)
   couvertes par la chaîne suivante, intégralement satisfaite :
   - verdicts **signés** du `source_validator` à sa **version courante**
     (`VALIDATOR_VERSION`, actuellement `source_validator_v4`) ;
   - verdict **lié au contenu** relu (`content_sha256`) et à la **provenance
     réelle** (`final_url`, droits revalidés après redirections) ;
   - fetch gouverné : whitelist, robots.txt, GET-only, UA identifié,
     crawl-delay configuré à chaque saut, kill-switch `network_allowed` ;
   - portes **fail-closed** de l'export : schéma courant exigé, **signature
     recalculée** cryptographiquement, ledger intègre (ligne malformée =
     refus), liste legacy gelée (id **et** URL) ;
   - **preuve versionnée** : `docs/validation/source_validation_evidence.json`.
2. **Revalidation forcée.** Toute évolution des règles de revue **bump
   `VALIDATOR_VERSION`** : les verdicts antérieurs deviennent périmés et les
   sources concernées doivent être revalidées avant bascule/export
   (démontré rounds 8-9 de la PR #74).
3. **Périmètre.** Sources eduscol whitelistées. Hors périmètre (validation
   humaine ou ADR dédié toujours requis) : nouvelle provenance hors whitelist,
   droits inconnus (quarantaine — règle dure non délégable), toute source
   hors `eduscol_sources.yml`.
4. **Amendement.** `services/rag-pedago/AGENTS.md` référence cette
   substitution dans son interdiction d'ajout de lecture de `source_uri`.

## Conséquences

- Les 3 sources LOT 31 (`eduscol_langues_voie_gt`, `eduscol_dnb`,
  `eduscol_grand_oral`) sont activées au titre de la présente décision, sur
  verdicts v4 signés consignés dans la preuve versionnée.
- Toute activation future sans verdict conforme fait échouer l'export
  (exit 1) — la règle est auto-appliquée, pas déclarative.
- La substitution reste **révocable** par le fondateur via un nouvel ADR.
