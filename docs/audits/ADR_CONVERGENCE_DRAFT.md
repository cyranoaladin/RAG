# PROJET D'ADR — Convergence dual-engine (SUPERSEDED)

**Statut** : SUPERSEDED par `docs/adr/ADR-0013-convergence-dual-engine.md`. Ce document est un historique figé. Ne plus le modifier — ADR-0013 + `rag_collections.yml` sont les seules sources de vérité.
**Constats traités** : F-02, A-01, F-14, F-38.
**Date** : 30 juin 2026.

---

## 1. Décisions actées (lead)

| Ref | Décision |
|---|---|
| A-1 | Modèle/Store : e5-large 1024 dim + **pgvector dédié** (séparé de `nexus_prod`). |
| A-2 | Migration : shadow puis canary, rollback nginx en une ligne (D-4). |
| A-3 | Génération : G-3 transitoire → G-1. ADR distinct pour lever `answer_generation_allowed`. |
| A-4 | `rights` : par **provenance** uniquement. Jamais par classification de texte. |
| A-5 | Quarantaine : tout chunk sans `rights` établi par provenance → `rag_nexus_quarantine`. |
| A-6 | `nsi_corpus` : re-ingestion par chaîne gouvernée depuis sources `rag-pedago`. |
| A-7 | `rag_francais_premiere` : correction des métadonnées (niveau faux) puis indexation dans la collection cible correspondant à son niveau/matière réels (A-7 amendé : granularité fine, pas de fusion dans un grand silo `rag_nexus_education`). |

---

## 2. Contexte

Deux chaînes RAG incompatibles coexistent :

| | Prod | Pilote gouverné |
|---|---|---|
| Embedding | nomic-embed-text **768 dim** | e5-large **1024 dim** |
| Store | ChromaDB 1.1.1 | pgvector |
| Données | **17 912 vecteurs** actifs | 124 vecteurs dev |
| `rights` | **0 %** | 0 % |
| Code ingestor | 91 501 octets (build 28/06) | 90 357 octets — **divergent** |

Dimensions incompatibles (768 ≠ 1024). Script `migrate_chroma_to_pgvector.py` **inopérant** (préserve les vecteurs, ne recalcule pas).

### Dérive prod ↔ dépôt : remplacement, non report (J-04)

La prod diverge du dépôt (I-05). Le moteur gouverné **remplace** la prod — la dérive n'est pas reportée dans le nouveau moteur. Les comportements prod spécifiques (`score_threshold`, `maths_premiere_fallback` à 3 filtres, routing par `section`, `COLLECTION_MAP` élargi) sont captés comme **spécification de régression** (inventaire §13) et évalués individuellement pour décision d'implémentation ou de retrait documenté.

Le build-context hôte (`/srv/nexusreussite/rag-ui/compose/ingestor/`, `api.py` 91 501 o, build 28/06) doit être préservé : `docker save` des images ingestor + UI **obligatoire avant tout rebuild** (pas de registry). Emplacement consigné dans l'inventaire §6.1.

---

## 3. Stratégie de migration (D-4 : shadow + canary)

