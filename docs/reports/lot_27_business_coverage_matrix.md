# LOT 27 — Matrice de couverture metier

Source de verite : `services/rag-engine/configs/rag_collections.yml` (version 2, 35 collections).

## College — 3e

| Matiere | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Mathematiques | `rag_nexus_maths_troisieme_tc` | oui | non | non | Tronc commun |
| Francais | `rag_nexus_francais_troisieme_tc` | oui | non | non | Tronc commun |
| Histoire-Geographie | `rag_nexus_hg_troisieme_tc` | oui | non | non | Tronc commun |
| DNB | `rag_nexus_dnb` | oui | non | non | Examen transversal |
| Sciences (Physique-Chimie, SVT) | — | non | — | — | Hors perimetre v1 |

## Lycee — Seconde

| Matiere | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Mathematiques | `rag_nexus_maths_seconde_tc` | oui | non | non | Tronc commun |
| Francais | `rag_nexus_francais_seconde_tc` | oui | non | non | Tronc commun |
| Histoire-Geographie | `rag_nexus_hg_seconde_tc` | oui | non | non | Tronc commun |
| SNT | `rag_nexus_snt_seconde_tc` | oui | non | non | Tronc commun |
| Physique-Chimie | — | non | — | — | Hors perimetre v1 (pas de collection seconde PC) |
| SVT | — | non | — | — | Hors perimetre v1 (pas de collection seconde SVT) |
| SES | — | non | — | — | Hors perimetre v1 (pas de collection seconde SES) |

## Premiere generale

| Matiere / EDS | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Francais / EAF | `rag_nexus_francais_premiere_tc` | oui | non | non | Tronc commun, taxonomy EAF |
| Mathematiques specialite | `rag_nexus_maths_premiere_gen_specialite` | oui | non | non | |
| Mathematiques tronc commun | `rag_nexus_maths_premiere_gen_tc` | oui | non | non | Ens. scientifique sans spe maths |
| NSI specialite | `rag_nexus_nsi_premiere_specialite` | oui | **oui** | **oui** | 16 892 chunks (LOT 25a) |
| Physique-Chimie specialite | `rag_nexus_pc_premiere_specialite` | oui | non | non | |
| SVT specialite | `rag_nexus_svt_premiere_specialite` | oui | non | non | |
| SES specialite | `rag_nexus_ses_premiere_specialite` | oui | non | non | |
| Histoire-Geographie | `rag_nexus_hg_premiere_tc` | oui | non | non | Tronc commun |
| HGGSP | — | non | — | — | Hors perimetre v1 |
| Epreuves anticipees maths | `rag_nexus_exams_anticipee_maths` | oui | non | non | Examen |

## Premiere STMG

| Matiere | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Mathematiques STMG | `rag_nexus_maths_premiere_stmg_tc` | oui | non | non | Tronc commun |
| Droit-Economie specialite | `rag_nexus_droiteco_premiere_stmg_specialite` | oui | non | non | |

## Terminale generale

| Matiere / EDS | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Philosophie | `rag_nexus_philo_terminale_tc` | oui | non | non | Tronc commun |
| Mathematiques specialite | `rag_nexus_maths_terminale_gen_specialite` | oui | non | non | |
| Maths complementaires | `rag_nexus_maths_terminale_gen_option_comp` | oui | non | non | Option sans spe maths |
| Maths expertes | `rag_nexus_maths_terminale_gen_option_exp` | oui | non | non | Option avec spe maths |
| NSI specialite | `rag_nexus_nsi_terminale_specialite` | oui | **oui** | **oui** | |
| Physique-Chimie specialite | `rag_nexus_pc_terminale_specialite` | oui | non | non | |
| SVT specialite | `rag_nexus_svt_terminale_specialite` | oui | non | non | |
| SES specialite | `rag_nexus_ses_terminale_specialite` | oui | non | non | |
| Histoire-Geographie | `rag_nexus_hg_terminale_tc` | oui | non | non | Tronc commun |
| Grand Oral | `rag_nexus_grand_oral_terminale` | oui | non | non | Examen transversal gen+stmg |
| Bac general (annales) | `rag_nexus_exams_bac_general` | oui | non | non | Examen |

## Terminale STMG

| Matiere | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Mathematiques STMG | `rag_nexus_maths_terminale_stmg_tc` | oui | non | non | Tronc commun |
| Droit-Economie specialite | `rag_nexus_droiteco_terminale_stmg_specialite` | oui | non | non | |
| MSDGN specialite | `rag_nexus_msdgn_terminale_stmg_specialite` | oui | non | non | GF/mercatique/RHC/SIG en metadata |

## Transversal

| Element | Collection | Declaree | Instanciee | Retrievable | Notes |
|---|---|---|---|---|---|
| Grand Oral | `rag_nexus_grand_oral_terminale` | oui | non | non | |
| Candidats libres | `rag_nexus_candidats_libres_terminale` | oui | non | non | Remediation |
| Quarantaine | `rag_nexus_quarantine` | oui | **oui** | non | Isolement, non retrievable par design |
| DNB | `rag_nexus_dnb` | oui | non | non | Examen college |
| Bac general | `rag_nexus_exams_bac_general` | oui | non | non | |
| Epreuves anticipees maths | `rag_nexus_exams_anticipee_maths` | oui | non | non | |

## Synthese

| Indicateur | Valeur |
|---|---|
| Total collections declarees | 35 |
| Total instanciees | 3 |
| Total retrievable | 2 |
| Collections instanciees retrievable | `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite` |
| Collection instanciee non retrievable | `rag_nexus_quarantine` (par design) |

## Gaps metier

Seule la matiere **NSI** (Premiere + Terminale specialite generale) est actuellement
instanciee et interrogeable. Les 32 autres collections sont declarees dans le
catalogue taxonomique mais pas encore instanciees.

Matieres declarees non instanciees (par ordre de priorite potentielle) :
- Mathematiques (9 collections, 5 niveaux/voies)
- Francais (3 collections)
- Histoire-Geographie (4 collections)
- Physique-Chimie (2 collections)
- SVT (2 collections)
- SES (2 collections)
- Philosophie (1 collection)
- SNT (1 collection)
- STMG specialites (3 collections)
- Grand Oral (1 collection)
- Examens (3 collections : DNB, Bac general, Epreuves anticipees)
- Candidats libres (1 collection)

## Hors perimetre v1 (non declare)

- HGGSP
- Sciences college (PC/SVT 3e)
- PC/SVT/SES seconde
- Series technologiques hors STMG (ST2S, STI2D, STL, STD2A, STHR, S2TMD)

## Prochaine phase proposee

Instancier les collections par lot de matiere, en commencant par les matieres
a fort volume de candidats (Mathematiques, Francais) et les examens (DNB, Bac).
Chaque instanciation necessite un corpus ingere et valide (quality gate).
