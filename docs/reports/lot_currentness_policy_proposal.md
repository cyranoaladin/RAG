# Politique d'actualité — proposition, projections, et ce qui bloque réellement

## 1. La campagne est scellée

```
CURRENTNESS_CAMPAIGN_RUN_ID=422356d3f7f51f93ea9a8dbff7c37fac13586334bb32e3f30eb4297ab3c5a139
CURRENTNESS_CAMPAIGN_MANIFEST_SHA256=8bb11c521618dbf78b852dd8f2e96e8eeed047332669c2c2f435df461bf14d75
CURRENTNESS_OBSERVATION_LEDGER_SHA256=15bf725d8d8c0c26930f175fd2c7d06fc86cf1ac4b91bd0e9cf7d27a2627fc48
CURRENTNESS_RELATION_LEDGER_SHA256=b223fe3de23267a9a6c8d9bf4dcc36097ce775f87681ea2a49b9fecb6edc1fe7
CURRENTNESS_POLICY_INPUT_SHA256=b0e735d4592d38ce14f982454dd61133508ab07e3cc0118371fa37ed4eb4c1f7
CURRENTNESS_CAMPAIGN_FROZEN=true

NETWORK_CURRENTNESS_CAMPAIGN=PASS
NETWORK_CURRENTNESS_VERIFICATION=INCONCLUSIVE
```

Aucune requête ne sera rejouée : 110 refus sont une preuve durable de
l'incapacité du canal à trancher, pas un incident à retenter.

## 2. Le rôle des URL, requalifié

Ma première sortie annonçait `NAVIGATION_URLS=111`. C'était faux, et pour une
raison instructive : je lisais le `Content-Type` des réponses **403** — celui
de la page de refus — et j'en concluais le rôle de la ressource.

```
CONFIRMED_NAVIGATION_URLS=1
CONFIRMED_DIRECT_RESOURCE_URLS=0
ROLE_UNOBSERVABLE=110
                                somme = 111
CATALOGUE_SEMANTIC_ROLE=NAVIGATION   (sémantique documentaire, pas observation)
```

Requalification faite sur les observations **déjà collectées** : aucune requête
supplémentaire. Et l'absence de `.pdf` dans une URL ne prouve rien — une route
sans extension peut parfaitement servir un PDF.

## 3. Statuts de source, projetés par relation

```
SOURCE_RELATIONS_TOTAL=2542         CONTENTS_TOTAL=2451

CONTENT_WITH_ANY_ACTUEL=170
CONTENT_WITH_ONLY_A_VERIFIER=2158
CONTENT_WITH_ARCHIVE_AND_NON_ARCHIVE=9
CONTENT_WITH_ONLY_ARCHIVE=31
CONTENT_WITH_TRANSITION_ONLY=77
```

Partition exhaustive des combinaisons, qui somme à 2451 :

```
2158  a-verifier                              164  actuel
  77  transition-ou-actuel                     31  archive
   6  a-verifier+transition-ou-actuel           6  a-verifier+archive
   5  a-verifier+actuel                         2  archive+transition-ou-actuel
   1  a-verifier+archive+transition-ou-actuel   1  actuel+transition-ou-actuel
```

Aucune priorité arbitraire : le statut reste porté par la relation.

## 4. Version de programme — le vrai blocage

```
PROGRAM_COMPATIBLE=0    PROGRAM_INCOMPATIBLE=0    PROGRAM_UNKNOWN=2451

PROGRAMME_VERSION_AUTHORITY_SCOPES=18
CONTENTS_IN_SCOPE_WITH_GOVERNED_PROGRAMME_VERSION=123
CONTENTS_IN_SCOPE_WITHOUT_GOVERNED_PROGRAMME_VERSION=2328
```

Une autorité versionnée **existe** : 18 profils d'ingestion déclarent
`programme_version` et `school_year: 2026-2027` (`BOEN_special_1_2019-01-22`,
`BOEN_14_2026-04-02_MENE2602917A`, …). Mais elle est indexée par
`(niveau, matiere)` et ne couvre que 123 contenus.

Surtout : **le catalogue ne porte aucune colonne de version de programme.** Sa
colonne `annee` est l'année de publication du document, pas le programme qu'il
sert — un document de 2016 peut mettre en œuvre un programme encore en vigueur,
et un document de 2026 en servir un abrogé. En déduire la compatibilité serait
une inférence de la même nature que déduire une URL d'un slug.

## 5. `NEXUS-RAG-CURRENTNESS-POLICY-V1` — proposée

```
CURRENTNESS_POLICY_PROPOSED=true      CURRENTNESS_POLICY_APPLIED=false
```

Cinq dimensions tenues séparées : `PROVENANCE`, `SOURCE_STATUS`,
`NETWORK_CURRENTNESS`, `PROGRAM_VERSION`, `SERVABILITY`. Les fondre ferait d'un
`200` une preuve d'actualité pédagogique et d'un `403` une preuve
d'obsolescence.

