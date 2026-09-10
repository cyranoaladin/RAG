# NEXUS-OPEN-PR-CONVERGENCE-V1

Mesure de chaque PR ouverte contre `main` en `342e710`, puis classification.
Aucune fermeture par intuition : chaque classe est justifiée par une mesure.

## Mesure

| PR | ahead | behind | commits uniques | fichiers PR | fichiers uniques | déjà dans `main` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 168 | 1 | 10 | 1 | 1 | 1 | 0 |
| 167 | 2 | 10 | 2 | 1 | 1 | 0 |
| 151 | 8 | 19 | 8 | 16 | 16 | 0 |
| 140 | 60 | 29 | 60 | 343 | 338 | 5 |
| 139 | 5 | 29 | 5 | 5 | 5 | 0 |
| 138 | 28 | 29 | 28 | 78 | 77 | 1 |
| 135 | 1 | 31 | 1 | 1 | 1 | 0 |
| 134 | 16 | 31 | 16 | 27 | 27 | 0 |
| 132 | 4 | 32 | 4 | 10 | 10 | 0 |
| 98 | 2 | 65 | 2 | 5 | 5 | 0 |

```text
OPEN_PRS=10
FULLY_SUPERSEDED_BY_CONTENT=0
```

Aucune PR n'est vidée par les dix fusions. Le backlog ne se ferme pas mécaniquement.

## Le fait décisif : quatre numéros d'ADR entrent en collision

`#140` et `#138` portent des ADR dont les numéros sont **déjà pris sur `main`, par des
décisions sans rapport** :

| Numéro | Sur `main` | Sur #140 / #138 |
| --- | --- | --- |
| ADR-0048 | émetteur canonique de scopes retrieval | périmètre go-live collège/lycée/STMG |
| ADR-0049 | contrat type de taxonomie servable | activation de 7 collections lycée |
| ADR-0050 | identité canonique de release après revue PII | extension contractuelle sixième/cinquième |
| ADR-0051 | servabilité face à une compatibilité programme inconnue | base pgvector canonique et nom de projet compose |

Fusionner l'une ou l'autre telle quelle donnerait quatre numéros d'ADR portant chacun deux
décisions différentes. Ce n'est pas un conflit de texte que `git` signalerait : les fichiers ont
des noms différents, la fusion serait **propre**, et la collision ne se verrait qu'après coup.

## Le registre de numérotation existe déjà — sur #139

`#139` porte précisément le mécanisme qui manque à `main` : `docs/adr/RESERVATIONS.md`, le
contrôle `scripts/check-adr-numbering.sh`, son épreuve, et son câblage dans `ci-local.sh`. Le
texte du registre dit lui-même, à propos de la réutilisation d'un numéro : « C'est arrivé. »

Il l'est encore aujourd'hui sur `main` :

```text
ADR_FILES=51   ADR_DISTINCT_NUMBERS=50
ADR_0046_USED_TWICE=yes   (foyer-unique-predicat-page-pdf, manifeste-corpus-servable-nexus)
ADR_0043_MISSING_ON_MAIN=yes   (fichier vivant sur une branche non fusionnée)
```

## Conséquence immédiate : le prochain numéro libre n'est pas celui qu'on croit

Un `ls docs/adr/` sur `main` suggère `ADR-0052`. C'est faux :

```text
ADR-0052  revendiqué par #138 et #140  (rescellement de release)
ADR-0053  réservé par le registre de #139  (autorité eduscol_catalogue_par_scope)
ADR-0054  revendiqué par #139  (posture opérationnelle)
FIRST_FREE_ADR=ADR-0055
```

Toute nouvelle ADR de ce chantier prend donc **ADR-0055**, pas ADR-0052.

## Classification

| PR | classe | motif mesuré |
| ---: | --- | --- |
| 167 | `ACTIVE_GO_LIVE` | ferme le gate 2 ; 1 fichier d'épreuve d'intégration, `+25/-4` contre `main` ; session H2-C externe |
| 168 | `ACTIVE_GO_LIVE` | ferme le gate 3 ; 1 fichier d'épreuve d'intégration, `+3/-3` contre `main` ; session H2-C externe |
| 139 | `PORT_THEN_CLOSE` | porte le registre et le contrôle de numérotation ADR, qui corrigent un défaut présent sur `main` |
| 151 | `PORT_THEN_CLOSE` | 2 modules runtime uniques plus leur producteur ; à porter dans le front actualité canonique |
| 132 | `PORT_THEN_CLOSE` | répétition de déploiement Docker et rollback ; à auditer puis porter le mécanisme utile |
| 140 | `PORT_THEN_CLOSE` | 338 fichiers uniques dont du runtime cockpit ; **mais** 4 collisions d'ADR : jamais telle quelle |
| 138 | `INVALID_UNDER_CURRENT_GOVERNANCE_CLOSE` | rescellement en place, sémantique interdite par ADR-0050 ; 3 collisions d'ADR ; base non-`main` |
| 134 | `INVALID_UNDER_CURRENT_GOVERNANCE_CLOSE` | 18 autorisations V1 dans un répertoire **absent de `main`** ; concurrencerait AuthorizationSetV2 |
| 98 | `INVALID_UNDER_CURRENT_GOVERNANCE_CLOSE` | 1 autorisation V1, même répertoire, même motif |
| 135 | `FULLY_SUPERSEDED_CLOSE` | 1 rapport de baseline go-live du 25/08, supersédé par le rapport pilote courant |

```text
GOVERNANCE_AUTHORIZATIONS_DIR_ON_MAIN=0 fichiers
```

C'est ce chiffre qui décide du sort de #134 et #98 : le répertoire `governance/authorizations/`
n'existe pas sur `main`. Ces PR ne mettraient pas à jour une autorité, elles en **créeraient** une
en V1, au moment précis où la cible est V2. Leur contenu reste consultable dans l'historique des
branches ; il ne doit pas devenir une autorité active.

## Ce que cette mesure ne décide pas

La classification `PORT_THEN_CLOSE` ne dit pas *quoi* porter. Chaque port exige son propre lot,
ses épreuves, et sa revue. Aucune PR n'est fermée par ce document : il établit sur quelle base
elle pourra l'être.
