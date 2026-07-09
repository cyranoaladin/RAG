# ADR-0014 — Cadre de convergence RAG (cyranoaladin/RAG ↔ rag-local ↔ RAG-Anything)

- **Statut** : proposé
- **Date** : 2026-07-09
- **Décideur** : Lead engineering (Conduite LOT 26)
- **Lot** : 26.1
- **Référence de cadrage** : `docs/reports/lot_26_cahier_charges_fusion_rag.md`, introduit par la PR #48, mergée.

---

## Contexte

Le lot 26 impose une convergence contrôlée entre trois sources techniques sans rupture de service :

- dépôt canonique `cyranoaladin/RAG` (pilotage ADR, CI, gouvernance) ;
- historique `cyranoaladin/rag-local` (opérations VPS, ingestion legacy, UI Streamlit, Drive/URL uploads, observabilité) ;
- `cyranoaladin/RAG-Anything` (capacités d'extraction multimodale utiles).

Le système actuel doit rester gouverné, sans dette volontaire, avec séparation stricte plan de contrôle / plan de données / cockpit.

## Décisions

### D1 — Dépôt canonique et répartition des responsabilités

Le dépôt **`cyranoaladin/RAG`** reste l’unique base d’autorité d’évolution.

- `services/rag-pedago` : gouvernance, taxonomie, review, contrôle qualité, profils.
- `services/rag-engine` : moteur de données, ingestion v2 et retrieval.
- `services/cockpit` : façade SaaS par niveaux/profils (sans accès direct à pgvector).
- `packages/contracts` : contrats partagés versionnés.

Aucune fusion “à plat” de dépôt externe ne sera réalisée.

### D2 — Rag-local en mode legacy source de robustesse

`rag-local` n’est **pas** fondue dans le code courant. Il est conservé en tant que source documentaire/technique legacy pour :

- ingestion UI admin existante (Streamlit) en mode transitional;
- ingestion upload/URL/Drive historiques;
- nginx + observabilité + scripts de smoke déjà stabilisés;
- logique de parsing et d’exploitation opérationnelle utile.

Les nouveaux parcours v2 n’utilisent pas ChromaDB et n’intègrent pas de réutilisation directe de code métier legacy sans contrat.

### D3 — RAG-Anything intégré comme adaptateur optionnel

`RAG-Anything` est intégrable **uniquement** comme adaptateur multimodal.

- Il peut améliorer la normalisation d’extraction de blocs multimodaux.
- Il **ne devient pas** backend de stockage RAG.
- Il ne remplace pas la base de vérité pgvector ni `rag_chunks`.

L’activation est optionnelle ; fallback texte obligatoire si dépendances adaptateur absentes.

### D4 — Coexistence contrôlée legacy / v2

Le système reste en période de transition avec deux plans techniques coexistant :

- v2 = cible opérationnelle (pgvector 1024d, `review_status`, collection catalogue piloté).
- legacy = continuité opérationnelle (pipeline historique).

Règles d’isolation :

- La recherche élève des nouveaux parcours lit uniquement `rag-engine` v2.
- Aucun fallback legacy silencieux n’est autorisé.
- Legacy peut rester exploité uniquement pour continuité opérationnelle ou migration, jamais comme fallback invisible du flux élève v2.

### D5 — Collections : dérive historique vs catalogue courant

Le catalogue `services/rag-engine/configs/rag_collections.yml` est la référence v2 opérationnelle.

- les noms sont de type `rag_nexus_<matiere>_<niveau>_<statut>` (avec exceptions nommées documentées);
- chaque entrée possède un drapeau `instanciee` ; l’accès v2 n’est autorisé que si `instanciee: true`;
- il n’y a **aucune auto-création** de collection;
- le mapping legacy (si utilisé) reste explicite et ne pilote pas la logique v2.

Les collections historiques connues en legacy restent listées pour compatibilité opérationnelle et migration, mais ne prévalent pas sur le contrat v2.

### D6 — Nomenclature tenant / audience

Le moteur v2 ne réintroduit pas `{population}_{niveau}` comme règle opérationnelle.

La base de vérité v2 reste `collection / niveau / audience / matière / statut` selon :
- `services/rag-engine/configs/rag_collections.yml`
- `packages/contracts`.

`{population}_{niveau}` est une convention historique présente dans certains documents, traitée comme dette documentaire ou compatibilité legacy.

Aucun nouveau lot v2 ne doit propager cette convention sans ADR dédié.

Toute évolution de nomenclature tenant/audience doit être décidée par ADR séparé.

### D7 — Stratégie shadow/canary/rollback (obligatoire)

1. **Shadow** : ingestion/validation en parallèle sans exposition élève v2 automatique.
2. **Canary** : activation de collections validées par lot, observabilité dédiée et rollback immédiat.
3. **Rollback** : rétablissement vers la configuration précédente en une opération inverse contrôlée.

Le déploiement de production n’est pas initié par ce lot.

### D8 — Invariants LOT 26 confirmés

- `review_status = needs_review` ne doit jamais être servi au flux élève.
- 1024 dimensions pour `rag_chunks` cible v2.
- aucun code v2 nouveau ne doit écrire dans ChromaDB.
- aucune écriture directe pgvector hors pipeline `quality → gate → review`.
- aucune fusion sans ADR ; aucune levée de verrou sans procédure `transition_authorization` + baseline.

## Conséquences

- Lot 26 est séquencé en PR atomiques; le lot 26.1 est purement documentaire (ADR+rapport).
- Les lots suivants peuvent implémenter : rôle v2, fail-closed search, review workflow, ingestion Drive v2, contrats, adapter optionnel, cockpit.

## Références

- `docs/reports/lot_26_cahier_charges_fusion_rag.md` (dans la base `main` suite au merge de #48).
- Référence de cadrage à PR #48 : fichier disponible dans `main` (PR mergée).
- `services/rag-engine/configs/rag_collections.yml` (contrat catalogue actif).
- `services/rag-engine/src/ingestor/collection_config.py` (résolution v2).
- `docs/adr/ADR-0001-separation-controle-donnees-cockpit.md`
