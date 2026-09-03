# LOT 1.2 — la correction du LOT 1c existait déjà, et elle est meilleure que la mienne

> Épreuve exigée avant le cherry-pick : la correction du générateur d'inventaire survit-elle
> dans la version 319 du producteur ? Elle y était avant moi.

## Le verdict

```
version 319 de _model_inventory, docstring datée du 27/08/2026
   « Le parcours était snapshot.iterdir() — non récursif — filtré par is_file(),
     qui écarte les répertoires SANS ERREUR NI AVERTISSEMENT. […]
     Le 27/08/2026, cela a produit un artefact embedding sans 1_Pooling/ :
     conforme à son empreinte, et incapable de se charger. »

éprouvée contre les instantanés réels
   EMBEDDING  rendu 58ad18db…  attendu 58ad18db…  CONCORDE
   RERANKER   rendu d7c1b418…  attendu d7c1b418…  CONCORDE
```

**La correction existe sur la branche 319 depuis le 27 août, quatre jours avant la mienne**,
et elle produit exactement les empreintes que la production porte. Le contrat est respecté :
le cherry-pick ne réintroduira pas le défaut.

## Les deux versions diffèrent, et la leur est meilleure sur les deux points

| | version 319 (27 août) | ma version (LOT 1c) |
|---|---|---|
| récursion | `rglob`, chemins relatifs POSIX | identique |
| `manifest.json` / `SHA256SUMS` dans l'entrée | **ignorés** | **refusés** |
| liens symboliques | **suivis, délibérément** | **refusés** |

### Sur les liens symboliques, j'avais tort

La version 319 documente son choix :

> `is_file()` suit les liens symboliques, et c'est requis : le cache hub HuggingFace —
> passé tel quel en `--embedding-snapshot`, son nom devant être la révision — ne contient
> que des liens vers `../../blobs`. Les exclure viderait l'inventaire.

**J'avais transposé au producteur une règle du vérificateur.** Le vérificateur d'exécution
refuse les liens sous la racine de l'*artefact monté*, et il a raison. Le producteur reçoit
un *instantané de construction*, qui n'est pas le même objet — le cache HuggingFace en est
un, et il est fait de liens.

Mesuré : aucun des répertoires de modèle de cette machine ne contient de lien symbolique,
donc mon refus **ne casse rien aujourd'hui**. Il casserait le cas documenté, standard, du
cache hub passé directement.

### Sur les produits en entrée, la leur est plus juste

Ignorer `manifest.json` et `SHA256SUMS` rend le producteur **idempotent** : la même entrée
donne le même inventaire, que la sortie précédente y traîne ou non. Mon refus attrape une
erreur d'opérateur, mais au prix de l'idempotence.

## Conséquence

**Le cherry-pick apporte la version 319, qui supersède ma correction du LOT 1c sur cette
fonction.** Mon refus des liens symboliques ne doit pas survivre à la fusion.

Ce que ma correction garde d'utile : les huit tests écrits pour elle. Trois portent sur la
récursion et la couverture exacte et restent valides ; celui qui exige le refus d'un lien
symbolique doit être retiré, et celui qui exige le refus d'un produit en entrée doit être
inversé en « ignoré ».

## Ce que cet épisode établit

**Une correction juste existait sur une branche et n'a jamais atteint `main`.** Je l'ai
réinventée quatre jours plus tard, moins bien, et je l'ai présentée comme une découverte.

C'est le même motif que tout le reste de ce dossier — du travail détenu sur une branche,
invisible depuis la source publiée — appliqué cette fois à un correctif. Et il a un coût
particulier : **une correction réinventée sans connaître l'originale perd les raisons de
l'originale.** La raison, ici, était le cache HuggingFace, et je ne pouvais pas la deviner.
