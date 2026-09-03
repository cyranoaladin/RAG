# LOT 1.2 — Release normalisée et partition dérivée des pages PDF

**Statut :** actif. Contrat des pages validé le 31 août 2026 ; Option A de
gouvernance retenue le même jour.

## But et borne

Produire une release non activée représentant exactement 320 contenus,
320 artefacts globaux, 488 placements et 11 collections, avec un seul jeu de
chunks par contenu et une partition exhaustive des pages physiques.

Ce checkpoint local ne vaut ni ingestion, ni déploiement, ni GO LIVE. La base
servie reste à 319 contenus / 486 placements pendant ce lot.

## Propriété canonique

```text
1 contenu = 1 artifact_id = content_sha256
          = 1 définition globale d'artefact
          = 1 jeu global de chunks
          = N placements
```

La collection, le profil, le niveau et le programme sont des faits du
placement. Aucun sujet ne possède l'artefact. Aucun ordre lexical ou premier
placement ne désigne de propriétaire. Option B — répétition puis fusion de
définitions — est rejetée.

## Représentation physique V2

La plus petite évolution qui permet aussi de valider un sujet sans dépendre de
son propre parent est un registre global dans un fichier frère :

```text
release-registry.json
  └─ expected_manifest_sha256
     └─ production-profile-gate.release.json
        ├─ release_kind = MULTILEVEL_AGGREGATE_RELEASE_V2
        ├─ artifact_registry {path, sha256} ─┐
        └─ subjects[]
           ├─ path
           └─ sha256 ──────────────┼────────┐
                                   └─ subjects/<collection>.release.json
                                      ├─ release_kind = MULTILEVEL_SUBJECT_RELEASE_V2
                                      ├─ artifact_registry {path, sha256}
                                      └─ placements[]  # références artifact_id
                                             │
        artifacts.release.json ◄─────────────┘
          ├─ release_kind = MULTILEVEL_ARTIFACT_REGISTRY_V2
          └─ artifacts[]           # définitions globales uniques
```

Le fichier frère évite une dépendance sémantique parent→enfant→parent : chaque
sujet nomme directement le registre qu'il utilise, et l'agrégat nomme les deux
types de feuilles. Aucun sujet ne peut substituer un autre registre.

Le DAG de scellement est acyclique :

- `artifacts.release.json` est une feuille scellée par son SHA ;
- chaque sujet V2 référence ce chemin et ce SHA, puis son propre SHA est porté
  dans l'entrée `subjects` de l'agrégat ;
- l'agrégat référence aussi directement le chemin et le SHA du registre ;
- le SHA de l'agrégat est déclaré par `release-registry.json` ;
- tous les documents contribuent aussi à l'identité du répertoire de release.

Une mutation d'un placement casse donc le SHA du sujet ; une mutation d'un
artefact casse le SHA du registre, puis les références du sujet et de
l'agrégat. Une mutation rescellée mais sémantiquement fausse est refusée par le
lecteur.

## Discriminateurs et compatibilité

Les anciens documents restent :

```text
MULTILEVEL_AGGREGATE_RELEASE_V1
MULTILEVEL_SUBJECT_RELEASE_V1
```

Ils conservent leur sens historique : définitions d'artefacts dans les sujets,
et refus des définitions dupliquées entre sujets.

La nouvelle représentation utilise explicitement :

```text
MULTILEVEL_AGGREGATE_RELEASE_V2
MULTILEVEL_SUBJECT_RELEASE_V2
MULTILEVEL_ARTIFACT_REGISTRY_V2
```

Le lecteur branche sur `release_kind`, jamais sur l'absence opportuniste d'un
champ. `release-registry.json` reste structurellement V1 mais autorise
explicitement le nouveau `release_kind`; sa propre structure ne change pas.

## Contrat du registre d'artefacts V2

`artifacts.release.json` contient exactement une définition par
`artifact_id`. Une
définition porte seulement des faits intrinsèques :

- `artifact_id` et `content_sha256`, égaux ;
- source, titre et type documentaire ;
- `page_count` ;
- `ignored_empty_pages` ;
- chunks et leurs identités/pages ;
- digests historiques des sets de chunks et de couverture.

Elle ne porte ni placement, ni collection, ni profil.

Ses compteurs sont non ambigus :

```text
expected_counts.unique_artifacts
expected_counts.unique_chunks
```

Pour la production visée : 320 et la valeur de chunks mesurée.

L'agrégat V2 porte `artifact_registry {path, sha256}`, les sujets scellés et
les compteurs globaux :

