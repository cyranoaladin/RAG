# LOT — `REAL_MULTILEVEL_INGESTION=PASS`

- **Branche** : `glr/multilevel-preflight`
- **Amont** : émetteur canonique de scopes ([`lot_multilevel_scope_successors.md`](lot_multilevel_scope_successors.md), ADR-0048)
- **Banc** : `services/rag-engine/tests/integration/test_multilevel_real_ingestion.py`

## Résultat

```
REAL_MULTILEVEL_INGESTION=PASS

SUBJECTS=10
SUBJECTS_WITH_EXACT_SCOPE=10
EXPECTED_ARTIFACTS=11
EXPECTED_CHUNKS=353
missing_chunks=0
unexpected_chunks=0
scope_binding_errors=0

RETRIEVABLE_COLLECTIONS_EXPECTED=10
RETRIEVABLE_COLLECTIONS_OBSERVED=10

REAL_RETRIEVAL_QUERY=PASS      (30 requêtes HTTP réelles, 10 collections × 3)
CROSS_SCOPE_REFUSED=403
ARTIFACTS_DISCOVERED=11/11
```

`1 passed` — PostgreSQL+pgvector jetables réels, LocalGitHub, LOT41A, Worker A,
LOT42, Worker B, provider E5 vérifié, reranker vérifié, et un **vrai processus
uvicorn** servant `src.ingestor.api_v2:app`.

## Le défaut, et rien d'autre

Six prédicats étaient déjà écartés (`CHUNK_DRIFT`, `PLACEMENT_DRIFT`,
`SCOPE_BINDING`, `MODEL_DRIFT`, `DB_ROLE_DRIFT`, `COLLECTION_READINESS` :
tous faux). Restait `SERVABLE_COLLECTION_SELECTION`.

Instrumentation posée **dans le processus uvicorn qui répond**, pas dans un
script à côté. Pour chaque scope successeur, `/collections/v2` a rendu la table
de prédicats exigée. Le premier faux :

```
FIRST_FALSE_PREDICATE=retrievable_catalogue_contains
EXPECTED=true
OBSERVED=false                 (8 collections sur 10)
```

Mesuré, collection par collection :

```
SERVED_BY_RELEASE=10
IN_RETRIEVABLE_CATALOGUE=2     (rag_nexus_nsi_premiere_specialite,
                                rag_nexus_nsi_terminale_specialite)
MISSING=8                      rag_nexus_maths_seconde_tc
                               rag_nexus_francais_seconde_tc
                               rag_nexus_maths_quatrieme_tc
                               rag_nexus_francais_quatrieme_tc
                               rag_nexus_maths_premiere_gen_specialite
                               rag_nexus_francais_premiere_tc
                               rag_nexus_maths_terminale_gen_specialite
                               rag_nexus_pc_terminale_specialite
```

### La cause

