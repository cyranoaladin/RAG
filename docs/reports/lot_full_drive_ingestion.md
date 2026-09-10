# LOT — Ingestion complète du Drive gouverné

## Ce que ce lot prouve

L'intégralité de la racine Drive gouvernée a été énumérée, acquise, rehachée
et présentée au staging du plan de contrôle. Aucun lot n'a été sauté, aucun
compteur n'est approximatif : chaque objet non ingéré est nommé par son
`drive_file_id` dans `lot_full_drive_ingestion_dispositions.json`.

```
DRIVE_DISCOVERED                 2580
DRIVE_ELIGIBLE_PDF               2473
DRIVE_FETCHED                    2473
DRIVE_DISTINCT_ARTIFACTS         2473
DRIVE_DUPLICATE_BY_CONTENT          0
DRIVE_INGESTED                   1478
DRIVE_UNCLASSIFIABLE_BY_SOURCE    993
DRIVE_ERRORS                        2
DRIVE_UNACCOUNTED                   0
```

`1478 + 993 + 2 = 2473`. L'accounting ferme.

Manifeste scellé de la campagne :
`b14bad4bf358e0d86838d7daddc49d32bd61d9b9a5175649040afb9164d3eaf5`
(2473 objets, 1 732 360 626 octets).

État de la base de staging après la passe : **1478 artefacts, 1478
provenances, 14 541 chunks**, dont **0 artefact sans chunk** et **1478 en
`needs_review`** — aucun n'est servable, comme l'exige la tranche.

## Une acquisition, pas une série de lots

Le premier essai découpait la campagne en lots partageant une destination.
`require_scoped_reconciled` a refusé dès le deuxième lot : il voyait dans
l'arbre des fichiers hors du périmètre demandé et concluait, correctement,
que « la source a changé sous l'acquisition ». **Le garde avait raison ;
c'est l'orchestration qui était fausse.** Une campagne est UNE acquisition,
avec UN manifeste et UN recoupement exact. Le découpage ne subsiste que là
où il a un sens — classification, extraction, staging — pour qu'une erreur
soit imputée à SON objet.

## Reprise sans re-téléchargement, et sans baisser la preuve

Le staging est tombé une première fois sur un défaut d'orchestration (une
DSN passée là où `PostgresStagingStore` attend une connexion ouverte). Plutôt
que de re-télécharger 1,7 Go pour corriger une faute qui ne touchait pas les
octets, la reprise lit l'arbre déjà acquis — ce que la tranche exige de toute
façon : « le découpage lit les octets écrits par l'acquisition, pas ceux
téléchargés ».

La reprise ne se croit pas sur parole : elle **recalcule** le manifeste scellé
sur l'arbre et le confronte à l'empreinte publiée par l'acquisition. Identité
vérifiée avant toute écriture. Un octet déplacé et la reprise s'arrête.

## Idempotence

Une passe complète rejouée sur le même instantané rend :

```
new_artifacts        0      duplicate_artifacts     1478
new_provenances      0      duplicate_provenances   1478
new_chunks           0      duplicate_chunks       14541
```

C'est exactement ce que la tranche exige : « un second passage sur le même
instantané Drive doit rendre `new_artifacts == 0` et `new_chunks == 0` : c'est
la seule preuve qu'une réexécution ne dédouble pas le corpus ». La base est
inchangée (1478 artefacts, 14 541 chunks, 0 sans chunk).

Les compteurs suivent la **transaction**, pas la tentative. Une première
version les incrémentait dans le bloc protégé : un artefact annulé par le point
de reprise était compté « nouveau » alors qu'il n'avait rien écrit, et le
rapport contredisait la base qu'il prétendait décrire.

Un artefact entre entier ou pas du tout : chaque artefact est écrit dans un
point de reprise. Sans lui, un échec au découpage laissait derrière lui sa
ligne d'artefact et ses provenances — en aval, un document sans chunks, ou
pire avec un jeu partiel, se serait lu comme ingéré. Les deux artefacts en
échec ont été retirés de la base ; la passe suivante a confirmé qu'ils n'y
réécrivent rien.

## ESCALADE — trois écarts de modélisation hors périmètre de ce lot

