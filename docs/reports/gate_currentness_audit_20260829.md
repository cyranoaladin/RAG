# Voie C était déjà implémentée — et le blocage final est externe

*29 août 2026.*

## Correction : la trouvaille du multi-placement était fausse

J'ai rapporté que `rag_chunks_pkey (chunk_id)` empêchait le multi-placement et
que **2 990 placements seraient silencieusement vides**. **C'est faux, et vous
avez décidé sur cette base — la correction vous est due.**

Le retrieval **n'utilise déjà pas** `chunk.collection` :

```sql
-- retrieval_pg_v2.py, _EFFECTIVE_SCOPE_FILTER_SQL
chunk.artifact_id IS NOT NULL
AND matched_placement.placement_id IS NOT NULL   ← la collection vient du PLACEMENT
```

`chunk.collection` n'est lu que dans la branche héritée, `chunk.artifact_id IS
NULL`. Vérifié en base : **730 chunks sur 730 portent un `artifact_id`. Zéro
emprunte la branche héritée.**

**Voie C est l'implémentation en place.** Le plan d'exécution le confirme :
`LEFT JOIN LATERAL` avec `Memoize` sur `artifact_id` — précisément la structure
qu'un multi-placement exploite au mieux.

Il n'y avait rien à décider, et votre raisonnement — la collection est une
propriété du placement — était **déjà celui du code**. J'ai lu la clé primaire
sans lire la requête.

## Les hypothèses 1:1 réellement rencontrées, et retirées

Le producteur de release, lui, supposait 1:1 en **cinq** points. Chacun était une
CONSTANTE figeant le périmètre d'un jour, jamais un invariant :

| Site | Constante | Invariant conservé |
|---|---|---|
| `stable_release_order` | unicité globale du contenu | `(collection, contenu)` unique |
| `_source_records` | `len(ordered) != 26` + empreinte gravée | produit == déclaré par la matrice |
| `_release_scope_inputs` | `len(contents) != 26` | idem |
| `_release_scope_inputs` | `len(profiles) != 18` | `== len(profiles)` du registre |
| `validate_pdf_mirror` | contenu dupliqué refusé | le miroir est 1:1 par nature — la demande se déduplique |

Trois tests verrouillent le premier, dans les deux sens.

## Deux défauts de matérialisation, les miens

**Le miroir attendait des fichiers nommés par empreinte** ; le corpus téléchargé
porte l'arborescence Drive. Miroir adressé par contenu construit en liens durs :
**2 451 fichiers, aucun octet dupliqué.**

**`1_Pooling` à nouveau omis** — `cp` sans `-r` sur le snapshot nommé par
révision. C'est exactement le défaut qui a coûté la nuit de jeudi, reproduit par
moi dans un `cp`. Corrigé, vérifié présent.

## Le blocage final — externe, pas une décision

`resolve_currentness_network_audit` exige, pour chaque document, une **attestation
d'actualité vérifiée contre la source**. Deux modes :

- `--verify-official-downloads` → acquisition **réseau** via `curl` sur
  `current_download_url` ;
- hors ligne → rejeu contre un audit **scellé** préexistant.

Aucun des deux n'est atteignable :

1. **Il n'existe pas d'audit scellé** pour les 2 389 documents — celui du dépôt
   couvre les 26.
2. **`current_download_url` est vide** pour ces documents : le catalogue de
   provenance porte l'URL de *listing*, pas celle de téléchargement, et je me
   suis refusé à présenter l'une pour l'autre.
3. **Éduscol répond 403** à toute requête programmée — vérifié à l'instant sur
   une URL du corpus, et déjà constaté avec un `User-Agent` de navigateur comme
   avec `curl`.

**Ce n'est pas un arbitrage que vous pouvez trancher.** La release atteste que
chaque document est à jour à sa source ; la source refuse d'être interrogée. Il
faudrait soit une voie d'accès autorisée à Éduscol, soit décider que
l'attestation d'actualité se fonde sur autre chose que la vérification en direct
— et cela, c'est un ADR sur ce qu'atteste une release.

## État

Tout le reste est écrit, vérifié, commité : **2 400 placements**, **121 profils**
valides, **121 partitions**, manifeste à `declared_count = 121`, autorité de
provenance scellée et raccordée, miroir de 2 451 fichiers, cinq hypothèses 1:1
retirées avec leurs invariants conservés.

**L'ingestion n'a pas eu lieu.**
