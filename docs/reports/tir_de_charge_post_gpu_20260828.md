# Tir de charge post-GPU — la mise en service est tenable

*28 août 2026. Troisième et dernière mesure de la série.*

## La série complète

| État | Concurrence 1 | Point de rupture |
|---|---|---|
| 2 CPU, torch CPU-only | **0/18 servies** — `503` | *en dessous de 1* |
| 8 CPU, torch CPU-only | p50 2 731 ms, 17/18 | **2** |
| **8 CPU + GPU, torch cu130** | **p50 632 ms, 18/18** | **entre 8 et 16** |

## La courbe, avant et après GPU

| Concurrence | 8 CPU (p50 — servies) | GPU (p50 — servies) | Gain |
|---|---|---|---|
| **1** | 2731 ms — 17/18 | **632 ms — 18/18** | 4.3× |
| **2** | 4573 ms — 13/18 | **946 ms — 18/18** | 4.8× |
| **4** | 6005 ms — 2/18 | **1834 ms — 18/18** | 3.3× |
| **8** | 6021 ms — 1/18 | **3296 ms — 18/18** | 1.8× |
| **16** | 6015 ms — 1/18 | **5779 ms — 10/18** | 1.0× |
| **32** | — | **6010 ms — 7/18** | — |

**Le point de rupture passe de 2 à entre 8 et 16.** À concurrence 8, les dix-huit
collections répondent, aucune hors budget, p50 à 3 296 ms contre 6 000 de budget.

**Capacité de service : huit utilisateurs simultanés, intégralement servis.**
C'était un à la fois il y a une heure.

À 16, 8 requêtes sur 18 dépassent — c'est la limite haute, et elle est connue.

## La queue inexpliquée a disparu

À concurrence 1, le p95 était de **8 426 ms** sur une requête pourtant servie, et
je disais ne pas l'expliquer. Après GPU, le p95 à concurrence 1 est de **729 ms**,
pour une médiane de 632 ms.

L'écart p50/p95 passe de 3,1× à 1,15×. La queue était donc bien un effet de
contention CPU — mais ce n'est établi que par sa disparition, pas par une cause
identifiée. Je l'enregistre comme résolu **de fait**, non comme compris.

## La preuve cosinus, depuis le conteneur

La pile ML a changé en profondeur : `torch` 2.4.1+cpu → 2.13.0+cu130,
`transformers` 4.44.2 → 5.16.1, `sentence-transformers` 3.0.1 → 5.6.0. Trois
versions majeures. Le conteneur encode les requêtes : si ses vecteurs dérivent,
tout le retrieval dérive.

Contrôle exécuté **dans le conteneur, sur le GPU**, contre les vecteurs stockés
en base — produits avant le changement :

| Chunk | Cosinus | Écart |
|---|---|---|
| `0079a770ec493a2d…` | 0,999999999998 | 1,53·10⁻¹² |
| `022ff3d958f7f465…` | 0,999999999998 | 2,12·10⁻¹² |
| `0289ab2511987282…` | 0,999999999997 | 3,05·10⁻¹² |

**Écart maximal 3,05·10⁻¹², seuil 10⁻⁷** — cinq ordres de grandeur sous la
limite. Aucune dérive. Les 730 vecteurs en base restent valides ; aucun
ré-encodage n'est requis.

## La contrainte de VRAM a mordu pendant ce lot

Elle avait été écrite dans le compose une heure plus tôt. Elle s'est vérifiée
immédiatement : lancer la preuve cosinus **pendant que le service tournait** a
donné

```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 978.00 MiB.
GPU 0 has a total capacity of 3.62 GiB of which 534.19 MiB is free.
Process 1 has 2.25 GiB memory in use.
```

Le service détient 2,25 Gio en régime nominal. **Une seconde instance du modèle
n'entre pas.** La preuve a été obtenue en arrêtant le service, mesurant, puis en
le redémarrant — le séquencement, appliqué.

Ce n'est pas un incident : c'est la contrainte qui se comporte comme annoncé.
Elle vaut à l'identique pour l'ingestion des 2451 documents, qui **ne doit pas
recouvrir le service**.

## Requalification finale

**n°26 — close.** La panne venait de l'allocation CPU et de la build CPU-only.
Corrigée par configuration et par alignement de version, sans qu'aucun contrôle
soit affaibli : `CHANNEL_LIMIT` inchangé, budget inchangé, rerank actif,
sceaux intacts, preuve cosinus rejouée.

**n°27 — close en tant que « non mesurée ».** La courbe est tracée trois fois.
Ce qui subsiste est une **caractéristique connue** et non une dette : capacité
de huit utilisateurs simultanés sur ce matériel, rupture entre 8 et 16.

## Ce qui reste vrai malgré ces chiffres

Le service tient, mais deux bloqueurs de mise en service demeurent, tous deux
hors du domaine de la performance :

- **n°28** — aucun rôle `student` ne peut interroger le corpus (`visibility:
  internal`). Analysé, non appliqué : c'est une décision de gouvernance.
- **La production sert un code antérieur au contrat.** La mise en service est une
  migration, avec un existant en ligne.
