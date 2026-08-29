# Tir de charge — après passage à 8 CPU, 28 août 2026

*Suite de `tir_de_charge_20260828.md`, qui constatait 18 collections sur 18 en `503`.*

## Le geste

Une ligne de `docker-compose.v2.yml` : `cpus: "2.0"` → `"8.0"`, plus l'alignement
des fils torch (`OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `TORCH_NUM_THREADS` à 8).

Le plafond est à **8 et non 16**, par mesure : sur ce poste chargé, 16 threads
donnaient 2 533 ms au rerank de 50 paires contre 1 438 ms à 8. « Plus de cœurs »
n'était pas la bonne réponse.

## La panne est levée

| | Avant (2 CPU) | Après (8 CPU) |
|---|---|---|
| Collections servies | **0 / 18** | **18 / 18** |
| Latence | 6003 ms → `503` | **1 146 à 3 258 ms** |
| Médiane | — | **2 731 ms** |

Contre un budget de 6 000 ms, la marge médiane est de **2,2×**. Le RAG sert.

## La courbe de concurrence

Celle qui manquait. 18 requêtes par palier, questions réelles sur les 18
collections, chemin HTTP complet.

| Concurrence | p50 | p95 | Servies | Hors budget | Débit/s |
|---|---|---|---|---|---|
| **1** | 2731 ms | 8426 ms | 17/18 | 1 | 0.36 |
| **2** | 4573 ms | 6009 ms | 13/18 | 5 | 0.41 |
| **4** | 6005 ms | 6011 ms | 2/18 | 16 | 0.6 |
| **8** | 6021 ms | 6028 ms | 1/18 | 17 | 1.0 |
| **16** | 6015 ms | 6022 ms | 1/18 | 17 | 1.5 |

### Le point de rupture est à **2**

Il n'est pas au-delà de 8, ni de 4 : **dès deux requêtes simultanées**, 5 sur 18
dépassent le budget. À 4, il en reste 2 servies sur 18.

La lecture est mécanique : le rerank est CPU-bound et sature les 8 cœurs à lui
seul. Deux requêtes concurrentes s'en partagent quatre chacune — soit le régime
qui échouait déjà avant le correctif.

**Capacité réelle du service aujourd'hui : un utilisateur à la fois.**

Pour une plateforme destinée aux élèves, c'est la contrainte structurante. Elle
ne se lève pas en ajoutant des cœurs : la machine en a 16, et 16 threads sont
plus lents que 8.

## Requalification des dettes

**n°26 — panne de service → résolue à concurrence 1.** La cause était
l'allocation CPU, pas l'algorithme. Corrigée par configuration, sans affaiblir
aucun contrôle : ni `CHANNEL_LIMIT` réduit, ni budget relevé, ni rerank désactivé.
Reste ouverte au titre de la concurrence, ci-dessous.

**n°27 — courbe inconnue → tracée, point de rupture = 2.** L'énoncé antérieur
disait « il est plausible que deux requêtes concurrentes franchissent le budget,
mais cela n'a pas été mesuré ». C'est désormais mesuré, et c'est exact : à
concurrence 2, 28 % des requêtes échouent. La dette change de nature — elle
n'est plus « non mesurée », elle est **« capacité d'un seul utilisateur »**.

## Ce qui lèverait la contrainte

Le rerank sur GPU coûte **265 ms pour 50 paires contre 1 438 ms à 8 threads** —
mesuré. Un facteur 5,4 sur l'étape dominante déplacerait le point de rupture
d'environ un ordre de grandeur.

**Mais le GPU n'est pas accessible au conteneur, et pour deux raisons distinctes :**

1. **`torch` dans l'image est en `2.4.1+cpu`** — build CPU-only, sans CUDA. Les
   venvs portent `2.13.0+cu130` et `2.12.1+cu130`. Double écart : CPU-only *et*
   très en retard.
2. **Le toolkit conteneur NVIDIA n'est pas installé.** `docker info` ne déclare
   que le runtime `runc` ; aucun paquet `nvidia-container-toolkit`, aucun dépôt
   configuré, aucun `/dev/nvidia*` ni `nvidia-smi` dans le conteneur — vérifié.

Corriger la roue seule ne suffirait donc pas : le conteneur ne verrait toujours
aucun périphérique. Les deux sont nécessaires, et le second **exige l'opérateur**
(dépôt NVIDIA, `apt install`, `nvidia-ctk runtime configure`, redémarrage du
démon Docker).

Ce redémarrage est **le même** que celui de la dette n°9. Les deux gestes se
font dans une seule fenêtre.

## La frontière runtime/dépôt a mordu une seconde fois

`nexus-contracts` 0.14.0 figé dans l'image quand le dépôt était en 0.16.0 était
le premier cas. `torch` est le second, et il est pire : deux divergences
superposées, et **aucune ne se voit dans les journaux du service**. Un runtime
CPU-only ne se plaint pas de l'être.

`check_runtime_conformance.py` est étendu aux dépendances tierces partagées et à
la capacité CUDA. Il rapporte désormais :

```
[bloquant] tous / torch : versions divergentes entre runtimes —
  nexusrag-ingestor:latest = 2.4.1+cpu, rag-engine/.venv = 2.13.0,
  rag-pedago/.venv = 2.12.1
[bloquant] nexusrag-ingestor:latest / torch : build CPU-only, quand les venvs
  portent CUDA 13.0 — ce runtime ne peut pas utiliser le GPU, et rien dans ses
  journaux ne le dit
```

Pour une dépendance tierce il n'existe pas de version « déclarée » par le dépôt :
la référence est **l'accord entre runtimes**. Un désaccord suffit à constituer le
défaut — deux runtimes sur des versions différentes ne prouvent rien l'un de
l'autre.

## Contrainte de VRAM à écrire avant de l'apprendre en panne

Le GPU porte **4 Go**. L'embedding e5-large en consomme **2,44 Go** mesurés.

**Servir et ingérer simultanément sur ce GPU épuisera la VRAM.** L'ingestion des
2451 documents et le service de retrieval doivent être **séquencés**, jamais
concurrents. C'est exactement la contrainte qu'on redécouvre en panne si elle
n'est écrite nulle part.

## Un chiffre à ne pas surinterpréter

À concurrence 1, le p95 est de **8 426 ms** — au-dessus du budget, sur une
requête pourtant servie. Le budget porte sur le chemin base/inférence, pas sur
le temps mural total. Une requête peut donc dépasser 6 s de bout en bout sans
être refusée. La médiane à 2 731 ms reste la grandeur qui décrit le régime
nominal ; ce p95 dit qu'il existe une queue, et elle n'est pas expliquée ici.
