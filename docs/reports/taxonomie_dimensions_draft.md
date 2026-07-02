# Taxonomie des dimensions du referentiel scolaire -- Draft

> Document de recherche (FE-05a). Ne pas merger. Source : `docs/referentiel_scolaire_3e_terminale.md`

---

## Dimension 1 : NIVEAU

| Valeur | Slug | Description dans le referentiel |
|---|---|---|
| Troisieme (cycle 4) | `3e` | Derniere annee de college, 26 h de tronc commun unique, pas de specialite. Diplome : DNB (reforme 2026 : 60/40, moyenne >= 10/20). |
| Seconde generale et technologique | `2de` | Classe de determination commune. Tronc commun ~26-28 h, options facultatives (1 generale + 1 techno). Pas de diplome ; choix d'orientation vers voie generale (3 EDS) ou serie technologique. |
| Premiere | `1re` | Cycle terminal an 1. 3 EDS en voie generale (3x4 h) ; 3 EDS obligatoires communs en STMG. Epreuves anticipees : francais (coef 10), maths anticipees [S2027] (coef 2). |
| Terminale | `tle` | Cycle terminal an 2. 2 EDS en voie generale (2x6 h) ; 2 EDS en STMG. Epreuves finales : philosophie, Grand oral, 2 specialites. |

**Point de vigilance** : un eleve de terminale 2025-2026 releve de [S2026], un eleve de premiere 2025-2026 releve de [S2027]. Le niveau seul ne suffit pas a determiner le regime d'examen ; il faut aussi la session.

---

## Dimension 2 : VOIE

| Valeur | Slug | Differences cles vs. l'autre voie |
|---|---|---|
| Generale | `gen` | 13 EDS au choix (3 en 1re, 2 en Tle). Philosophie coef 8. Grand oral coef 10 [S2026] / 8 [S2027]. Enseignement scientifique en TC (2 h + 1h30 maths si pas de spe maths). Options maths complementaires / maths expertes en Tle. ECE pratique en PC/SVT. Pratique en NSI/SI. |
| Technologique STMG | `stmg` | EDS fixes en 1re (sciences de gestion et numerique, management, droit et economie). En Tle : droit et economie (coef 16) + MSDGN (coef 16) avec choix d'enseignement specifique parmi 4 (gestion-finance, mercatique, RH-communication, SIG). Philosophie coef 4. Grand oral coef 14 [S2026] / 12 [S2027]. Maths en tronc commun (3 h, coef 6 CC). ETLV (1 h). |
| (Non applicable / college) | `college` | En 3e, pas de notion de voie. Tronc commun unique. DNB serie generale (la serie professionnelle est mentionnee mais hors perimetre detaille). |

**Point de vigilance** : les autres series technologiques (ST2S, STI2D, STL, STD2A, STHR, S2TMD) sont mentionnees au passage mais non detaillees dans le referentiel. Seule STMG est couverte.

---

## Dimension 3 : TYPE D'ENSEIGNEMENT

### 3a. Tronc commun (TC)

| Matiere TC | Niveaux concernes | Notes |
|---|---|---|
| Francais | 3e, 2de, 1re (gen+stmg) | En 1re : epreuve anticipee (coef 10). |
| Mathematiques | 3e, 2de | En 2de : 4 h. Disparait du TC en voie gen en 1re (remplace par maths dans ens. scientifique si pas de spe). Reste en TC en STMG (3 h, 1re+Tle). |
| Mathematiques (ens. scientifique) | 1re gen (sans spe maths) | 1 h 30 integree a l'enseignement scientifique. Sujet maths anticipees [S2027] specifique. |
| Histoire-geographie | 3e, 2de, 1re, Tle (gen+stmg) | Volumes differents gen vs stmg (3 h vs 1h30). |
| LVA | 3e, 2de, 1re, Tle | -- |
| LVB | 3e, 2de, 1re, Tle | -- |
| Enseignement scientifique | 1re gen, Tle gen | 2 h (+ 1h30 maths si pas spe maths en 1re). |
| Physique-chimie | 3e, 2de | Disparait du TC au lycee gen (devient EDS). |
| SVT | 3e, 2de | Idem. |
| Technologie | 3e | College uniquement. |
| SES | 2de | Decouverte. Devient EDS en voie gen. |
| SNT | 2de | Sciences numeriques et technologie. |
| EPS | 3e, 2de, 1re, Tle | CCF en Tle (coef 6). |
| EMC | 3e, 2de, 1re, Tle | 18 h/an. Coef 2 CC. |
| Philosophie | Tle (gen+stmg) | Remplace francais. Coef 8 gen / 4 stmg. |
| Arts plastiques, Education musicale | 3e | College. |