1. **Phase shadow** : nouveau moteur en parallèle (port séparé). Trafic dupliqué, résultats comparés à la baseline D-11. L'ancien continue de servir.
2. **Phase canary** : bascule progressive nginx quand recall ≥ baseline et latence ≤ 2×.
3. **Rollback** : 1 ligne nginx (remettre l'ancien proxy_pass).

---

## 4. Hébergement (C-02, A-1)

**L'index RAG est hébergé dans une instance pgvector dédiée**, séparée de `nexus_prod`.

Justification : isolation des pannes, sauvegardes indépendantes, droits séparés (le RAG n'accède pas aux PII), tuning mémoire distinct. Un nouveau conteneur `pgvector/pgvector:pg15` dans le compose RAG ou dédié.

---

## 5. Génération de réponse (C-01, A-3)

La prod expose `/rag/query` (qwen2.5:1.5b). Le contrat impose `answer_generation_allowed: false`.

**Cap** : G-3 (l'UI legacy conserve la génération pendant la transition) → G-1 (génération gouvernée sous citation obligatoire). Le lever de `answer_generation_allowed` se fait par un **ADR distinct**, **postérieur** à la résolution effective de F-01 (citations opérationnelles). Cet ADR de convergence **ne lève aucun verrou**.

---

## 6. Réentrée du corpus par la gouvernance (C-03, A-4, A-5)

### Chiffrage (I-01 corrigé)

Critère d'admissibilité : `matiere` ∧ `niveau` ∧ `source_uri` (URL). Scan exhaustif :

| Collection | Total | matiere ∧ niveau ∧ URL | Action |
|---|---|---|---|
| rag_education | 7 181 | **3 366** (46 %) | Admissibles après enrichissement `rights` par provenance |
| rag_francais_premiere | 5 948 | **5 833** (98 %) | Admissibles après enrichissement `rights` + correction `niveau` |
| nsi_corpus | 4 716 | **0** | Re-ingestion par chaîne gouvernée (A-6) |
| rag_math_correction | 67 | **0** | Quarantaine |
| **Total** | **17 912** | **9 199** (51 %) | |

### `rights` par provenance (A-4)

`rights` = 0 % sur la totalité du corpus. La résolution se fait **uniquement par provenance** :
- Contenu Nexus-owned (créé par l'équipe) → `rights: nexus_proprietaire` ou `usage_interne`
- Contenu officiel (programmes, BO) → `rights: officiel_public`
- Contenu tiers (PDFs GDrive de provenance non établie, pop B `rag_education` = 2 819 chunks) → droits à établir explicitement auprès du propriétaire, ou **quarantaine** (A-5)
- **Jamais** de classification automatique de `rights` par analyse de texte

### Pipeline

1. **Vérifier l'accès GDrive** — **préalable bloquant** (I-03). Le re-chunking heading-aware exige les documents originaux, pas les fragments ChromaDB.
2. **Extraire les documents originaux** depuis GDrive (pas depuis ChromaDB).
3. **Décomposer `education` par matière** — `rag_education` n'est pas une unité migrable, c'est un silo d'ingestion (I-08).
4. **Enrichir `rights` par provenance** (A-4) — et non par classification.
5. **Quarantaine** (A-5) : tout chunk sans `rights` établi et sans `source_uri` → `rag_nexus_quarantine`.
6. **Re-chunker** (heading-aware, ≤ 384 tokens) sur les documents originaux.
7. **Re-embedder** (e5-large 1024 dim).
8. **Dédup NSI** : `chunk_sha256` comme clé, priorité au corpus `rag-pedago` structuré (I-07).
9. **Admission** : `quality → gate → review` (AGENTS.md).
10. **Indexer** dans pgvector dédié, vers la collection fine correspondante (`rag_nexus_{matiere}_{niveau}_{statut}` selon §11 — jamais vers un silo unique).

**Mode dégradé** (si GDrive indisponible) : re-split des fragments ChromaDB par taille (≤ 384 tokens), sans hiérarchie H1/H2/H3. Perte de qualité du chunking. À documenter comme régression acceptée.

---

## 7. Re-embedding 768 → 1024 (C-04)

### Reconnaissance

Le script `migrate_chroma_to_pgvector.py` est **inopérant** : 768 ≠ 1024, dimensions physiquement incompatibles.

### Chiffrage

| Paramètre | Valeur |
|---|---|
| Documents-source à re-chunker | ~9 199 chunks admissibles → N′ chunks post re-chunking (N′ ≠ N, dépend du re-chunker) |
| Modèle | intfloat/multilingual-e5-large (560M params) |
| Device | CPU (12 cœurs, pas de GPU) |
| Débit | **Non mesuré sur le host** — benchmark à réaliser pendant le LOT 25 (unification chunker) avec ≥ 200 chunks représentatifs. Estimation conservative : 30-80 chunks/min en CPU (batch=32). |
| **Durée estimée** | **2 à 6 heures** pour ~10k chunks (à affiner après benchmark) |
| RAM requise | ~2-4 GiB pour le modèle + batch |
| **Emplacement** | Sur le host en **off-peak** (55 GiB RAM disponibles, load < 1). Host séparé non strictement nécessaire mais préférable. |

---

## 8. `nsi_corpus` — contenu non revu servi en prod (I-06, escalade)

**94 % de `nsi_corpus` a `status: needs_review`**, 6 % a un statut vide. 100 % du contenu est non revu et servi aux utilisateurs. Violation de gouvernance live.

**Recommandation** : retirer `nsi_corpus` du routing prod ou ajouter un filtre `status=reviewed`. Ce constat est **indépendant** de la migration et devrait être traité en priorité.

Re-ingestion (A-6) : depuis les sources `rag-pedago`, **après vérification** que ces sources existent et correspondent. Le corpus `rag-pedago` a ses propres gates de review — les chunks y entreront avec le statut que la chaîne de gouvernance leur attribuera.

---

## 9. Déduplication NSI post-fusion (I-07)

Après migration, les collections NSI cibles (`rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`) agrégeront :
- Chunks NSI de `rag_education` (GDrive, non structurés, ~4 362 — admissibles triés par niveau)
- Chunks NSI de `nsi_corpus` (rag-pedago, structurés, 4 716 — re-ingérés par A-6)

**Stratégie** :
- **Clé** : `chunk_sha256`
- **Priorité** : corpus `rag-pedago` (gouverné, structuré) prévaut
- **Arbitrage** : si contenu différent sur la même notion (sujet bac vs fiche cours), les deux sont conservés avec `type_doc` différents
- **Gate** : dédup avant `INSERT` lors de l'indexation

---

## 10. Table de régression au cutover

| Fonctionnalité prod | Répliquée ? | Action |
|---|---|---|
| `score_threshold` | Non | Implémenter |
| `maths_premiere_fallback` | Non | **Non-fonctionnel par construction** (L-01) : filtres (`Mathématiques`/`Première`/`EDS`) incompatibles avec le schéma réel (`NSI`/`Première et Terminale`). Ne pas répliquer tel quel ; filtrer sur schéma cohérent. |
| `/rag/query` génération | Non | G-3→G-1, ADR distinct |
| Filtres `groupe`/`type_ressource` | Non | Implémenter dans le pilote |
| Document complet (vs preview 200 c, F-19) | Partiel | Vérifier bout en bout |
| Routing par `section` | Non (table unique) | Implémenter routing collection/section |
| Auth Bearer partagé → HMAC par profil | Non | **Refonte UI Streamlit** |
| Rubriques UI (`app_v2.py`) : FR 1re, Maths 1re, Éducation, Web3, Divers, Toutes | Non (pas d'UI pilote) | Répliquer dans cockpit ou future UI |
| **Maths 1ère** : cassée (fallback non-fonctionnel par construction, L-01) | — | Documentée, non masquée (A-L03). Différée au remplacement UI. |
| **Web3** : cassée (`rag_web3` auto-créée vide, L-02/M-01) | — | Documentée, non masquée. Différée. |
| **Divers** : cassée (`rag_divers` auto-créée vide, L-02/M-01) | — | Documentée, non masquée. Différée. |
| Auto-création de collections (M-01) | Oui (prod `get_or_create_collection`) | **Interdit** dans le moteur cible. Création par gouvernance uniquement. |

---

## 11. Arborescence de collections cible (M-02, réconcilié)

### Convention de nommage unique (N-01)

Préfixe `rag_nexus_` sur toutes les collections cibles, cohérent avec le nommage existant (`rag_nexus_education`, `rag_nexus_quarantine`).

**Décision A-7 amendée** : la fusion initiale dans `rag_nexus_education` (grand domaine) est remplacée par une granularité fine (une collection par matière × niveau × statut). Ceci est nécessaire pour un filtrage performant (index B-tree par collection plutôt que `WHERE matiere=... AND niveau=...` sur une table massive) et pour l'invariant M-04 (exposer uniquement ce qui est peuplé). A-7 est amendé en conséquence : `rag_francais_premiere` est corrigée et indexée dans la collection correspondant à son niveau/matière réels, pas fusionnée dans un grand silo.

### Deux niveaux : catalogue taxonomique vs collections instanciées (N-02)

**Catalogue taxonomique** = l'ensemble des collections **possibles** dérivées de la taxonomie. C'est un périmètre cible. Une entrée du catalogue **n'implique pas** une collection créée.

**Collections instanciées** = uniquement celles peuplées (≥ 1 chunk gouverné) et passées par `quality → gate → review`. Seules les collections instanciées sont exposées à l'UI (M-04). Une collection du catalogue n'est **créée** que quand du contenu gouverné existe pour elle.

### Catalogue taxonomique (source : `services/rag-pedago/taxonomy/`)

Convention : `rag_nexus_{matiere}_{niveau}_{statut}`

| Matière | Fichier taxonomie | Niveau (enum `Niveau`) | Statut (enum `StatutEnseignement`) | Collection catalogue |
|---|---|---|---|---|
| NSI | `nsi/premiere_specialite.yml` | `premiere` | `specialite` | `rag_nexus_nsi_premiere_specialite` |
| NSI | `nsi/terminale.yml` | `terminale` | `specialite` | `rag_nexus_nsi_terminale_specialite` |
| Maths | `maths/troisieme.yml` | `troisieme` | `tronc_commun` | `rag_nexus_maths_troisieme_tc` |
| Maths | `maths/seconde_tronc_commun.yml` | `seconde` | `tronc_commun` | `rag_nexus_maths_seconde_tc` |
| Maths | `maths/premiere_tronc_commun.yml` | `premiere` | `tronc_commun` | `rag_nexus_maths_premiere_tc` |
| Maths | `maths/terminale_specialite.yml` | `terminale` | `specialite` | `rag_nexus_maths_terminale_specialite` |
| Français | `francais/troisieme.yml` | `troisieme` | `tronc_commun` | `rag_nexus_francais_troisieme_tc` |
| Français | `francais/premiere_eaf.yml` | `premiere` | `tronc_commun` | `rag_nexus_francais_premiere_eaf` |
| Histoire-Géo | `histoire_geo/troisieme.yml` | `troisieme` | `tronc_commun` | `rag_nexus_hg_troisieme_tc` |
| Histoire-Géo | `histoire_geo/seconde_tronc_commun.yml` | `seconde` | `tronc_commun` | `rag_nexus_hg_seconde_tc` |
| Histoire-Géo | `histoire_geo/premiere_tronc_commun.yml` | `premiere` | `tronc_commun` | `rag_nexus_hg_premiere_tc` |
| Histoire-Géo | `histoire_geo/terminale_tronc_commun.yml` | `terminale` | `tronc_commun` | `rag_nexus_hg_terminale_tc` |
| Physique-Chimie | `physique_chimie/premiere_specialite.yml` | `premiere` | `specialite` | `rag_nexus_pc_premiere_specialite` |
| SVT | `svt/premiere_specialite.yml` | `premiere` | `specialite` | `rag_nexus_svt_premiere_specialite` |
| SES | `ses/premiere_specialite.yml` | `premiere` | `specialite` | `rag_nexus_ses_premiere_specialite` |
| Philosophie | `philosophie/terminale_tronc_commun.yml` | `terminale` | `tronc_commun` | `rag_nexus_philo_terminale_tc` |
| SNT | `snt/seconde.yml` | `seconde` | `snt` | `rag_nexus_snt_seconde` |
| Grand Oral | `grand_oral/terminale.yml` | `terminale` | `examen` | `rag_nexus_grand_oral_terminale` |
| Examens | `exams/bac_general.yml` | `terminale` | `examen` | `rag_nexus_exams_bac_general` |
| Examens | `exams/anticipee_maths.yml` | `premiere` | `examen` | `rag_nexus_exams_anticipee_maths` |
| Candidats libres | `candidats_libres/parcours_terminale.yml` | `terminale` | `remediation` | `rag_nexus_candidats_libres_terminale` |
| Quarantaine | — | — | — | `rag_nexus_quarantine` |

**22 entrées** de catalogue. Seules celles peuplées seront instanciées.

### Encodage des statuts d'enseignement (N-03)

Valeurs issues de `nexus_contracts.document.StatutEnseignement` (`packages/contracts/src/nexus_contracts/document.py:34-49`) :

| Cas pédagogique | Valeur enum | Suffixe de collection |
|---|---|---|
| Tronc commun (collège, lycée) | `tronc_commun` | `_tc` |
| Enseignement commun | `enseignement_commun` | `_ec` |
| Spécialité / EDS | `specialite` ou `eds` | `_specialite` |
| Option (maths complémentaires) | `maths_complementaires` | `_maths_compl` |
| Option (maths expertes) | `maths_expertes` | `_maths_exp` |
| SNT | `snt` | `_snt` (matière = statut) |
| Enseignement scientifique | `enseignement_scientifique` | `_ens_sci` |
| EMC | `emc` | `_emc` |
| Examen (bac, Grand Oral) | `examen` | `_examen` ou nom spécifique |
| Remédiation (hors candidats libres) | `remediation` | `_remediation` (candidats libres : exception nommée, cf. table ci-dessous) |

### Exceptions à la convention de nommage (O-02)

La convention générale est `rag_nexus_{matiere}_{niveau}_{statut}`. Les collections suivantes y dérogent car leur nature ne s'encode pas en matière×niveau×statut :

| Collection | Dérogation | Justification |
|---|---|---|
| `rag_nexus_grand_oral_terminale` | Pas de statut suffixé | Grand Oral = transversal (pas disciplinaire). `matiere=grand_oral`, `niveau=terminale`. Le statut (`examen`) est implicite — suffixer `_examen` serait redondant. |
| `rag_nexus_exams_bac_general` | `exams` remplace matière | Les annales/sujets sont transversaux. `matiere=exams`, `niveau=terminale`. |
| `rag_nexus_exams_anticipee_maths` | `exams` remplace matière | Épreuve anticipée, `niveau=premiere`. |
| `rag_nexus_candidats_libres_terminale` | Pas de statut suffixé | Parcours transversal. `statut=remediation` implicite. |
| `rag_nexus_quarantine` | Ni matière, ni niveau, ni statut | Zone de quarantaine, hors arborescence disciplinaire. |

Toute collection **non listée** dans cette table suit la convention stricte `rag_nexus_{matiere}_{niveau}_{statut}`.

### Bilan contrat vs taxonomie (O-03)

**Enums de statut : suffisants.** Valeurs vérifiées dans `packages/contracts/src/nexus_contracts/document.py:34-49` :
- `maths_complementaires` : **présent** (ligne 40)
- `maths_expertes` : **présent** (ligne 41)
- `option` : **présent** (ligne 39) — couvre les options non nommées (DGEMC, arts, etc.)
- `snt` : **présent** (ligne 42)
- `examen` : **présent** (ligne 48)

**Taxonomie : incomplète.** Les fichiers `services/rag-pedago/taxonomy/` ne couvrent pas :
- Options hors maths (DGEMC, arts, langues rares, etc.)
- Maths complémentaires / maths expertes (pas de fichier dédié)
- Enseignement scientifique (enum `enseignement_scientifique` existe, pas de fichier taxonomie)
- EMC (enum `emc` existe, pas de fichier taxonomie)

**Tâche LOT 21** : compléter la taxonomie pour les options et enseignements manquants. Le contrat (`StatutEnseignement`) est prêt ; c'est la taxonomie qui doit rattraper.

### Règle de routage

Le routage est défini dans `rag_collections.yml` (mis à jour au LOT 21). Le `COLLECTION_MAP` hardcodé de la prod est remplacé par une lecture de la config YAML. Pas d'auto-création de collection (M-04).

---

## 12. Invariant : n'exposer que ce qui est peuplé et gouverné (M-04)

La taxonomie définit le **périmètre cible** (toutes les matières/niveaux/statuts). Mais une collection/rubrique n'est **exposée à l'UI** que si :
1. La collection cible est **peuplée** (≥ 1 chunk indexé).
2. Les chunks ont passé `quality → gate → review`.
3. Les métadonnées obligatoires sont complètes (`rights`, `source_uri`, `type_doc`).

**Pas de rubrique pointant une collection vide.** Le bug des rubriques cassées de la prod (L-02) est le contre-exemple exact de cet invariant.

**Pas d'auto-création de collection.** Le moteur cible lève une erreur si la collection demandée n'existe pas dans `rag_collections.yml`. Pas de `get_or_create_collection`.

---

## 13. Question de cadrage LOT 21 : interface RAG (M-03)

Le dépôt prévoit un **cockpit** (placeholder Next.js, `services/cockpit/`) comme future UI gouvernée. L'UI actuelle est un Streamlit legacy (`app_v2.py`).

**Question ouverte** (à trancher avec le lead au démarrage du LOT 21) :

| Option | Description | Conséquences |
|---|---|---|
| **Cockpit Next.js** | L'interface RAG est le cockpit, avec auth HMAC par profil, personas par niveau, gouvernance intégrée. | Refonte UI complète. Aligné sur l'architecture cible (ADR-0001). |
| **Évolution Streamlit** | L'UI Streamlit est adaptée : routing corrigé, auth HMAC, rubriques dynamiques. | Évolution incrémentale. Dévie de l'architecture cible (cockpit placeholder). |
| **Hybride transitoire** | Le cockpit pour les élèves, Streamlit pour l'admin/ingestion. | Deux UI à maintenir temporairement. |

**Pas de décision unilatérale.** Le choix est présenté au lead au LOT 21.

---

## 14. Gel du corpus et baseline (I-10)


1. **Gel** : suspendre l'ingestion avant cutover
2. **Snapshot** : backup ChromaDB frais + sauvegarde catalogue SQLite (I-11)
3. **Baseline** : D-11 re-capturée au plus près du cutover
4. **Cutover** : fenêtre de maintenance, corpus stable
5. **Dégel** : reprise ingestion vers le nouveau moteur

---

## 15. Préalables de bascule (Phase 4)

1. Backup frais ChromaDB
2. **Sauvegarde catalogue SQLite admin** (168 MiB, I-11)
3. `docker save` des images actuelles
4. **Vérification accès GDrive** (I-03, **bloquant**)
5. Gel du corpus (I-10)
6. Baseline D-11 re-capturée
7. Provisionnement pgvector dédié (A-1)

---

## 16. Plan de migration (si validé)

### Phase 1 — LOT 21

1. ADR définitif.
2. Supprimer déclarations Chroma de `rag_collections.yml`.
3. Table cible : `rag_chunks` (pas `rag_chunks_pilote`).
4. Compose pgvector dédié (A-1).

### Phase 2 — LOTs 22-25

5. Citations F-01.
6. Harnais évaluation (LOT 23).
7. Hybride + rerank (LOT 24).
8. Chunker unifié + benchmark débit e5 (LOT 25, I-04).

### Phase 3 — Lot dédié

9. Vérifier accès GDrive (I-03).
10. Extraire documents originaux depuis GDrive.
11. Décomposer `education` par matière (I-08).
12. Enrichir `rights` par provenance (A-4).
13. Quarantaine (A-5).
14. Re-chunker heading-aware.
15. Re-embedder e5-large.
16. Dédup NSI (I-07).
17. Admission `quality → gate → review`.
18. Indexer dans pgvector dédié, vers les collections fines §11.

### Phase 4 — Cutover (instruction lead)

19. Préalables §15.
20. Shadow traffic.
21. Canary progressif.
22. Surveillance 48h.
23. Décommissionner l'ancien.

---

## 17. Questions ouvertes

1. **Accès GDrive** : le folder source est-il accessible ? Credentials valides ? (**Bloquant** pour le re-chunking, I-03.)
2. **Fenêtre de bascule** : contraintes de calendrier (examens, périodes scolaires) ?
3. **Interface RAG** (M-03) : cockpit Next.js, évolution Streamlit, ou hybride transitoire ? À trancher au LOT 21.
