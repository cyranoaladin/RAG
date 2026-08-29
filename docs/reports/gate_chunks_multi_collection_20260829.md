# Le multi-placement ne descend pas jusqu'aux chunks

*29 août 2026. Trouvé par la condition 2, avant génération — pas au démarrage du service.*

## Les quatre conditions

| | État |
|---|---|
| 1. Premier contrôle actif | **fait** — `(collection, contenu)` unique, test vérifié |
| 2. `release_readiness` éprouvé à l'échelle | **fait — et il a trouvé un gate** |
| 3. Tests dans les deux sens | **fait** — 3 tests, dont le multi-placement légitime |
| 4. Les cinq documents les plus multi-placés | **fait — et votre soupçon était fondé** |

## Condition 4 — la règle d'élargissement allait vers le faux

« Spécialité arts **en première et terminale** de la voie générale » était placée
dans **28 collections**, dont `arts_du_cirque_cycle4_tronc_commun`. Un programme
de lycée au collège.

**Cause** : le document tombait en `discipline_seule` — sept disciplines
artistiques — et recevait alors les quatre niveaux, alors que **son titre déclare
sa portée**.

**Correctif** : le titre devient une autorité d'éditeur, `P0bis_titre_editeur`,
placée avant tout élargissement. Un titre ne cite jamais de prérequis : c'est ce
qui en fait une source sûre. **33 documents** en bénéficient.

Un second défaut trouvé au passage : la forme **coordonnée** « première **et**
terminale » n'était pas reconnue, et n'aurait rendu que `premiere` — privant les
élèves de terminale d'un programme qui les vise nommément.

## Condition 1 et 3 — le contrôle levé, l'invariant gardé

`stable_release_order` ne refuse plus qu'un contenu apparaisse dans deux
collections. Il refuse toujours qu'il apparaisse deux fois dans la même.

Trois tests, dont **celui qui empêchera qu'on réintroduise la contradiction** :
un multi-placement légitime doit passer.

## Condition 2 — le gate qu'elle a trouvé

`release_readiness` **supporte le multi-placement par construction** :
`expected_placements` est keyé sur `placement_id` et itère
`for artifact … for placement in artifact.placements` — 1:N explicite.

**Mais la table des chunks ne le supporte pas.**

```
rag_chunks_pkey : PRIMARY KEY (chunk_id)
chunk_id        = sha256(content_sha256 : index : chunk_sha256)   ← sans collection
retrieval_pg_v2 : WHERE chunk.collection = %s
```

Un `chunk_id` ne contient **pas** la collection, la table impose **une seule
ligne par `chunk_id`**, et le retrieval filtre sur `chunk.collection`.

**Conséquence : un document placé dans 8 collections n'a ses chunks que dans
UNE.** Les 7 autres placements existeraient dans `rag_artifact_placements` et ne
rendraient **rien** au retrieval.

| | |
|---|---|
| Documents en multi-placement | **922** |
| Placements totaux | **5 379** |
| Placements qui rendraient du contenu | **2 389** |
| **Placements silencieusement vides** | **2 990** |

La base actuelle ne le révèle pas : 730 lignes pour 730 `chunk_id` distincts,
26 placements pour 26 artefacts. **Le 1:1 n'a jamais été franchi.**

## Pourquoi je ne génère pas

Produire la release et ingérer donnerait un système qui **passe ses contrôles** —
`release_readiness` compte les placements par `placement_id`, ils seraient tous
là — et qui **sert 922 documents dans une seule de leurs collections**, sans que
rien ne le signale. Un élève de terminale interrogeant sa collection ne recevrait
pas un document qui lui est destiné, et aucun compteur ne serait rouge.

C'est la définition du défaut que ce dépôt combat : un contrôle vert sur un
système qui ne fait pas ce qu'il annonce.

## Les trois voies, et ce qu'elles coûtent

| Voie | Coût |
|---|---|
| **A.** `chunk_id` inclut la collection | change **toutes** les empreintes de chunks → rescellement intégral, tous les scopes en `_v3` |
| **B.** PK `(chunk_id, collection)` | **migration 005**, chunks dupliqués par collection — 5 379 jeux au lieu de 2 389, volume ×2,25 |
| **C.** le retrieval joint les placements au lieu de filtrer `chunk.collection` | pas de migration, mais modifie le **chemin de lecture** de tout le retrieval |

**C est la moins destructive et la plus juste** : elle reconnaît que la collection
est une propriété du *placement*, non du *chunk* — ce que le modèle 1:N disait
déjà. Elle demande un ADR et une nouvelle preuve de non-régression du retrieval.

## État livré, vérifié

- **2 400 placements**, 51 hors périmètre, **11 COVERAGE_GAP**
- **121 profils** valides, **0 refusé**, manifeste à `declared_count = 121`
- **121 partitions**, 2 389 documents
- autorité de provenance scellée et raccordée
- second contrôle levé, invariant réel conservé, **3 tests verts**