### 3b. Enseignements de specialite (EDS) -- voie generale (13)

| # | Intitule | Slug propose | Volumes | Epreuve terminale |
|---|---|---|---|---|
| 1 | Arts (7 sous-options) | `arts` | 4 h (1re) / 6 h (Tle) | ecrite 3h30 + orale 30 min |
| 2 | Biologie-ecologie | `bioeco` | idem | ecrite 3h30 + pratique 1h30 |
| 3 | EPPCS | `eppcs` | idem | ecrite 3h30 + pratique 30 min |
| 4 | HGGSP | `hggsp` | idem | ecrite 4h |
| 5 | HLP | `hlp` | idem | ecrite 4h |
| 6 | LLCER | `llcer` | idem | ecrite 3h30 + orale 20 min |
| 7 | LLCA | `llca` | idem | ecrite 4h |
| 8 | Mathematiques | `maths` | idem | ecrite 4h |
| 9 | NSI | `nsi` | idem | ecrite 3h30 + pratique 1h (coef 16 = 12 ecrit + 8 pratique) |
| 10 | Physique-chimie | `pc` | idem | ecrite 3h30 + ECE 1h (16 pts ecrit + 4 pts pratique) |
| 11 | SVT | `svt` | idem | ecrite 3h30 + ECE 1h (idem PC) |
| 12 | Sciences de l'ingenieur | `si` | idem (+2h sciences physiques en Tle) | ecrite 3h30 + pratique 1h |
| 13 | SES | `ses` | idem | ecrite 4h |

### 3c. Enseignements de specialite -- STMG

| Intitule | Niveau | Slug |
|---|---|---|
| Sciences de gestion et numerique | 1re | `sgn` |
| Management | 1re | `management` |
| Droit et economie | 1re + Tle | `droiteco` |
| MSDGN (tronc) | Tle | `msdgn` |
| -- Gestion et finance (enseignement specifique) | Tle | `msdgn_gf` |
| -- Mercatique | Tle | `msdgn_mercatique` |
| -- RH et communication | Tle | `msdgn_rhc` |
| -- SIG | Tle | `msdgn_sig` |

### 3d. Enseignements optionnels

| Option | Niveaux | Notes |
|---|---|---|
| LVC | 2de, 1re, Tle | Option generale. |
| LCA Latin | 2de, 1re, Tle | Cumulable avec autre option. |
| LCA Grec | 2de, 1re, Tle | Cumulable. |
| Arts (arts plastiques, cinema-AV, danse, hist. arts, musique, theatre) | 2de, 1re, Tle | Option generale. |
| EPS | 2de, 1re, Tle | Option generale. |
| Mathematiques complementaires | Tle gen | Pour eleves SANS spe maths. 3 h. |
| Mathematiques expertes | Tle gen | Pour eleves AVEC spe maths. 3 h. |
| DGEMC | Tle gen | Uniquement en terminale. |
| Management et gestion | 2de | Option technologique, porte vers STMG. |
| Sante et social | 2de | Option technologique. |
| Biotechnologies | 2de | Option technologique. |
| Sciences de l'ingenieur (decouverte) | 2de | Option technologique. |
| Creation et innovation technologiques | 2de | Option technologique. |
| Hippologie et equitation | 1re, Tle | Lycees agricoles. |
| Langue des signes francaise | 1re, Tle (stmg) | -- |
| Chant choral | 3e | Facultatif college. |

Coef. options : **+2 par option par an** (max +4 sur le cycle pour une option suivie 2 ans). S'ajoute au total de 100.