La disposition de repli est `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`, et la
politique déclare explicitement qu'elle **n'est jamais équivalente** à
`VERIFIED_CURRENT`. Une épreuve le vérifie : le repli autorise éventuellement à
servir, il ne falsifie pas le niveau de preuve.

Traductions proposées : `archive → ARCHIVE / servable=false` (le repli réseau
ne ressuscite pas une archive) ; `actuel → CURRENT_DECLARED_BY_CATALOGUE` (une
déclaration institutionnelle, pas une vérification réseau) ;
`transition-ou-actuel → TRANSITION_OR_CURRENT` (la source n'a pas tranché) ;
`a-verifier → NEEDS_SECONDARY_EVIDENCE` avec quatre preuves secondaires
ordonnées.

**12 épreuves sur fixtures**, aucun contenu réel. Elles couvrent la matrice
demandée et vérifient que chacune des neuf conditions du repli est réellement
bloquante — sans quoi la liste serait décorative.

## 6. Impact projeté — et ce qu'il révèle

```
CONTENTS_PROJECTED=2451
REVIEW_REQUIRED_PROGRAM_UNKNOWN=2411
BLOCKED_ARCHIVE_ONLY=31
MIXED_ARCHIVE_RELATION_LEVEL_DECISION=9
```

**Aucun contenu n'atteint la disposition de repli aujourd'hui**, et pas parce
que la politique serait sévère : parce que `PROGRAM_VERSION_COMPATIBLE` est
faux pour les 2451. Ce n'est pas la politique qui bloque, c'est une **autorité
manquante**.

Une autorité `(niveau, matiere, annee|type_document) → programme_version` ferait
passer les contenus compatibles de `REVIEW_REQUIRED` à `CANDIDATE` **sans
changer une ligne de la politique**. C'est le levier le plus rentable du
programme : il décide du sort de 2411 contenus.

Sans elle, l'alternative est une revue humaine sur 2411 contenus — dont 2158
`a-verifier` seuls.

## 7. Comptabilité

```
FULL_URL_ACCOUNTING_COMPLETE=true      (2530 objets, tous une disposition explicite)
FULL_URL_PROVENANCE_COMPLETE=false     (79 sans provenance URL)
FULL_CURRENTNESS_COMPLETE=false        (politique non adoptée, réseau inconcluant)
```

Les 79 passent de `UNACCOUNTED` à
`NO_URL_EVIDENCE_IN_EXAMINED_AUTHORITIES` : comptablement fermés, pas
vérifiés.

## 8. Autorité d'adoption de la politique — identifiée, et absente

La politique se déclare elle-même non appliquée et subordonnée à une décision
d'architecture :

```
policy_id: NEXUS-RAG-CURRENTNESS-POLICY-V1
status: PROPOSED
applied: false
requires_adr: true
```

Restait à nommer **quelle** décision. La recherche a été menée sur les deux
surfaces où elle pourrait exister :

```
ADRS_ON_MAIN_CITING_THE_POLICY=0
ADRS_IN_THIS_LOT_CITING_THE_POLICY=0
HIGHEST_ADR_ON_MAIN=ADR-0050
CURRENTNESS_POLICY_ADOPTION_AUTHORITY=ABSENT
```

Aucune ADR n'adopte cette politique, ni sur `main`, ni dans ce lot. L'autorité
d'adoption n'est donc pas introuvable : elle n'existe pas encore. Elle doit
prendre la forme d'une ADR distincte, portée par une PR distincte, devenant
Acceptée par une review humaine `APPROVED` du Code Owner selon ADR-0025.

Cette ADR ne peut pas être écrite dans ce lot, et ce n'est pas une commodité de
séquencement. Ce lot **mesure** ; adopter une politique de servabilité est un
acte de gouvernance. Les confondre reviendrait à laisser une mesure s'auto-
autoriser, ce qui est exactement le défaut que la politique elle-même interdit
en refusant qu'un `200` devienne une preuve d'actualité pédagogique.

Conséquence pour le go-live : la dimension actualité reste sans autorité
appliquée, et `FULL_CURRENTNESS_COMPLETE=false` n'est pas un défaut de ce lot
mais l'état exact de la gouvernance. Aucun contenu n'est déclaré servable au
titre de l'actualité.

### Chaîne d'autorité, telle qu'elle se présente

| Autorité | Portée | État |
| --- | --- | --- |
| `programme_version` déclarée | servabilité au regard du programme | ADR proposée, non fusionnée |
| `program_authorities_v1` | liaison périmètre → programme en vigueur | proposition, hors ADR |
| `NEXUS-RAG-CURRENTNESS-POLICY-V1` | servabilité au regard de l'actualité | proposition, **sans ADR** |

Les trois sont proposées, aucune n'est appliquée. Le go-live ne peut donc pas
s'appuyer sur l'actualité comme critère de servabilité.
