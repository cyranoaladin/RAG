# ADR-0013 — Convergence dual-engine

**Statut** : accepté
**Date** : 30 juin 2026
**Constats traités** : F-02, A-01, F-14, F-38
**Historique** : `docs/audits/ADR_CONVERGENCE_DRAFT.md` (brouillon v5, LOT 20)

---

## Contexte

Deux chaînes RAG incompatibles coexistent : un moteur historique (nomic-embed-text 768 dim, ChromaDB, Ollama) et un pilote gouverné (e5-large 1024 dim, pgvector, sentence-transformers). Les dimensions sont physiquement incompatibles. Le script `migrate_chroma_to_pgvector.py` est inopérant (préserve les vecteurs sans recalcul). Le code prod diverge du dépôt (91 501 o vs 90 357 o, `COLLECTION_MAP` et fallback différents).

## Décisions

### Modèle et store (A-1)

**intfloat/multilingual-e5-large (1024 dim) + pgvector dédié**, instance séparée de `nexus_prod`. Pas de colocalisation de l'index RAG dans la base applicative à PII.

### Stratégie de migration (A-2, amendée le 25 août 2026)

Shadow puis canary (D-4), avec rollback de trafic versionné, borné et testé.
La formulation historique « rollback nginx en une ligne » est supersédée :
aucune mutation Nginx ad hoc n'est admise. Toute bascule ou restauration exige
les preuves et gates décrits dans l'amendement ci-dessous.

### Génération (A-3)

G-3 transitoire (UI legacy conserve la génération) → G-1 cible (génération gouvernée sous citation obligatoire). Lever de `answer_generation_allowed` par un ADR distinct, postérieur à la résolution de F-01. Cet ADR ne lève aucun verrou.

### Droits (A-4, A-5)

`rights` résolu **par provenance uniquement**, jamais par classification de texte. Contenu Nexus-owned → droits connus ; contenu tiers → droits à établir explicitement ou quarantaine (`rag_nexus_quarantine`).

### `nsi_corpus` (A-6)

Re-ingestion par la chaîne gouvernée depuis les sources `rag-pedago`, après vérification d'existence/correspondance.

### `rag_francais_premiere` (A-7, amendé)

Correction des métadonnées (niveau faux) puis indexation dans la collection fine correspondante. Granularité matière×niveau×statut, pas de fusion dans un silo `rag_nexus_education`.

### Interface (D-M03)

Cible unique = cockpit Next.js, **différé après le LOT 25**. Aucun développement UI dans les lots intermédiaires. Streamlit legacy gelé en l'état (admin/ingestion uniquement). Rejet de l'hybride (coût double, problème prématuré).

### Périmètre d'instanciation initial (D-PERIMETRE)

1. `rag_nexus_nsi_terminale_specialite` — première collection prouvée de bout en bout
2. `rag_nexus_nsi_premiere_specialite` — instanciée juste après
3. `rag_nexus_quarantine` — instanciée d'emblée
4. Français : différé (J-06 non résolu, source unique, droits non établis)
5. Toutes les autres : non instanciées (M-04), restent au catalogue

### Dérive prod ↔ dépôt

Le moteur gouverné **remplace** la prod — la dérive n'est pas reportée. Les comportements prod spécifiques (`score_threshold`, `maths_premiere_fallback`, routing par `section`) sont captés comme spécification de régression et évalués individuellement.

## Arborescence de collections cible

Convention : `rag_nexus_{matiere}_{niveau}_{statut}`. 22 entrées au catalogue taxonomique. Chaque collection porte un flag `instanciee` ; seules les instanciées sont exposées à l'UI (invariant M-04 : peuplé et gouverné uniquement).

Exceptions nommées : `rag_nexus_grand_oral_terminale`, `rag_nexus_exams_bac_general`, `rag_nexus_exams_anticipee_maths`, `rag_nexus_candidats_libres_terminale`, `rag_nexus_quarantine` — cf. `rag_collections.yml` pour le détail.

## Invariants

1. **Pas d'auto-création de collection** — le moteur lève une erreur si la collection n'est pas déclarée instanciée. Pas de `get_or_create_collection`.
2. **Pas de rubrique UI pointant une collection vide** (M-04).
3. **Réentrée par la gouvernance** (C-03) — tout chunk passe par `quality → gate → review` avant indexation.
4. **Re-chunking exige les documents GDrive originaux** (I-03) — mode dégradé documenté si indisponible.

## Table de régression au cutover

Cf. `PROD_INVENTORY_rag-ui.md` §13. Fonctionnalités à traiter : `score_threshold`, `maths_premiere_fallback` (non-fonctionnel par construction L-01), `/rag/query`, filtres `groupe`/`type_ressource`, routing par `section`, auth Bearer → HMAC, rubriques UI.

## Backlog

- Compléter la taxonomie : options hors maths, maths complémentaires/expertes, enseignement scientifique, EMC (O-03)
- Résoudre J-06 (niveau réel `rag_francais_premiere`) avant toute instanciation française
- Benchmark débit e5-large CPU (I-04, LOT 25)

## Conséquences