993 PDF ne sont pas ingérés parce que `classify_from_hints` refuse leur
chemin. **Le garde n'est pas en cause et n'a pas été modifié.** Mais son
refus recouvre trois causes distinctes, dont deux sont des écarts de
*vocabulaire* et non des ambiguïtés réelles. Conformément à AGENTS.md
(« si un lot exige de toucher une logique métier hors de son périmètre :
s'arrêter et le signaler »), rien n'est implémenté ici.

### A. Un statut empilé sur une nature — 938 objets

`_NATURE` est une regex ouverte (`\d{2}_[A-Z0-9_]+`) sans vocabulaire fermé.
Elle capture donc indifféremment deux familles de dossiers que la source
numérote pourtant séparément :

| famille | préfixes | libellés |
|---|---|---|
| type de document | `01`–`09` | `PROGRAMMES_OFFICIELS`, `REPERES_ATTENDUS`, `RESSOURCES_ACCOMPAGNEMENT`, `EVALUATIONS_EXAMENS`, `ANNALES_SUJETS_CORRIGES`, `GUIDES`, `DIAPORAMAS_SUPPORTS`, `PROGRAMMES_LIMITATIFS`, `AUTRES` |
| statut d'actualité | `10`, `20`, `80`, `90`, `99` | `ACTUEL_CONFIRME`, `TRANSITION_OU_ACTUEL`, `A_VERIFIER`, `ARCHIVE_CATALOGUE`, `CONFLITS_STATUTS` |

Sur les 27 combinaisons observées, **aucune** ne empile deux statuts ni deux
types : toutes croisent exactement un statut et un type. Chaque libellé porte
un et un seul préfixe. La distinction est donc **déjà encodée par la source** ;
c'est le modèle qui replie deux dimensions orthogonales en une seule.

La docstring du garde nomme explicitement ce cas (« typiquement un bucket
`80_A_VERIFIER` empilé sur une nature réelle ») et choisit le refus. Ce choix
reste défendable pour `80_A_VERIFIER` : la source dit qu'elle ne sait pas.
Il l'est beaucoup moins pour `10_ACTUEL_CONFIRME`, où la source affirme au
contraire que le document est à jour.

Répartition : `A_VERIFIER` 805, `ACTUEL_CONFIRME` 64, `TRANSITION_OU_ACTUEL`
49, `ARCHIVE_CATALOGUE` 19, `CONFLITS_STATUTS` 1.

**825 seraient écartés par la gouvernance de toute façon** (à vérifier,
archive, conflit). **113 sont des documents que la source déclare courants**
et que seul le repliement écarte.

### B. Un niveau abrégé hors vocabulaire — 44 objets

`KNOWN_NIVEAUX` déclare `TROISIEME`, `QUATRIEME`, `CINQUIEME` ; le Drive écrit
aussi `3E`, `4E`, `5E`. Non reconnue, l'abréviation retombe dans les segments
libres et entre en collision avec la vraie matière :

```
01_EDUSCOL_OFFICIEL/COLLEGE/3E/HISTOIRE_GEOGRAPHIE/03_RESSOURCES_ACCOMPAGNEMENT/2017/...
                            ^^                ^^^^^^^^^^^^^^^^^^
                            deux « matières » → refus
```

Ce n'est pas une ambiguïté : c'est une orthographe que le vocabulaire ignore.

### C. Un vocabulaire réellement inconnu — 11 objets

`STMG,COMMUN` (8), `DEPP,TESTS_POSITIONNEMENT` (1),
`PHILOSOPHIE_IA,FICTION_PEDAGOGIQUE` (1), `DEPP,MATHEMATIQUES,TESTS_POSITIONNEMENT`
(1). Séries et producteurs que la taxonomie ne modélise pas. Ici le refus est
pleinement justifié tant qu'une décision de gouvernance n'a pas tranché.

## Les 2 erreurs, nommées

| `drive_file_id` | cause |
|---|---|
| `1CKDQfoMVUZEjHg6_bp7PrIapNSx1km1P` | le texte extrait porte des octets NUL (0x00), que PostgreSQL refuse en colonne `text` |
| `1mVZbFLk7und5Sq9KpEfNhfp7YshQe6s1` | l'artefact ne rend **aucun** texte — refus de `CorpusAcquisitionError` : « le stager vide passerait pour un document ingéré alors qu'il n'enseigne rien » |

Le second est un garde qui fonctionne : un PDF image-seul n'enseigne rien à
un moteur de recherche textuel. Le premier est un défaut d'extraction réel.

## Portée de l'écart

Si les trois écarts étaient résolus, **169 documents supplémentaires**
deviendraient ingérables (113 + 44 + 11 + 1). Les 826 restants seraient
écartés par la gouvernance elle-même, et non par un défaut de modèle.

Le détail objet par objet — `drive_file_id`, `artifact_id`, chemin, cause,
statut source, servabilité si résolu — est dans
`lot_full_drive_ingestion_dispositions.json` (995 entrées, `DISPOSITION_REQUIRED`).