```text
expected_counts.unique_artifacts
expected_counts.placements
expected_counts.unique_chunks
expected_counts.subjects
```

Pour la production visée : 320, 488, valeur mesurée, 11.

## Contrat d'un sujet V2

Un sujet conserve ses autorités, modèles, profil, collection, année et version
de programme. Il porte la même référence exacte
`artifact_registry {path, sha256}` et `placements`; chaque placement contient
`artifact_id` plus les faits de placement existants. Il ne porte ni chunks ni
faits intrinsèques de document.

Ses compteurs sont :

```text
expected_counts.unique_artifact_references
expected_counts.placements
```

Ils doivent être égaux. `(collection, artifact_id)` est unique dans le sujet.
Le même `artifact_id` peut être référencé par plusieurs sujets.

## Invariants globaux V2

- `artifact_id == content_sha256` ;
- chaque artefact est défini exactement une fois ;
- chaque `(artifact_id, chunk_index)` et chaque `chunk_id` est unique ;
- chaque chunk appartient à exactement un artefact global ;
- aucun sujet ne définit de chunk ;
- chaque placement référence un artefact existant ;
- chaque artefact est référencé par au moins un placement ;
- chaque placement appartient au sujet qui le contient ;
- aucune paire `(collection, artifact_id)` n'est dupliquée ;
- les compteurs déclarés égalent les populations mesurées.

D-31 continue donc de refuser toute double définition. Il accepte plusieurs
références vers l'unique définition.

## Autorité unique des pages vides

Les deux services exécutent aujourd'hui deux copies du prédicat structurel.
Cette duplication est retirée : un petit foyer technique neutre, hors des deux
services et hors du contrat de retrieval, porte la traversée pypdf et le verdict
canonique. PII et extracteur l'appellent tous deux. Le producteur compare leurs
résultats et refuse toute divergence.

Une page sans texte n'est ignorable que si le prédicat prouve que son flux,
y compris les `/Form` effectivement invoqués, ne porte ni image, ni opérateur
de texte, ni tracé ambigu. Une image, une lecture impossible ou un contenu non
prouvé vide reste un refus.

Le producteur dérive `ignored_empty_pages` de cette extraction ; il ne la
calcule jamais comme complément des chunks.

## Partition des pages

Pour chaque artefact PDF global :

```text
expected_pages = {1, ..., page_count}
chunk_covered_pages = pages couvertes par au moins un chunk
ignored_empty_pages = pages classées structurellement vides par l'autorité
```

Invariants bloquants :

```text
chunk_covered_pages ∩ ignored_empty_pages = ∅
chunk_covered_pages ∪ ignored_empty_pages = expected_pages
```

`ignored_empty_pages` est toujours émis, même `[]`, avec des entiers stricts
(jamais `bool`), bornés, uniques et strictement croissants. Un document
entièrement vide reste non substantiel et non servable.

`page_coverage_digest` conserve son sens historique : uniquement les pages
couvertes par des chunks. Aucun digest décoratif n'est ajouté.

## Citations

L'extracteur conserve une entrée par page physique. Le chunker saute une page
vide sans la retirer de la liste et numérote par position physique. Pour chaque
page ignorée de la production, un chunk antérieur et le premier chunk suivant,
quand ils existent, sont comparés aux numéros réels du PDF.

## Lecture et réconciliation

`load_release_expectation` accepte V1 et V2 par branches explicites. Pour V2,
il assemble en mémoire les définitions globales et les placements référents,
sans inventer de faits absents. Les consommateurs d'éligibilité lisent les
faits de profil depuis le sujet/placement, pas depuis l'artefact.

La comparaison DB globale attend 320 artefacts et 488 placements. La
comparaison par collection sélectionne les artefacts via les placements de la
collection ; elle ne réintroduit pas de propriété `artifact.collection`.
L'ancienne vérification de la colonne dénormalisée `chunk.collection` reste
applicable à V1 seulement.

Avant ingestion, la base 319/486 doit rester rouge. Son delta read-only exact
est le seul contenu `8848f073…`, ses deux placements NSI et ses chunks.

## Non-régression et arrêt

Les 319 artefacts, leurs chunks et les 486 placements historiques doivent être
identiques sous leur représentation canonique. `3bc5ff23…` reste exclu. Tout
autre delta, tout compte différent de 320/488/11, toute preuve historique à
réécrire ou toute action de production arrête le lot.

Une production réussie n'active rien et ne commence pas l'étape 3.