`/collections/v2` ne retient qu'une collection `instanciee: true` dont le
domaine est `retrievable: true`. Les huit collections sont `instanciee: false`
dans `configs/rag_collections.yml` — et c'est **correct** au regard de la
propriété que `a4b1f96` (PR #142) a scellée :

> l'ensemble instancié est exactement celui des collections que les releases
> scellées du registre servent, plus la quarantaine.

Or le registre `release-registry.json` ne déclare **qu'une** release : la porte
de profils production, onze collections. La release multi-niveaux n'y figure
pas — elle en a été retirée à `3566caf` (PR #133), lorsque
`build_production_profile_release.py` a réécrit le registre entier avec sa
seule entrée. Avant cela (`2182339`, PR #95), le registre portait bien
`multilevel-2026-2027-v1` et ses dix collections.

Le banc configurait donc l'autorité de release multi-niveaux
(`RAG_RELEASE_MANIFESTS_JSON`) **et** le catalogue de production. Deux
autorités qui ne parlent pas de la même release : le sélecteur, fidèle,
n'annonçait rien.

### Pourquoi pas « remettre la release au registre »

Le lecteur du registre refuse qu'une collection soit servie par deux releases :

```python
if seen_declared_collections.intersection(collections):
    raise ReleaseReadinessError("release registry collection collision")
```

`rag_nexus_nsi_premiere_specialite` et `rag_nexus_nsi_terminale_specialite`
sont servies par les deux lignées. Ajouter la release multi-niveaux au registre
de production rendrait celui-ci invalide. **Cette garde n'a pas été touchée** :
c'est elle qui a rendu le conflit visible.

## Le correctif

Le catalogue de v2 dispose déjà d'une forme d'overlay de déploiement
(`RAG_COLLECTIONS_STAGING_OVERLAY_V1`), **activation seulement** : elle ne peut
qu'allumer une collection dormante, jamais en éteindre une servie ailleurs.
C'est exactement l'outil.

| Livrable | Chemin |
|---|---|
| Catalogue du banc multi-niveaux | `services/rag-engine/configs/staging/rag_collections_multilevel.yml` |
| Liaison catalogue ↔ release | `services/rag-engine/tests/test_multilevel_staging_catalogue.py` |

L'overlay active les **huit** collections dormantes que la release
multi-niveaux sert (les deux NSI le sont déjà par la release production), et
rien d'autre. Les quatre épreuves lient l'overlay à la release, et non à une
liste figée :

- la release mesurée est bien celle que le banc épingle (`6ec1a4f8…`) ;
- le banc monte l'overlay, pas le catalogue de production ;
- `served ⊆ servable` sur le catalogue du banc ;
- `activées == served − déjà_instanciées` : aucune activation en trop.

Rouge avant l'overlay (`served − servable = 8`), vert après.

### Ce qui n'a pas bougé

- `instanciee` du catalogue canonique `configs/rag_collections.yml` ;
- `release-registry.json` et la garde de collision ;
- la garde `scope source SHA differs from subject release` ;
- le plancher de pertinence `RERANK_THRESHOLD = 1.90` ;
- les dix-huit scopes `prod_*`, la release archivée du 2026-08-13.

## Preuve dans le processus qui sert

Table rendue par `/collections/v2` **depuis le processus uvicorn**, après
correctif, pour les scopes atteints :

```
scope_id                      collection                              raw  retr  ev_coll  ev_v2  exact  selected
entree_premiere_maths_v2      rag_nexus_maths_seconde_tc              True True  True     True   True   True
entree_premiere_francais_v2   rag_nexus_francais_seconde_tc           True True  True     True   True   True
entree_troisieme_maths_v2     rag_nexus_maths_quatrieme_tc            True True  True     True   True   True
entree_troisieme_francais_v2  rag_nexus_francais_quatrieme_tc         True True  True     True   True   True
entree_terminale_maths_v2     rag_nexus_maths_premiere_gen_specialite True True  True     True   True   True
entree_terminale_nsi_v2       rag_nexus_nsi_premiere_specialite       True True  True     True   True   True
eaf_premiere_francais_v2      rag_nexus_francais_premiere_tc          True True  True     True   True   True
```

Contexte du processus, relevé dans la requête elle-même — jamais comparé entre
un script et le serveur :

```
CONFIG_PATH=…/configs/staging/rag_collections_multilevel.yml
CONFIG_SHA=698cfa8e45027215173452d67c92607754a410fb3f6ab6efc6e594764791be0e
CATALOGUE_SHA=a3708c093ae97fb0b9906e841c6d14303ade97d0da12607bcd7746339745bf8f
CATALOGUE_SIZE=19
SCOPE_REGISTRY_SHA=f34afca149e5b403a448f72e657f7b369555f2e6d11c4ad7c839a3db1c43cc8f
RELEASE_REGISTRY_SHA=bc958092cc564a9247c16aab35a9aa5fb3176166997a94b9f8a81d41c03c84e4
RELEASE_IDS=['multilevel-2026-2027-v1']
MODULE_PATH=…/src/ingestor/retrieval_v2_endpoint.py
```

L'instrumentation était temporaire et n'est pas livrée : elle a servi à
produire cette table, la garde n'a jamais été modifiée.

## Deux cas sémantiques requalifiés, mesurés

La release régénérée re-partitionne le texte : sur l'artefact de
`rag_nexus_francais_premiere_tc`, **36 des 38 chunks** ont un contenu différent
de la release archivée, à nombre de chunks et de pages égal. Deux des trente
questions du banc, épinglées sous l'ancienne partition, ne tenaient plus.

Reproduction hors banc, à l'octet près : les 38 chunks recalculés depuis le PDF
du miroir, avec l'extracteur et le découpeur du dépôt et le tokenizer E5
vérifié, rendent **exactement** les 38 `chunk_sha256` de la release. C'est donc
bien la partition servie qui est mesurée.

| Cas | Ancienne formulation | Meilleure logit | Nouvelle formulation | Logit |
|---|---|---|---|---|
| eaf #2 | « Quelles compétences prépare-t-on pour les épreuves anticipées de français ? » | **−1.251** | « Quels exercices d'écrit et d'oral prépare-t-on en première en vue des épreuves anticipées de français ? » | **2.032** |
| eaf #3 | « Comment le programme de première organise-t-il lecture, écriture et étude de la langue ? » | 4.028, mais l'extrait de 200 caractères rendu ne contient pas « langue » | « Comment l'étude de la langue est-elle conduite en classe de première ? » | **4.682**, extrait portant « la complexité de la langue » |

Le plancher de 1.90 n'a pas été abaissé, et l'extrait n'a pas été retouché :
ce sont les questions qui ont été remesurées contre le corpus réellement servi.
Les vingt-huit autres cas passent inchangés — mesuré hors banc sur les onze
artefacts avant de relancer.

## Qualité

| Cible | Résultat |
|---|---|
| `services/rag-engine` — pytest (`-m "not integration"`) | vert, exit 0 |
| `services/rag-engine` — `ruff check src tests` | All checks passed |
| `services/rag-engine` — `mypy src` | Success: no issues found in 132 source files |
| `services/rag-engine` — banc réel multi-niveaux | **1 passed** |
