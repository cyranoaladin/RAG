# ROADMAP — Plateforme RAG pédagogique (Nexus)

> Décision fondatrice : ADR-0001 (séparation plan de contrôle / plan de données / cockpit).
> Cette feuille de route est organisée en **gates** vérifiables jusqu'à l'exploitation.
> Les statuts datés sont des lectures LIVE : les relire (`/project-status`) avant toute décision.

## But terminal

Code complet et qualifié → gouvernance auditée → corpus cible ingéré → staging peuplé et
vérifié → retrieval qualifié sur tous les scopes → `GO_LIVE_READY` démontré mécaniquement →
déploiement et validation production → exploitation durable → retrieval exposé de façon
contrôlée à des agents externes.

## Gates

Une gate est franchie quand sa preuve de sortie est archivée dans un rapport de lot.

| Gate | Objet | Preuve de sortie | Statut au 29/09/2026 (LIVE, à relire) |
|---|---|---|---|
| **G0** — Développement et migrations | Code des trois services et migrations nécessaires au premier cut, qualifiés | CI `main` verte ; HEAD des deux chaînes de migrations figés pour le cut | En cours : `ingestion_control` à `019` sur `main` ; migration `020` en PR (#271) |
| **G1** — Gouvernance | Autorités LOT41A/LOT42, décisions PII, droits, actualité, scopes r4 pour chaque collection du cut | Artefacts actifs fusionnés, ADR acceptés, gardes de gouvernance vertes | En cours : activation HGGSP en PR brouillon (#270) ; revue V4 #262 approuvée non fusionnée ; PR historiques ouvertes à disposer |
| **G2** — Corpus et release | Release(s) scellée(s) du premier cut, manifestes et provenance vérifiés | Manifestes, empreintes recalculées, ADR d'adoption | V4 scellée ; successeur HGGSP construit, autorisation `PROPOSED_INACTIVE` |
| **G3** — Ingestion staging | Staging dédié peuplé de toute la release, jobs terminés | Cardinalités mesurées = attendues (11 / 315 / 479 / 8 268, à recalculer) | Partiel : V4 hors HGGSP (9 / 263 / 405 / 5 678, journaux opérateur) ; HGGSP non publié |
| **G4** — Vérification indépendante du retrieval | Sonde indépendante sur tous les scopes, évaluation qualité (golden set revu) | Rapport de sonde zéro non-conformité ; métriques ≥ seuils décidés | Non franchie |
| **G5** — `GO_LIVE_READY` | Tous les critères de `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md` | `check_go_live_readiness.py --assert-ready` = 0 en direct + dossier de preuves | `NO_GO` |
| **G6** — Migration et déploiement production | Autorisation production, sauvegarde vérifiée, migrations, images par digest, bascule | Journal d'opération `/production-deploy` | Non commencée |
| **G7** — Validation production | Smoke, sonde de retrieval production, cardinalités production | Rapport de validation production | Non commencée |
| **G8** — API agents externes | Accès authentifié par client, quotas, révocation (`docs/agentic/EXTERNAL_AGENT_ACCESS.md`) | ADR d'ouverture, tests de refus, client pilote sondé | Non commencée (existant : `/search/v2`, triple credential) |
| **G9** — Adaptateur MCP (optionnel) | Traduction MCP du même contrat, sans droit supplémentaire | Tests de parité API/MCP | Non commencée |
| **G10** — Exploitation | Observabilité, alertes, sauvegarde/restauration exercées, rollback, runbooks à jour, rotation des secrets | Exercices datés, runbooks relus | Non franchie : `rollback.md` et `rag_incident_response.md` décrivent encore l'ancienne pile |

Ordre : G0–G2 peuvent avancer en parallèle ; G3 exige G1 et G2 pour la release visée ;
G4 exige G3 ; G5 exige G0–G4 ; G6 exige G5 et une autorisation humaine explicite ;
G8 exige G7 ; G10 se construit dès G3 et doit être franchie avant G8.

## Premier cut production

Cible logique actuelle : **11 collections, 315 artefacts, 479 placements, 8 268 chunks**
(V4 hors HGGSP + successeur HGGSP, ADR-0062). Ces nombres sont une cible de contrôle
dérivée des manifestes, pas une mesure ; ils changent avec la release.

## Mise à l'échelle (après G7)

Autres niveaux et matières, track AEFE (`aefe_*`), cockpits correspondants, par réplication
de la chaîne gouvernée — chaque extension repasse G1 → G5 pour son périmètre.

## Cadence

Un lot = une branche = une PR = un rapport. Les décisions structurantes sont gelées en ADR
avant le code. Aucune gate n'est déclarée franchie sur la foi d'une CI verte ou d'un rapport
antérieur. Modèle opératoire : `docs/agentic/OPERATING_MODEL.md`.

## Annexe — phases initiales (historique)

Plan d'origine, conservé pour la traçabilité ; les gates ci-dessus le remplacent.

| Phase | Lots | Objet | État |
|---|---|---|---|
| 0 — Fondations | 0 | Monorepo, `nexus-contracts`, CI racine | Livré |
| 1 — Plan de données | 1.1–1.3 | Parsing/chunking, pgvector, retrieval hybride filtré | Livré (runtime v2, ADR-0024) |
| 2 — Couture | 2.1–2.2 | API retrieval interne, gold set | API v2 livrée ; évaluation → G4 |
| 3 — Cockpit MVP | 3.1–3.3 | Auth, profil, agent UI sourcé | BFF Auth.js livré ; génération verrouillée |
| 4 — Ingestion agentique | 4.1–4.3 | Découverte, admission, worker gouverné | Chaîne `quality → gate → review` + releases scellées |
| 5 — Mise à l'échelle | 5.x | Autres niveaux, AEFE | Après G7 |
| 6 — Industrialisation | 6.x | Observabilité, RGPD, prod | → G6, G7, G10 |

ADR structurants : ADR-0001 (séparation), ADR-0024 (runtime v2 lecture/revue fail-closed),
ADR-0025 (autorité de revue humaine GitHub) ; registre complet : `docs/adr/`.
