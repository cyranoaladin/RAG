# LOT 1.2 — le dépôt porte deux lignées de release, et les matrices amont ne sont pas l'amont

> Mesure préalable à l'étape 2 : qui produit les 486 placements, et depuis quelle entrée ?
> La réponse retire son objet à l'étape 1 telle qu'elle était spécifiée.

## Ce que la base déclare de sa propre provenance

```
rag_artifact_placements, 486 lignes
   source_scope ......... lycee/general/{svt,ses,hlp,hggsp,dgemc,nsi}
   authorization_id ..... prerentree-2026-2027-<collection>-v1   (11 distinctes)
   source_placement_id .. 486 empreintes distinctes
```

## L'amont réel, identifié par identité d'ensembles

```
profile_gate/catalog_delta.json
   placements ....................... 486
   source_placement_id distincts .... 486

confrontation à rag_artifact_placements
   déclarés absents de la base ......   0
   en base non déclarés .............   0
   ENSEMBLES IDENTIQUES .............  vrai
   source_placement_id identiques ...  vrai
```

**`catalog_delta.json` est l'amont des 486 placements.** L'identité porte sur les couples
`(collection, contenu)` **et** sur les identifiants de placement source, dans les deux sens.

## Les deux lignées

```
LIGNÉE DU 25 AOÛT
   final_production_profile_matrix_20260825.json          18 collections · 26 couples
   production_profile_accepted_placements_20260825.json   26 entrées
   verified_production_profiles_20260825.json             18 profils
        ↓  produce_release_scope_placement_from_git
   release_scope_placement_20260825.jsonl                 26 contenus · 18 profile_id
        ↓
   ffc1bae — release à 18 sujets
        ↓
   nexus-contracts — 18 artefacts de portée, source_sha256 = manifests de ffc1bae

LIGNÉE DU 29 AOÛT
   profile_gate/catalog_delta.json                        486 placements · 11 collections
   profile_gate/candidate_inventory.json                  11 collections
        ↓
   branche rag-pedago/release-chain-ingestion-319 — release à 11 sujets
        ↓
   rag_artifact_placements — 486 lignes, identiques au catalog_delta
   rag_chunks — 8 324 chunks, 319 artefacts
```

**Les deux lignées sont internes cohérentes et mutuellement étrangères.** Onze couples
seulement leur sont communs, sur 26 d'un côté et 486 de l'autre.

## Ce que cela corrige dans le plan

L'étape 1 du LOT 1.2 disait : *rectifier les matrices amont contre les populations
mesurées*. **Elle n'a pas d'objet pour cette livraison.** Les matrices du 25 août ne sont
pas l'amont des 486 placements ; elles sont l'amont d'une autre release, celle de
`ffc1bae`. Les rectifier reviendrait à écrire dans un artefact d'une lignée ce qu'on lit
dans l'aval de l'autre — la circularité que la manche 4 avait mise en garde.

**Ce qu'il faut à la place :** produire la release des onze depuis `catalog_delta.json` et
`candidate_inventory.json`, qui sont son amont réel et qui concordent déjà avec la base à
l'identité près. Le producteur `produce_release_scope_placement_from_git` lit les matrices
du 25 août : **il est le producteur de l'autre lignée**, et son refus
`UNACCEPTED_COLLECTION` disait exactement cela.

## Ce qui reste à trancher

- **Laquelle des deux lignées fait foi ?** La seconde décrit la base ; la première décrit le
  paquet `nexus-contracts` et l'image en service. Aucune ne décrit les deux.
- **La lignée du 25 août doit-elle être déclarée abandonnée ?** Elle porte les dix
  collections sans données et omet les trois peuplées.
- **Le producteur des 486** — quel outil lit `catalog_delta.json` et écrit les manifests de
  sujet ? Non identifié à cette date.

## Périmètre

Base servie `ragdb`, 2026-09-01. Comparaisons d'ensembles dans les deux sens, sur
l'intégralité des populations, jamais sur des cardinaux.
