# LOT 1 — les 167 placements manquants : ni arrêt, ni choix d'ingestion

> Question posée : les 167 placements déclarés et absents de la base sont-ils un arrêt de
> l'ingestion, ou un choix de ne matérialiser qu'un placement par contenu ?
> **La réponse n'est ni l'un ni l'autre : le schéma les rend impossibles.**

## La répartition — parfaitement régulière

```
contenus à 1 placement déclaré → 1 matérialisé ....... 152
contenus à 2 placements déclarés → 1 matérialisé ..... 167
TOUT contenu a exactement un placement matérialisé ... vrai, sans exception

les 167 manquants, par collection
   hlp_terminale_specialite ..... 86 manquants sur 90 déclarés
   nsi_terminale_specialite ..... 28 sur 47
   hggsp_terminale_specialite ... 22 sur 35
   ses_terminale_specialite ..... 20 sur 28
   svt_terminale_specialite ..... 11 sur 38
   toutes les collections de PREMIÈRE ..... 0 manquant
   dgemc_terminale_option ................. 0 manquant
```

Et pour les 167 contenus doublement placés, **la collection conservée est celle de première
dans 167 cas sur 167**.

Une répartition parfaitement régulière n'est pas un arrêt : un arrêt produit une coupure.

## Le mécanisme, lu dans le schéma servi

```sql
-- rag_artifacts
CHECK  (artifact_id = content_sha256)
UNIQUE (content_sha256)
PRIMARY KEY (artifact_id)
-- aucune colonne `collection`

-- rag_chunks
CHECK  (doc_id = artifact_id)                                    -- governed_identity
UNIQUE (artifact_id, chunk_index) WHERE artifact_id IS NOT NULL  -- sans la collection
```

La déduction est mécanique :

1. un contenu a **exactement une** ligne dans `rag_artifacts` — son identité **est** son
   empreinte de contenu, et la contrainte l'impose ;
2. `rag_artifacts` **n'a pas de colonne `collection`** : un artefact n'appartient à aucune
   collection en propre ;
3. dans `rag_chunks`, le couple `(artifact_id, chunk_index)` est **unique sur toute la
   table**, la collection n'entrant pas dans la clé.

Donc pour un contenu donné, le chunk d'indice *k* ne peut exister **qu'une fois dans toute
la base**. Le placer dans une seconde collection exigerait de réinsérer les mêmes couples :
l'index l'interdit.

**Un contenu ne peut être matérialisé que dans une seule collection.** Ce n'est pas une
règle de l'ingesteur, c'est le modèle de données.

## Ce que cela établit

**La release et la base ne partagent pas le même modèle du placement.**

```
modèle de la RELEASE   un contenu peut être placé dans plusieurs collections
                       → 486 placements pour 319 contenus
modèle de la BASE      un contenu vit dans exactement une collection
                       → 319 placements possibles au maximum
```

Les 167 placements ne manquent pas parce que quelque chose s'est arrêté ou a choisi : ils
manquent parce que **la base ne peut pas les contenir**. Aucune reprise d'ingestion ne les
matérialisera tant que le schéma est celui-ci.

## Conséquences

- **Les 4 079 chunks ne sont pas récupérables par une reprise.** Un tiers du corpus scellé
  est hors d'atteinte du modèle de données actuel.
- **`rebuild` (LOT 2) produira 8 324 et non 12 403**, et la divergence sera exactement de
  4 079. Ce n'est pas un défaut de `rebuild` : c'est cette contradiction, rendue visible.
- **La porte de cohérence (LOT 1.3) doit comparer des grandeurs comparables.** Confronter
  486 placements déclarés à 319 matérialisés ferait échouer la porte sur une contradiction
  de modèle, non sur une incohérence de données.
- **L'ADR du LOT 1 doit trancher lequel des deux modèles fait foi.** Si un document doit
  pouvoir servir en première et en terminale, la clé unique doit inclure la collection. Si
  un contenu appartient à une seule collection, la release ne doit pas déclarer 486
  placements.

## Périmètre

Contraintes et index lus dans la base servie `ragdb` le 2026-09-01, via
`pg_constraint` et `pg_indexes`. Aucune écriture, ni transaction d'essai. La déduction
d'impossibilité est tirée des définitions, non d'une tentative d'insertion.