- Le LOT 21 pose l'infrastructure (pgvector dédié, `rag_collections.yml`, table `rag_chunks`, invariant anti-auto-création).
- Le LOT 22+ exécute la chaîne citations → évaluation → hybride → chunker sur NSI Terminale.
- Le cockpit Next.js est développé après le LOT 25.

## Amendement du 25 août 2026 — frontière de convergence exécutable

Le moteur B est confirmé comme seule architecture canonique. Le moteur A reste
une surface de compatibilité ou de rollback tant que les preuves réelles de
parité, restauration et bascule ne sont pas toutes obtenues. Cet amendement ne
change aucun verrou `*_allowed`, n'autorise aucune publication et ne
décommissionne aucun composant A.

### Migration directe interdite

`services/rag-engine/scripts/migrate_chroma_to_pgvector.py` est un tombstone
exécutable. Toute invocation refuse avant import d'un client Chroma,
PostgreSQL, Docker ou réseau. Les vecteurs `nomic-embed-text` de dimension 768
ne sont jamais copiés dans l'index e5-large de dimension 1024. La seule voie
admise est une réingestion depuis une source reconstructible, avec extraction,
re-chunking, embedding canonique et passage complet par
`quality → gate → review`.

### Politique et inventaire legacy fermés

La politique `NEXUS-ENGINE-CONVERGENCE-V1` fixe :

- `canonical_engine=B` et le contrat `nexus-contracts` comme source de vérité ;
- l'état de chaque capacité A : `compatibility_only`, `rollback_only` ou
  `blocked` ;
- les neuf collections legacy découvertes et leur disposition par défaut ;
- seulement deux cibles NSI fines lorsque la source, le scope et les preuves
  sont exacts ;
- `cutover_status=NO_GO`.

Une capture `NEXUS-LEGACY-CAPTURE-V1` est produite en lecture seule hors de la
frontière de préparation. Elle doit identifier Chroma, les deux SQLite
`catalog.sqlite` et `drive_sync_state.db`, pgvector, uploads, configurations,
images et modèles. Chaque objet découvert reçoit exactement une disposition :
`REINGEST_GOVERNED`, `REVIEW_REQUIRED`, `QUARANTINE`, `IGNORE_EMPTY` ou
`BLOCKED`. Un doublon reste compté et pointe vers son objet canonique. Le
manifeste de préparation ne transporte ni contenu, ni embedding, ni droit de
retrieval, ni autorisation de publication ; `migration_complete` demeure
`false`.

### Parité sur unité canonique

L'unité comparable entre A et B est le triplet exact :

`source_sha256 + canonical_span_id + content_hash`.

Le témoin scelle une allowlist de requêtes, `k`, scopes attendus, contexte
d'accès canonique et passages attendus. Les captures A/B portent des résultats
ordonnés, citations, droits canoniques et statut de revue. Le comparateur local :

- refuse les fichiers non réguliers, les entrées surdimensionnées, les
  schémas ouverts et les identifiants sensibles ;
- calcule rappel, rang réciproque du passage primaire, couverture et
  divergence positionnelle ;
- rend `FAIL_CLOSED` pour toute fuite de collection/niveau/scope, citation
  incomplète, droit inconnu ou incompatible avec le contexte, divergence de
  droits A/B sur le même passage, résultat non revu ou témoin hors collection ;
- rend seulement `METRICS_ONLY_THRESHOLDS_UNAPPROVED` en l'absence de seuils
  opérateur approuvés.

Les fixtures du Lot 2 sont marquées `SYNTHETIC_TEST_ONLY` et
`NOT_REAL_PARITY_EVIDENCE`. Elles prouvent le calcul et les refus, jamais la
parité des données réelles.

### Quiescence et preuve de cutover non substituable

Une capture A destinée à la migration ou au rollback exige : writers et tâches
planifiées désactivés, fenêtre UTC de 24 heures au maximum, ordre de capture
Chroma → catalogue SQLite → état Drive SQLite → uploads, et mêmes comptes et
digests avant/après. Ces comptes et digests sont liés aux inventaires A ; le
backup pgvector est lié à l'identité de base, au head de migration et au digest
de l'inventaire B.

Le manifeste `NEXUS-ENGINE-CUTOVER-V1` impose pour ce lot la topologie active
A, canary B, rollback A et au moins un smoke borné visant B. Il distingue cinq
faits qui ne peuvent jamais se substituer :

1. snapshot restauré et vérifié ;
2. parité réelle exécutée ;
3. restore rehearsal vérifié ;
4. rollback de trafic testé ;
5. cutover autorisé.

Chaque fait positif exige son propre type d'évidence scellée. Le validateur du
Lot 2 interdit en plus tout fait positif et tout verdict `READY`,
`GO_LIVE_READY` ou synonyme. Son seul verdict admissible est `NO_GO`.

### Conditions de sortie du dual-engine

Le moteur A ne peut être arrêté ou supprimé qu'après une capture réelle
exhaustive, une réingestion gouvernée complète, une parité A/B réelle sur le
corpus figé, un backup restauré en environnement isolé, un canary observé, un
rollback de trafic exécuté et une autorisation opérateur/trusted-human-review
liée au head exact. L'absence d'un seul de ces éléments maintient le cutover à
`NO_GO`.
