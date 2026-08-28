# Tir de charge — /search/v2, runtime réel, 28 août 2026

> **Verdict : le service ne sert pas.** À concurrence **1**, séquentiellement,
> **18 collections sur 18** dépassent le budget et renvoient `503`. Il n'existe
> pas de point de rupture à chercher plus haut : il est en dessous de 1.

## Ce qui a été mesuré

Chemin HTTP complet sur le runtime en service (`nexusrag-ingestor-1`), base
canonique, credential BFF **et** enveloppe d'identité signée, pipeline entier
dense → lexical → RRF → rerank → seuil → MMR. Aucun composant isolé, aucune
simulation, aucun contournement d'authentification.

Une question par matière, tirée du programme réellement ingéré. Profil élève et
`curriculum_scope` **dérivés du scope signé** et non devinés.

## Résultat

Passe propre, aucune autre activité sur le poste :

| Collections interrogées | 18 |
|---|---|
| Réponses `200` | **0** |
| Réponses `503` | **18** |
| Latence observée | 6002 à 6077 ms — le plafond, pas une mesure |

Trois passes successives (froid, puis deux fois chaud) donnent le même résultat.
**Ce n'est pas un cache froid** : le second et le troisième tour échouent comme
le premier.

Sur des passes antérieures, deux collections ont répondu : `francais_quatrieme_tc`
(5533 ms, 5590 ms) et `ses_terminale_specialite` (4910 ms). Ce sont les **deux
plus petites** — 20 et 18 chunks. C'est l'indice qui a mené à la cause.

## La cause

Deux faits, mesurés :

**1. Le conteneur ne dispose que de 2 cœurs sur les 16 de la machine.**

```
docker inspect nexusrag-ingestor-1 --format '{{.HostConfig.NanoCpus}}'
2000000000        # = 2,0 CPU
```

Pire, `torch.get_num_threads()` vaut **8** dans ce conteneur : huit fils
d'exécution se disputent deux cœurs. La sur-souscription ne ralentit pas
proportionnellement, elle ralentit **plus** que le simple manque de cœurs.

**2. Le coût du reranking dépasse le budget à lui seul.**

Mesuré dans le conteneur, hors plafond de requête :

| Étape | Coût |
|---|---|
| Encodage de la requête (e5-large) | 631 ms |
| Rerank 18 paires | 2 026 ms |
| **Rerank 50 paires** | **5 597 ms** |

5 597 + 631 = **6 228 ms** > 6 000 ms. Le `503` à 6003 ms n'est pas un incident :
c'est l'arithmétique.

**3. La taille des collections explique exactement qui passe et qui échoue.**

| Collection | Chunks | Verdict |
|---|---|---|
| `ses_premiere_specialite` | 16 | — |
| `ses_terminale_specialite` | 18 | a répondu (4910 ms) |
| `nsi_terminale_specialite` | 18 | — |
| `francais_quatrieme_tc` | 20 | a répondu (5533 ms) |
| … | | |
| `svt_terminale_specialite` | 72 | 503 |
| `philo_terminale_tc` | 75 | 503 |

Médiane : ~40 chunks. Le pipeline rerank jusqu'à `CHANNEL_LIMIT = 50`.

## Correction d'une dette antérieure

La dette n°26 affirmait que le point à 50 candidats était **extrapolé et non
observé**, et que la collection interrogée ne portant que 18 chunks, le
reranking réel en traitait au plus 18.

**Les deux moitiés étaient fausses.** La collection à 18 chunks était la plus
petite des dix-huit, pas un cas représentatif : la médiane est à 40, et six
collections dépassent 55. Le point à 50 est aujourd'hui **observé**, et c'est
lui qui met le service hors budget.

L'erreur venait d'avoir généralisé depuis une seule collection sans vérifier sa
représentativité — un contrôle exercé sur un échantillon, présenté comme valant
pour son périmètre.

**Conséquence de requalification : la n°26 n'est pas un risque de latence, c'est
une panne de service.** Elle passe en priorité bloquante.

## Le gain disponible, mesuré

Reranking de 50 paires, même modèle, même machine :

| Configuration | 20 paires | 40 paires | 50 paires | vs actuel |
|---|---|---|---|---|
| **Conteneur actuel** (2 CPU, 8 threads) | — | — | **5 597 ms** | référence |
| CPU 4 threads | 850 ms | 1 582 ms | 2 045 ms | **2,7×** |
| CPU 8 threads | 549 ms | 1 164 ms | **1 438 ms** | **3,9×** |
| CPU 16 threads | 1 123 ms | 2 240 ms | 2 533 ms | 2,2× |
| **GPU GTX 1650** | 106 ms | 209 ms | **265 ms** | **21×** |

Deux enseignements :

- **16 threads sont plus lents que 8.** Le poste porte six piles Docker et une
  charge moyenne de 3,5 à 5,4 ; au-delà de 8 fils, la contention l'emporte sur le
  parallélisme. Plus de cœurs n'est pas mieux, et ce n'était pas prévisible sans
  mesure.
- **Un GPU est présent sur cette machine et n'est pas utilisé.** `torch.cuda`
  répond `False` dans le conteneur. L'ingestion du 28/08 avait tourné avec
  `CUDA_VISIBLE_DEVICES=""` — délibérément, mais rien n'a été rouvert depuis.

## Chemin le plus court vers le service

Par ordre de coût croissant, **aucun n'affaiblit un contrôle** :

1. **Porter le conteneur de 2 à 8 CPU** (`cpus: 8` dans le compose) et aligner
   `torch.set_num_threads(8)`. Attendu : rerank 50 paires à ~1,4 s, requête
   complète à ~2,1 s contre un budget de 6 s. **Marge ×2,8.** Coût : une ligne
   de configuration et un redémarrage du conteneur.
2. **Exposer le GPU au conteneur.** Attendu : ~265 ms de rerank. Coût : `runtime:
   nvidia` et le toolkit conteneur, plus une vérification que le modèle scellé
   se charge à l'identique.
3. Réduire `CHANNEL_LIMIT` ou le nombre de candidats rerankés — **écarté** : ce
   serait affaiblir un contrôle de qualité pour tenir un budget, alors que deux
   corrections de configuration suffisent.

**La 1 est proposée comme geste de mise en service.** Elle n'est pas appliquée
ici : elle modifie le runtime, et la fenêtre appartient à l'opérateur.

## Ce que ce tir n'établit pas

- **Aucune courbe de concurrence n'a pu être tracée.** Mesurer la concurrence
  d'un service qui échoue à concurrence 1 produirait des chiffres sur des refus.
  La courbe reste due, **après** correction de l'allocation CPU.
- Le point de rupture en concurrence est donc toujours **inconnu**.
- Les mesures portent sur un poste chargé (six piles Docker, charge 3,5–5,4).
  Un serveur dédié donnerait d'autres chiffres — vraisemblablement meilleurs,
  mais ce n'est pas mesuré.

## Un obstacle distinct, rencontré en chemin

Les 18 collections sont en `visibility: internal`. Or `allowed_visibilities_for_role`
n'accorde `internal` qu'aux rôles `teacher`, `admin`, `reviewer` et
`ingest_agent` — **jamais à `student`**.

**Aucun profil élève ne peut interroger le corpus en l'état.** Tous les tirs de
ce rapport ont dû être effectués sous le rôle `teacher`. Ce n'est pas un défaut
de mesure : c'est un manque fonctionnel pour une plateforme destinée aux élèves,
et il doit être tranché — soit les collections passent en `public`, soit le rôle
`student` obtient `internal`. Les deux touchent la gouvernance et **ne sont pas
faits ici**.
