# LOT 27 — Business UI & Catalogue Alignment Audit

## Phase

LOT_27_BUSINESS_UI_AND_CATALOGUE_ALIGNMENT

## A. Source metier attendue

### rag_collections.yml (38 collections declarees)

| Niveau | Matiere | Voie | Statut | Instanciee |
|--------|---------|------|--------|------------|
| troisieme | maths | null | tronc_commun | false |
| troisieme | francais | null | tronc_commun | false |
| troisieme | histoire_geo | null | tronc_commun | false |
| troisieme | dnb | null | examen | false |
| seconde | maths | null | tronc_commun | false |
| seconde | francais | null | tronc_commun | false |
| seconde | histoire_geo | null | tronc_commun | false |
| seconde | snt | null | tronc_commun | false |
| premiere | nsi | gen | specialite | **true** |
| premiere | maths | gen | specialite | false |
| premiere | maths | gen | tronc_commun | false |
| premiere | maths | stmg | tronc_commun | false |
| premiere | francais | gen | tronc_commun | false |
| premiere | histoire_geo | gen | tronc_commun | false |
| premiere | physique_chimie | gen | specialite | false |
| premiere | svt | gen | specialite | false |
| premiere | ses | gen | specialite | false |
| premiere | droit_economie | stmg | specialite | false |
| terminale | nsi | gen | specialite | **true** |
| terminale | maths | gen | specialite | false |
| terminale | maths | gen | option (comp) | false |
| terminale | maths | gen | option (exp) | false |
| terminale | maths | stmg | tronc_commun | false |
| terminale | histoire_geo | gen | tronc_commun | false |
| terminale | physique_chimie | gen | specialite | false |
| terminale | svt | gen | specialite | false |
| terminale | ses | gen | specialite | false |
| terminale | philosophie | gen | tronc_commun | false |
| terminale | droit_economie | stmg | specialite | false |
| terminale | msdgn | stmg | specialite | false |
| terminale | grand_oral | null | examen | false |
| terminale | exams (bac general) | gen | examen | false |
| premiere | exams (anticipee maths) | null | examen | false |
| terminale | candidats_libres | null | remediation | false |
| null | quarantine | null | null | **true** |

### Taxonomy files existants (26 fichiers)

- nsi: premiere_specialite, terminale
- maths: troisieme, seconde_tronc_commun, premiere_gen_specialite (missing), premiere_tronc_commun, terminale_specialite
- francais: troisieme, premiere_eaf
- histoire_geo: troisieme, seconde_tronc_commun, premiere_tronc_commun, terminale_tronc_commun
- physique_chimie: premiere_specialite
- svt: premiere_specialite
- ses: premiere_specialite
- snt: seconde
- philosophie: terminale_tronc_commun
- grand_oral: terminale
- exams: bac_general, anticipee_maths
- candidats_libres: parcours_terminale
- stmg: droiteco_premiere, droiteco_terminale, msdgn_terminale (referenced but not all exist)

### Taxonomy files declares mais absents

Collections in rag_collections.yml referencing taxonomy_file not found in services/rag-pedago/taxonomy/:
- maths/premiere_gen_specialite.yml
- maths/terminale_gen_specialite.yml (only terminale_specialite.yml exists)
- maths/premiere_stmg_tc.yml
- maths/terminale_gen_option_comp.yml
- maths/terminale_gen_option_exp.yml
- maths/terminale_stmg_tc.yml
- francais/seconde_tc.yml
- physique_chimie/terminale_specialite.yml
- svt/terminale_specialite.yml
- ses/terminale_specialite.yml
- stmg/droiteco_premiere.yml
- stmg/droiteco_terminale.yml
- stmg/msdgn_terminale.yml
- exams/dnb.yml

## B. Etat reel UI (app_v2.py)

### Pages sidebar
1. Dashboard — `/collections/v2` (v2)
2. Education — legacy collections (rag_francais_premiere, rag_maths_premiere, rag_education)
3. Maths 1ere — legacy `/stats/rag_maths_premiere`
4. Web3 & Blockchain — legacy `/stats/rag_web3`
5. Divers — legacy `/stats/rag_divers`
6. Recherche — `/collections/v2` + `/search/v2` (v2)
7. Administration — `/collections/v2` (v2)

### Collections legacy encore utilisees
- `rag_francais_premiere` (Education page, selector)
- `rag_maths_premiere` (Maths page, stats, ingestion)
- `rag_education` (Education page, fallback)
- `rag_web3` (Web3 page, stats)
- `rag_divers` (Divers page, stats)

### Endpoints legacy encore appeles
- `GET /stats/rag_maths_premiere` (Maths page)
- `GET /stats/rag_web3` (Web3 page)
- `GET /stats/rag_divers` (Divers page)
- `GET /stats/{collection_education}` (Education page)

### Pages v2 correctes
- Dashboard: utilise `/collections/v2`
- Recherche: utilise `/collections/v2` + `/search/v2`
- Administration: utilise `/collections/v2`

## C. Ecarts detectes

| # | Zone | Ecart | Niveau | Decision |
|---|------|-------|--------|----------|
| 1 | Sidebar | Pages "Maths 1ere", "Web3", "Divers" sont legacy | P1 | Supprimer, remplacer par navigation scolaire |
| 2 | Education | Collection cible = legacy (rag_francais_premiere etc) | P1 | Deriver du catalogue v2 |
| 3 | Education | `/stats/` legacy encore appele | P2 | Supprimer appels /stats |
| 4 | Maths 1ere | Page entiere basee sur legacy Chroma | P1 | Supprimer, integrer dans ingestion v2 |
| 5 | Web3 | Page hors perimetre scolaire Nexus | P1 | Supprimer de la navigation principale |
| 6 | Divers | Pointe vers rag_divers au lieu de quarantine v2 | P2 | Supprimer, quarantine via Admin |
| 7 | Dashboard | Trop pauvre: n'affiche que les 2-3 collections instanciees | P1 | Afficher catalogue complet avec filtres |
| 8 | Administration | N'affiche que les collections instanciees/retrievable | P1 | Afficher catalogue complet + coherence |
| 9 | Ingestion | Upload/URL/Drive ciblent collections legacy | P1 | Deriver du catalogue v2 instanciees |
| 10 | Taxonomie UI | EDUCATION_TAXONOMY codee en dur, pas alignee avec taxonomy_file | P2 | A terme, deriver de taxonomy_file |
| 11 | ALL_COLLECTIONS | Liste legacy hardcodee | P2 | Supprimer, deriver du catalogue |
| 12 | WEB3_CATEGORIES | Categories Web3 hardcodees | P2 | Supprimer si hors perimetre |
| 13 | Backend | Pas d'endpoint `/catalogue/v2` complet | P1 | Ajouter endpoint read-only |
| 14 | Recherche | OK, deja v2 | - | Rien a changer |
| 15 | Ingestion v2 | Endpoint `/ingest/v2/*` existe mais UI ne l'utilise pas | P1 | UI doit utiliser `/ingest/v2/*` |

## Resume des priorites

- **P1** (8 ecarts) : UI ne represente pas l'architecture RAG v2
- **P2** (5 ecarts) : composants legacy visibles, dettes techniques
- **P0** : aucun (prod pas cassee)
- **P3** : aucun identifie a ce stade
