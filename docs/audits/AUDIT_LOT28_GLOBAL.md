# AUDIT GLOBAL — LOT 28 : mise au point, couverture tous niveaux, ingestion continue, dashboard rag-ui v2

**Date** : 26 juillet 2026
**Auditeur** : Kimi (agent de codage), pour Nexus Réussite
**Périmètre** : dépôt `cyranoaladin/RAG` complet + production `rag-ui.nexusreussite.academy` (d'après LOT 20 et AUDIT_FRONTEND du 02/07/2026)
**Méthode** : lecture intégrale du dépôt (README, AGENTS.md, 14 ADR, rapports de lots, code des 3 services, contrats, taxonomies, corpus, configs), réconciliation avec les inventaires de production existants.
**Règles respectées** : AGENTS.md (pas d'écriture sur `main`, pas de secret, pas de chemin absolu machine-local, pas de levée de verrou sans ADR).

---

## 1. Résumé exécutif

Le dépôt est **architecturellement sain et très bien gouverné** (séparation 3 plans, contrat partagé, gates qualité, CI locale, ADR systématiques), mais il est **fonctionnellement incomplet** au sens de la demande :

1. **Couverture pédagogique étroite** : le corpus ne contient que 13 fiches lycée et les taxonomies ne couvrent qu'une fraction du catalogue de collections (16 fichiers taxonomiques référencés sont **absents**). 32 collections sur 35 sont déclarées `instanciee: false`.
2. **Ingestion agentique présente mais non continue** : les agents Orchestrateur/Niveau/Matière existent (ADR-0005), la whitelist contient déjà eduscol, mais il n'existe **ni planificateur (scheduler), ni politique d'ingestion continue, ni boucle de surveillance des sources**.
3. **Double monde non convergé** : la production `rag-ui` (Streamlit + ChromaDB 768 dim, 17 912 vecteurs, 8 collections, 3 rubriques cassées) est **totalement déconnectée** du moteur gouverné (pgvector 1024 dim e5-large). Le code prod diverge du dépôt (I-05, non résolu).
4. **Cockpit vide** : `services/cockpit/` est un placeholder ; le dashboard moderne demandé n'existe pas.

Le lot 28 livre : (a) cet audit, (b) l'arborescence corpus complète 3e→Terminale avec fiches de référentiel par nœud, (c) les 16 taxonomies manquantes + extension du catalogue de collections, (d) des agents d'ingestion continue eduscol gouvernés (staging-only, aucun verrou levé), (e) le cockpit v2 (SPA React) prêt à brancher sur l'API retrieval, (f) ADR-0015/0016/0017 et le runbook de déploiement.

---

## 2. État des lieux détaillé

### 2.1 Architecture (conforme, à conserver)

| Plan | Service | État | Verdict |
|---|---|---|---|
| Contrôle | `services/rag-pedago` | Taxonomies, acquisition, gates, review, ledger, agents requête `context_only` | **Conforme** |
| Données | `services/rag-engine` | pgvector 1024d, `/search` lecture seule, rerank MiniLM, security_v2 fail-closed | **Conforme** |
| Contrat | `packages/contracts` | `nexus-contracts` 0.2.0, modèles Pydantic, HMAC profils | **Conforme** |
| UI SaaS | `services/cockpit` | Placeholder README uniquement | **À construire (lot 28)** |

Points forts à préserver absolument :
- Invariant anti-écriture directe : `quality → gate → review` avant toute indexation pgvector.
- Invariant M-04 : seules les collections `instanciee: true` sont créées/exposées ; pas d'auto-création.
- Fetch gouverné : GET-only, whitelist de 7 domaines (dont `eduscol.education.gouv.fr` et `cache.media.eduscol.education.gouv.fr` — **eduscol est déjà admis**), robots.txt, rate limit 2 s, timeout 30 s, 10 Mo max, User-Agent identifié.
- Droits résolus **par provenance**, jamais par classification de texte ; quarantaine dédiée non retrievable.

### 2.2 Couverture corpus (insuffisante)

| Zone | Existant | Manquant |
|---|---|---|
| `corpus/Tronc_commun` | 7 fiches (EAF, philo, HG, EMC, ES, LV, EPS) | Niveaux 2de/3e absents ; granularité unique |
| `corpus/Specialites` | 6 fiches (maths, NSI, PC, SES, SVT, HGGSP) | LLCE, AMC, NSI 1re, HLP, BCPST hors scope v1 (OK), droit/éco STMG |
| Référentiels | `REFERENTIEL_CANDIDAT_LIBRE.md` | DNB, EAF détaillée, Grand Oral détaillé, épreuve anticipée maths |
| Collège (3e) | 1 taxonomie français | Toutes les autres matières |
| Seconde | quasi rien | Tronc commun complet + SNT |

### 2.3 Taxonomies vs catalogue de collections

Le catalogue `rag_collections.yml` (35 entrées) référence des fichiers taxonomiques **absents** du dépôt — tout agent `LevelAgent` qui tenterait de les instancier échouerait :

```
exams/dnb.yml
francais/seconde_tc.yml
maths/premiere_gen_specialite.yml        maths/premiere_gen_tronc_commun.yml
maths/premiere_stmg_tc.yml               maths/terminale_gen_specialite.yml
maths/terminale_gen_option_comp.yml      maths/terminale_gen_option_exp.yml
maths/terminale_stmg_tc.yml
physique_chimie/terminale_specialite.yml ses/terminale_specialite.yml
stmg/droiteco_premiere.yml               stmg/droiteco_terminale.yml
stmg/msdgn_terminale.yml                 svt/terminale_specialite.yml
```

**Constat bloquant** : 16 taxonomies manquantes → 16 collections non instanciables. Le lot 28 les fournit (§5 du rapport de lot).

### 2.4 Agents d'acquisition (bons fondements, pas de continuité)

- `OrchestratorAgent → LevelAgent → SubjectAgent` : découverte des taxonomies par niveau, priorisation par correspondance BO (`bo_not_found` d'abord), dépôt en staging uniquement. **Conforme ADR-0005.**
- `scrapers/taxonomy_fetcher.py` : récupère depuis Wikipedia/Wikiversité (CC-BY-SA) avec contrôle de substance.
- `scrapers/discovery.py` : détecte déjà le type `eduscol` par domaine.
- **Manques** : aucun agent dédié eduscol (pages programmes, ressources pédagogiques, annales), aucun scheduler (cron/systemd), aucune politique de ré-ingestion (détection de changement, TTL), aucun budget de temps/taux.

### 2.5 Production rag-ui (à reconstruire)

D'après LOT 20 + AUDIT_FRONTEND (02/07/2026), inchangé depuis :

| Composant | État prod | Problème |
|---|---|---|
| UI | Streamlit `app_v2.py` | 3 rubriques cassées (Maths 1re, Web3, Divers) ; auto-création de collections vides au clic |
| Ingestor | FastAPI legacy | Code divergent du dépôt (91 501 o vs 90 357 o) |
| Vecteurs | ChromaDB 768 dim, 17 912 vecteurs | 9 199 chunks admissibles vers le moteur gouverné ; `nsi_corpus` et `rag_math_correction` hors mapping |
| Moteur gouverné | pgvector 1024 dim | **Non connecté à l'UI** |

Le lot 28 fournit le cockpit v2 (SPA) et le runbook de bascule ; la migration des 9 199 chunks admissibles reste un lot ultérieur (elle exige la chaîne `quality → gate → review`, non contournable).

---

## 3. Écarts et risques (registre)

| ID | Écart | Gravité | Traitement lot 28 |
|---|---|---|---|
| E-01 | 16 taxonomies référencées absentes | Bloquant | Fournies |
| E-02 | Corpus sans arborescence par niveau | Majeur | Arborescence complète 3e→Tle |
| E-03 | Pas d'ingestion continue | Majeur | Agents + scheduler gouvernés |
| E-04 | UI prod cassée et déconnectée | Majeur | Cockpit v2 + runbook bascule |
| E-05 | Code prod divergent du dépôt (I-05) | Majeur | Runbook impose rebuild depuis le dépôt |
| E-06 | `answer_generation_allowed: false` | Verrou | **Non levé** — cockpit en mode recherche/contexte sourcé uniquement |
| E-07 | Séries technologiques hors STMG hors scope v1 | Accepté | Convention voie extensible documentée (ADR-0015) |

---

## 4. Plan de convergence (phases)

- **Phase A (ce lot)** : audit, corpus, taxonomies, catalogue, agents continus (staging-only), cockpit v2, ADR, runbook. Aucun verrou levé.
- **Phase B (lot suivant)** : revue humaine des stagings lot 28 → `gate → review` → instanciation progressive des collections (`instanciee: true` par vague : NSI déjà fait, puis maths Tle/1re, puis tronc commun Tle, puis 2de/3e).
- **Phase C** : migration gouvernée des 9 199 chunks prod admissibles ; décommissionnement ChromaDB legacy ; bascule DNS du dashboard vers le cockpit v2.
- **Phase D** (ultérieur, ADR requis) : génération de réponse (`answer_generation_allowed`) uniquement après preuve de complétude de couverture sur périmètre réel.
