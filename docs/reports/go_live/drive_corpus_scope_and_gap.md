# Périmètre cible RAG et écart réel, mesurés contre le Drive

Ce document interprète deux artefacts dérivés. Il n'énonce aucun total qui ne
s'y trouve pas :

- `drive_corpus_inventory.json` — recensement du corpus Drive confronté à la
  matrice de servabilité et à l'ensemble promu canonique ;
- `non_pdf_drive_reacquisition_audit.json` — vérification d'identité des
  contenus non-PDF.

## 1. Ce qui a changé

Le dépôt raisonnait sur les contenus de la matrice sans avoir jamais
regardé la source documentaire d'où ils viennent. La confrontation n'avait pas eu lieu. Elle a
eu lieu.

Le point aveugle n'était pas un trou de corpus : c'était un trou de preuve.

## 2. Le périmètre cible

Deux périmètres coexistent et ne doivent jamais être confondus.

**`FULL_DRIVE_PEDAGOGICAL_SCOPE`** — les quatre zones que le README du corpus
destine à l'ingestion (`01_EDUSCOL_OFFICIEL`, `02_NEXUS_DIAGNOSTICS`,
`03_RESSOURCES_INTERACTIVES`, `04_COMPLEMENTS_PEDAGOGIQUES`). C'est la cible
d'un « RAG à 100 % ».

**`CURRENT_PROMOTED_SCOPE`** — ce que la release promeut aujourd'hui. C'est un
sous-ensemble strict du précédent, entièrement contenu dans Éduscol.

Les zones `00_ADMIN` et `00_INDEX_PROVENANCE` servent à prouver, pas à
enseigner : le README les exclut explicitement de l'ingestion. Elles ne font
partie d'aucune cible.

## 3. Ce que la confrontation établit

La matrice de servabilité couvre l'intégralité du périmètre pédagogique du
Drive. Aucun contenu pédagogique du Drive ne lui est inconnu, et aucune de ses
lignes ne désigne un contenu absent du Drive. La seule ligne de matrice hors
zone pédagogique est le mode d'emploi du corpus lui-même, que la matrice refuse
par rôle — un refus correct, pas un oubli.

L'ensemble promu est lui aussi intégralement présent dans le Drive.

Autrement dit : **l'écart de périmètre est nul**. L'écart qui reste n'est pas
un écart de collecte, c'est un écart de qualification.

## 4. L'écart réel

L'écart entre le périmètre pédagogique et l'ensemble promu ne tient pas à des
documents manquants. Il tient à quatre causes de blocage, chacune sous une
autorité distincte, et aucune ne se règle par une ingestion :

- une revue PII humaine, qui n'appartient à aucun script ;
- une absence de preuve d'URL de provenance ;
- une non-indexabilité par rôle, qui est une décision et non un défaut ;
- une incompatibilité de programme prouvée.

Un point mérite d'être signalé plutôt que noyé dans un total : **une partie des
contenus déjà promus n'est pas candidate servable**, et la cause en est
uniquement la revue PII en attente. Ces contenus sont dans la release et
attendent une décision humaine. Le compte exact figure dans
`drive_corpus_inventory.json` sous `promoted.non_candidats_servables`.

## 5. Les contenus non-PDF

La raison bloquante affichée jusqu'ici — l'absence d'identifiant Drive — était
fausse, et à double titre. Le dépôt portait déjà un manifeste de réacquisition
complet, avec identifiant Drive, empreinte attendue et taille attendue pour
chaque contenu. Ce qui manquait n'était pas l'identifiant : c'était l'exécution
de la vérification.

Elle a été exécutée. Toutes les demandes du manifeste ont été réacquises et
confrontées à leur empreinte et à leur taille attendues, sans aucun écart. Le
verdict est porté par `non_pdf_drive_reacquisition_audit.json`.

**Cela ne clôt pas le bloqueur, et il ne faut pas le faire dire au rapport.**
Deux conditions restent ouvertes, pour des raisons différentes :

1. *La conservation durable.* Le compteur du gate mesure une copie retenue,
   pas une vérification réussie. Une vérification faite dans un répertoire
   éphémère ne retient rien. Choisir l'emplacement de conservation est une
   décision de gouvernance ; ce n'est pas au script de la prendre par effet de
   bord.

2. *La provenance.* Le catalogue de provenance du Drive couvre la totalité du
   corpus Éduscol avec une URL source, et **aucun** des contenus des autres
   zones. Les ressources interactives restent donc sans preuve d'URL. Leur nom
   de fichier contient des identifiants qui ressemblent à ceux d'une page
   institutionnelle, et c'est précisément le piège : une URL dérivée d'un slug
   aurait la forme d'une preuve sans en être une. L'importeur du dépôt refuse
   déjà explicitement cette dérivation, et ce document ne la propose pas.

Lever ce second point suppose une source de provenance que le Drive ne contient
pas — le catalogue technique du run de collecte, qui n'est pas dans le corpus
livré.

## 6. L'ingestion, désormais mesurée

Le plan de clôture déclarait trois niveaux « non mesurables depuis le dépôt » :
ingéré, exploitable par recherche, servi en production. C'était exact depuis le
dépôt seul. Ce n'était pas une raison de les laisser indéterminés : ils sont
mesurables dès qu'une base est nommée.

Une base de préparation a été nommée et mesurée, en lecture seule, par
`scripts/go_live/audit_ingestion_from_dsn.py`. Le résultat est porté par
`ingestion_audit.json`. Trois faits en ressortent, et ils ne disent pas la
même chose :

1. **Tous les PDF pédagogiques du Drive sont ingérés**, avec leur texte
   canonique. Aucun contenu ingéré n'est inconnu de la matrice. Les seuls
   contenus pédagogiques absents sont exactement les non-PDF — ce que le
   pipeline PDF ne traite pas.

2. **Rien n'est exploitable par recherche vectorielle.** La base ne porte aucun
   vecteur et l'extension n'y est pas installée. Le texte est stocké, pas
   indexé pour la recherche. C'est le point où la confusion serait la plus
   coûteuse : « tout est ingéré » se lit spontanément comme « le RAG
   fonctionne », et ici les deux sont séparés par une étape entière.

3. **Rien n'est prouvé sur la production.** Cette base n'est pas prouvée être
   celle de la production, et aucune mesure prise ici ne peut en témoigner. Le
   niveau « servi en production » n'est pas prononcé.

## 7. Ce que cela change pour la revue PII

La revue PII n'était pas bloquée par l'absence d'outillage : le dépôt porte
déjà l'index des paquets, le CLI de revue et le scellement des décisions. Ce
qui manquait était la matière locale, et elle ne se recalcule pas depuis les
PDF : l'exporteur d'entrée canonique **retrouve** le texte dans la base du run
et refuse toute divergence — un texte de revue qui n'est pas celui qui a été
scanné ne prouve rien de ce sur quoi on statue.

Cette base existe et porte le texte canonique de tous les documents ingérés.
La revue PII est donc réamorçable, ce qu'elle n'était pas tant que le Drive
seul était en cause. C'est une condition nécessaire, pas la décision : celle-ci
reste humaine, et une partie des contenus concernés est déjà dans la release.
