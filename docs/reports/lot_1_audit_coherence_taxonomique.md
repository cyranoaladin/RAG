# LOT 1.4 — Audit de cohérence taxonomique

> Tableau brut. La divergence est le diagnostic, pas un défaut de présentation.
> Toutes les valeurs sont mesurées le 2026-08-31 contre la base servie et l'arbre de
> travail. Aucune n'est reprise d'un rapport antérieur.

## Le tableau

| axe | déclaré | peuplé | servi |
|---|---:|---:|---:|
| collections | 62 déclarées · **11 instanciées** | **11** | **11** |
| notions | **452** identifiants distincts | **0** | **0** |
| sous-notions | 171 | 0 | 0 |
| niveaux | 5 | **2** | 2 |
| matières | 24 identifiants | **6** | 6 |
| voies | — | 1 (`generale`) | 1 |

## Orphelins, dans les deux sens

```
notions déclarées SANS aucun chunk ............... 452 / 452   (100 %)
chunks citant une notion INEXISTANTE ..............   0
collections peuplées NON déclarées ................   0
collections déclarées instanciées et vides ........   0
```

**Les 452 notions de la taxonomie ne sont rattachées à aucun chunk.** Mesuré directement :

```sql
SELECT count(*) FILTER (WHERE notions = '{}') FROM rag_chunks;   →  8324 / 8324
SELECT count(*) FILTER (WHERE array_length(notions,1) >= 1) ...  →     0
```

La colonne existe, elle n'est jamais nulle, et elle est **vide sur chaque ligne**. Toute
métrique de couverture par notion vaut donc `0/452` ; toute métrique qui annoncerait autre
chose mesurerait autre chose.

## L'axe qui tient : les collections

```
62 déclarées dans rag_collections.yml
11 portent instanciee: true
11 sont peuplées en base
11 sont dans le domaine `education`, dont retrievable: true

les 11 instanciées SONT exactement les 11 peuplées — aucune dans un sens, aucune dans l'autre
```

C'est le seul axe des quatre où déclaré, peuplé et servi coïncident.

## Les axes qui ne tiennent pas

### Niveaux — trois sur cinq n'existent pas en base

```
taxonomie   troisieme(7 fiches)  quatrieme(2)  seconde(10)  premiere(18)  terminale(23)
base        premiere 5 745 chunks · terminale 2 579 chunks
            troisieme, quatrieme, seconde : ZÉRO
```

Le collège entier et la seconde sont déclarés et vides.

### Matières — dix-huit sur vingt-quatre n'existent pas en base

```
base   dgemc 368 · hggsp 2 590 · hlp 2 043 · nsi 913 · ses 1 039 · svt 1 371
```

Absentes de la base bien que déclarées : `mathematiques`/`maths`, `francais`,
`physique_chimie`/`pc`, `philosophie`, `histoire_geo`, `langues`, `llce`, `emc`, `eps`,
`es`, `snt`, `techno`, `msdgn`, `droit_economie`, `grand_oral`, `orientation`.

### Et la taxonomie se contredit elle-même sur l'identifiant de matière

```
maths (9 fiches)          ET  mathematiques (3 fiches)
pc (2)                    ET  physique_chimie (2)
es (2)                    ET  ses (3)
histoire_geo (4)          ET  hggsp (2)
```

Vingt-quatre identifiants pour un nombre de matières réelles inférieur. Aucune des quatre
paires n'est réconciliée par un alias déclaré ; ce sont quatre matières nommées deux fois.

## Le constat qui gouverne le go-live

```
visibility en base   internal : 8 324 / 8 324     public : 0

_ROLE_VISIBILITIES (retrieval_scope_v2.py:106)
   student       ('public',)                                        →      0 chunk
   teacher       ('public','internal')                              →  8 324
   reviewer      ('public','internal','restricted')                 →  8 324
   ingest_agent  ('internal','restricted')                          →  8 324
   admin         ('public','internal','restricted','private')       →  8 324
```

**Un élève atteint zéro chunk sur 8 324.** Mesuré par exécution de
`allowed_visibilities_for_role` du dépôt, puis comptage en base — pas par lecture de la
table de correspondance. L'instrument discrimine : le même comptage rend 8 324 pour
`teacher`.

La plateforme, en l'état, ne sert rien à un élève.

## Un chiffre sans source

Le chiffre de **743 notions** circule dans les échanges de gouvernance. Il n'apparaît nulle
part dans le dépôt en lien avec la taxonomie. Trois valeurs coexistent :

```
743   origine introuvable
523   ce que `validate_taxonomy.py` imprime — des OCCURRENCES (une notion comptée
      autant de fois qu'elle apparaît de fiches)
452   identifiants de notion DISTINCTS
```

Aucune des trois n'est fausse en soi ; elles ne comptent pas la même chose, et rien ne dit
laquelle la gouvernance emploie.

## Périmètre de cette mesure

- 60 fichiers de taxonomie retenus ; `common/`, `exams/`, `proposals/` exclus comme le fait
  `validate_taxonomy.py`.
- Base servie `ragdb`, table `rag_chunks`, 8 324 lignes, le 2026-08-31.
- Aucun échantillon : chaque chiffre porte sur l'intégralité de sa population.
