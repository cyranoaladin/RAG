# Lot — Matrice de profils production proposés pour le set authority-required (2026-08-22)

## 1. Périmètre et méthode

Construction d'une matrice de profils **proposés**, jamais devinés, pour
les 72 contenus réels authority-required (digest confirmé
`3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0`,
reproduit indépendamment une troisième fois post-merge PR#127). Aucun
fichier `CollectionProfile` n'est créé par ce lot — c'est une proposition
soumise à décision opérateur/produit avant toute création réelle.
Méthode : réutilisation du mapping par contenu déjà produit et mergé dans
`docs/reports/tier_a_scope_profile_audit_clean_20260822.json` (PR#127),
spot-vérifié à nouveau contre les données brutes EDUSCOL, plus lecture
complète des 3 profils existants
(`philosophie_terminale_tc_h2c_v1.yml`,
`staging/francais_troisieme_tc_wave0_v1.yml`,
`staging/maths_troisieme_tc_wave0_v1.yml`) comme seul précédent réel pour
les dimensions assignées par profil plutôt qu'intrinsèques au contenu.

## 2. Partitions (par couple niveau/matière réel)

**Écart de méthode signalé, non résolu** : le partitionnement strict par
tuple (niveau, matière) donne 23 partitions ; éclater les couples
multi-matière ambigus en matières individuelles en donnerait 28 ; le
nombre `DISTINCT_LEVEL_SUBJECT_PAIRS=22` déjà publié dans l'audit PR#127
ne correspond à aucune des deux méthodes appliquées ici — la méthode
exacte utilisée pour produire 22 n'est pas reconstituable depuis l'artefact
seul. Signalé tel quel, pas forcé.

| Partition (niveau / matière) | Nb contenus | Exemple |
|---|---|---|
| multi-niveaux / PHYSIQUE_CHIMIE | 29 | `.../LYCEE/TRANSVERSAL.../PHYSIQUE_CHIMIE/...` |
| non-classe / FRANCAIS+HLP | 12 | `.../TRANSVERSAL.../FRANCAIS_HLP/...` |
| non-classe / PHILOSOPHIE | 5 | `.../PHILOSOPHIE/01_PROGRAMMES_OFFICIELS/...03f268dc1f.pdf` |
| non-classe / EPS | 3 | |
| non-classe / DANSE | 3 | |
| multi-niveaux / SES | 2 | |
| multi-niveaux / SVT | 2 | |
| seconde / MATHEMATIQUES | 1 | |
| terminale / NSI | 1 | |
| multi-niveaux / SCIENCES_INGENIEUR | 1 | |
| multi-niveaux / bundle arts (6 matières) | 1 | multi-matière ambigu |
| multi-niveaux / bundle arts variant (+cirque) | 1 | multi-matière ambigu |
| premiere / MATHEMATIQUES | 1 | |
| multi-niveaux / DANSE | 1 | |
| 4e / FRANCAIS | 1 | |
| premiere / NSI | 1 | |
| multi-niveaux / MATHEMATIQUES | 1 | |
| seconde / FRANCAIS+HLP | 1 | multi-matière ambigu |
| multi-niveaux / EPS | 1 | |
| seconde / FRANCAIS | 1 | |
| 4e / MATHEMATIQUES | 1 | |
| non-classe / DGEMC | 1 | |
| terminale / MATHEMATIQUES | 1 | |

Total : 23 partitions, 72 contenus. Les 3 partitions multi-matière
ambiguës correspondent au `MATIERE_AMBIGUOUS_COUNT=15` (en nombre de
contenus concernés) déjà publié — conservées séparées, jamais forcées
dans une matière unique.

## 3. Grille de gouvernance par dimension (motif commun aux 23 partitions)

| Dimension | Valeur proposée | Source de vérité | Ancrée |
|---|---|---|---|
| `matiere` | par partition ci-dessus | placement pédagogique EDUSCOL réel | vrai (partitions mono-matière) ; **faux** pour les 3 partitions multi-matière ambiguës — conflit réel, pas une valeur |
| `niveau` | par partition ci-dessus | placement EDUSCOL réel | vrai pour seconde/premiere/terminale/4e (15/72) ; **faux** pour `multi-niveaux`/`non-classe` (57/72 — aucun profil existant n'a jamais utilisé ces valeurs, la convention tenant `{population}_{niveau}` d'AGENTS.md n'a pas de forme définie pour un niveau non spécifique) |
| `school_year` | `2026-2027` | répertoire de release `configs/prerentree_2026_2027/` | vrai, 72/72 |
| `voie` | `generale` (lycée) / `college` (4e) | précédent direct (les 3 profils existants) | vrai seulement où `niveau` est concret (15/72) |
| `tenant` | motif `libre_{niveau}` | convention AGENTS.md + 3/3 profils existants | vrai seulement où `niveau` est concret — **aucune forme définie pour `multi-niveaux`/`non-classe`, la plus grande décision ouverte, touche 57/72 contenus** |
| `collection` | motif `rag_nexus_{matiere}_{niveau}_tc` | motif des 3 profils existants | même conditionnalité que `tenant` |
| `candidat` | `libre` | précédent 3/3, jamais écrit comme règle explicite | vrai par précédent, marqué comme inféré |
| `audience` | `[libre, tous]` | précédent 3/3 | vrai par précédent, marqué comme inféré |
| `visibility` | `internal` | précédent 3/3 | vrai par précédent, marqué comme inféré |
| `programme_version` | — | **aucun registre programme/BOEN n'existe dans le dépôt** ; les 3 profils existants codent chacun une référence BOEN spécifique, aucune ne s'applique à ces 23 partitions | **faux pour les 72 contenus, sans exception** — décision bloquante universelle, hors périmètre de ce lot |

## 4. Conflit signalé, non résolu

Les 5 contenus `non-classe/PHILOSOPHIE` entrent en conflit direct avec
l'unique profil de production existant, qui déclare `niveau: terminale`
pour la Philosophie — la donnée EDUSCOL elle-même ne grade-tague jamais la
Philosophie, donc le `terminale` du profil existant était lui-même un
jugement humain, pas dérivé des données EDUSCOL non plus. Réutiliser le
profil existant exigerait de décider que le contenu `non-classe` entre
dans le périmètre d'un profil scopé `terminale` ; créer un profil séparé
`non-classe` est l'alternative. Non tranché ici.

## 5. Totaux et décisions ouvertes

```
TOTAL_PARTITIONS=23
PARTITIONS_FULLY_GROUNDED=0   # chaque partition échoue au moins sur programme_version
PARTITIONS_WITH_PROFILE_DECISION_REQUIRED=23
```

Décisions nécessitant un arbitrage opérateur/produit, par priorité :

1. Nommage `tenant`/`collection`/`voie` pour `niveau=multi-niveaux` ou
   `niveau=non-classe` (57/72 contenus, la grande majorité) — aucun
   précédent n'existe.
2. Philosophie `niveau` : `non-classe` (EDUSCOL) vs `terminale` (profil
   existant) — laquelle gouverne.
3. `programme_version` par partition — nécessite une recherche réelle de
   référence BOEN, aucun précédent dans le dépôt pour aucune des 23
   partitions.
4. Traitement des 3 partitions multi-matière ambiguës (bundles arts à 6
   matières, seconde FRANCAIS+HLP) — un profil par bundle, ou éclatement
   par matière au préalable (nécessiterait de re-dériver un placement
   mono-matière, non disponible dans les données source actuelles).

## 6. Booléens finaux

```
PROFILE_INVENTORY_GAP=true
PROFILE_MATRIX_PROPOSED=true
PROFILE_DECISION_REQUIRED=true (4 décisions listées ci-dessus)
NO_PROFILE_CREATED_BY_THIS_LOT=true
NO_GUESSED_VALUE_COMMITTED=true
```