### 3e. Cas ou la meme matiere change de nature selon le niveau/choix

| Matiere | Nature selon le contexte |
|---|---|
| **Mathematiques** | TC en 3e et 2de ; TC-integre a ens. scientifique en 1re gen (sans spe) ; **EDS** en 1re/Tle gen (avec spe) ; **option** en Tle gen (maths complementaires ou maths expertes) ; **TC** en STMG (1re+Tle). Epreuve anticipee [S2027] avec 3 sujets distincts. |
| **Physique-chimie** | TC en 3e et 2de ; **EDS** en 1re/Tle gen. |
| **SVT** | TC en 3e et 2de ; **EDS** en 1re/Tle gen. |
| **SES** | TC (decouverte) en 2de ; **EDS** en 1re/Tle gen. |
| **Arts** | TC en 3e (ens. artistiques) ; **option** au lycee ; **EDS** au lycee gen. |
| **EPS** | TC a tous niveaux ; **option** au lycee ; **EDS** (EPPCS) au lycee gen. |
| **LCA (latin/grec)** | Option facultative en 3e et lycee ; **EDS** (LLCA) au lycee gen. |

---

## Dimension 4 : TYPE DE RESSOURCE / DISPOSITIF (transversal)

| Valeur | Slug | Description |
|---|---|---|
| Cours / programme | `cours` | Contenu d'enseignement, programme officiel, fiches de cours. |
| Annales / sujets d'examen | `annales` | Sujets et corriges d'epreuves ecrites (bac, DNB). |
| Grand oral | `grand_oral` | Preparation, methodologie, exemples de questions, grille d'evaluation. |
| Epreuve pratique ECE (PC/SVT) | `ece` | Banque nationale de situations experimentales, grilles, consignes. |
| Epreuve pratique NSI | `pratique_nsi` | Exercices de programmation, evaluation en dialogue avec examinateur. |
| Epreuve pratique SI | `pratique_si` | Composante pratique sciences de l'ingenieur. |
| Epreuve anticipee francais | `eaf` | Sujets ecrit + oral, listes d'oeuvres, descriptifs. |
| Epreuve anticipee maths [S2027] | `eam` | Sujets (3 versions : gen+spe, gen-spe, techno), automatismes. |
| DNB | `dnb` | Sujets et corriges du brevet (francais, maths, sciences, HG-EMC, oral). |
| Candidats individuels | `indiv` | Modalites specifiques (evaluations ponctuelles, dispenses ECE, choix A/B). |
| Orientation / parcours | `orientation` | Accompagnement choix EDS, orientation post-bac. |
| Oral de rattrapage (2d groupe) | `rattrapage` | Modalites, 2 matieres au choix, 20 min. |
| Projet STMG / etude approfondie | `projet_stmg` | Projet conduit en Tle STMG (soutenance, composante pratique MSDGN). |

---

## Dimension 5 : TEMPORALITE REGLEMENTAIRE (session)

| Marqueur | Slug | Eleves concernes | Differences cles |
|---|---|---|---|
| `[S2026]` | `s2026` | Terminale 2025-2026 | Pas d'epreuve anticipee maths. Grand oral coef 10 (gen) / 14 (stmg). DNB reforme 2026 (60/40). |
| `[S2027]` | `s2027` | Premiere 2025-2026 (et au-dela) | Epreuve anticipee maths coef 2 (3 sujets). Grand oral coef 8 (gen) / 12 (stmg). Dispensation redoublants session 2026. |
| (stable) | `stable` | Les deux sessions | Tous les coefficients non marques (francais anticipe coef 10, specialites coef 16, philosophie, CC). |

**Differences concretes entre sessions :**

| Element | S2026 | S2027 |
|---|---|---|
| Epreuve anticipee maths | inexistante | coef 2 (1re gen et techno) |
| Grand oral (gen) | coef 10 | coef 8 |
| Grand oral (stmg) | coef 14 | coef 12 |
| Total obligatoire | 100 | 100 (reequilibre) |
| Oral rattrapage maths anticipees | n/a | possible (sauf cumul avec spe maths) |
