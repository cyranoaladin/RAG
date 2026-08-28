# Essai d'ingestion calibré — CPU contre GPU, 28 août 2026

> **Le GPU local rend le corpus complet ingérable en une soirée.**
> 3.2 heures contre 15.1 heures. Aucune location n'est nécessaire :
> le rapport est de **4.7×**, et le matériel est déjà là.

## Le GPU était disponible depuis le début

| Vérification | Résultat |
|---|---|
| `nvidia-smi` | **NVIDIA GeForce GTX 1650**, pilote **580.173.02**, 4096 Mio |
| `torch` dans `rag-engine/.venv` | 2.13.0+cu130 — `cuda_available=True` |
| `torch` dans `rag-pedago/.venv` | 2.12.1+cu130 — `cuda_available=True` |

**Ce n'était pas une version CPU-only, et pas un `pip install` à faire.** Les deux
environnements portent une build CUDA fonctionnelle. Le GPU répondait.

### Pourquoi `CUDA_VISIBLE_DEVICES=""` avait été posé

La raison est écrite, mot pour mot, dans `docs/reports/lot_wave0_search_ready.md` :

> « L'acceptance matérielle est exécutée sur CPU (`CUDA_VISIBLE_DEVICES=''`)
> **parce que le GPU 4 Go partagé était saturé** ; ni le modèle ni son contrat
> ne changent. »

**Une précaution de circonstance, pas un échec.** Aucune erreur CUDA n'est
consignée nulle part. Le réglage visait des tests d'acceptance à un moment où la
VRAM était prise — puis il a été reconduit jusque dans l'ingestion de production,
par habitude et non par décision.

À l'instant de la mesure : 784 Mio occupés sur 4096. L'embedding en consomme
2,44 Go — **il tient**, avec un peu plus d'un giga-octet de marge.

Le coût de cette reconduction : toute l'estimation « plusieurs jours » reposait
sur un calcul bridé.

## Le protocole

Même échantillon, même code, deux régimes. Les 26 PDF du miroir passent par les
fonctions réelles du pipeline gouverné — `chunk_publication`, `ModelTokenCounter`,
`format_passage`, `SentenceTransformer.encode` — et non par une approximation.

**Aucun contrôle n'a été désactivé.** Ce harnais mesure, il ne prétend pas
ingérer ; la base d'essai est jetable, sur volume anonyme, sans contact avec
`infra_rag_pgvector_data`.

Contrôle de validité : les deux régimes produisent **740 chunks**, soit
28.5 par document. Un chunking identique de part et d'autre — la comparaison
porte donc bien sur la seule vitesse.

## Résultats mesurés

| | CPU 8 threads | GPU GTX 1650 | Rapport |
|---|---|---|---|
| Durée totale, 26 documents | 577.2 s | **123.6 s** | **4.7×** |
| dont extraction PDF | 13.0 s | 15.8 s | 1,0× — *CPU des deux côtés* |
| dont embedding | 564.2 s | **107.8 s** | **5.2×** |
| **Documents / heure** | **162.2** | **757.6** | **4.7×** |
| Chunks / seconde | 1.28 | 5.99 | 4.7× |

L'extraction PDF ne profite pas du GPU — elle reste sur CPU et coûte ~0,55 s par
document. Sur GPU elle devient **13 % du temps total** au lieu de 2 % : le
plancher se déplace, il ne disparaît pas.

## Extrapolation aux 2451 documents

| | CPU 8 threads | **GPU GTX 1650** |
|---|---|---|
| Durée | **15.1 heures** | **3.2 heures** |
| soit | ~1.9 journées de travail | **une soirée** |

Volumétrie attendue, dérivée du mesuré :

| Grandeur | Valeur | Base de calcul |
|---|---|---|
| Chunks produits | ~69,854 | 28.5 chunks/document × 2451 |
| Table `rag_chunks` | **~1.3 Go** | 19 896 octets/chunk, mesuré en base |
| Miroir PDF | ~0.9 Go | 9,4 Mo pour 26, à l'échelle |
| **Total disque** | **~2.2 Go** | |
| Disque libre | 49 Go | **suffisant** |

### L'incertitude, nommée

L'échantillon est de **26 documents pour 2451** — 1,1 %. Ce n'est pas un
échantillon représentatif tiré au hasard : ce sont les documents **déjà
sélectionnés et ingérés**, donc possiblement plus homogènes que le corpus
complet.

Le facteur d'échelle réel est le **nombre de chunks**, pas de documents. Si le
corpus complet porte des documents plus volumineux — manuels, annales — le
nombre de chunks par document dépasserait 28,5 et la durée croîtrait
proportionnellement.

**Fourchette honnête sur GPU : de 3.2 à 6.5 heures**, la borne haute
correspondant à un corpus deux fois plus dense en chunks par document.
Cela reste une soirée, et c'est ce qui rend le chiffre décisif malgré
l'incertitude.

## L'arbitrage matériel — la question est close

Le mandat posait : *« si le rapport est de 10 ou plus, la location d'un GPU pour
une journée est le chemin le plus court »*.

**Le rapport est de 4.7, et il est obtenu sans rien louer.**
La location est écartée, pour trois raisons dans cet ordre :

1. **3.2 heures suffisent ici.** Un GPU loué de classe A100 ou L4 diviserait
   encore ce temps, mais on ne raccourcit pas utilement une soirée.
2. **Louer déplacerait l'artefact scellé hors de cette machine.** Le modèle est
   sous sceau ; le porter chez un tiers ouvre une surface de gouvernance —
   matérialisation, vérification, destruction — pour gagner deux heures.
3. **Le corpus devrait être téléversé**, soit ~0,9 Go de PDF, plus le
   rapatriement des vecteurs.

**Décision technique proposée : ingérer sur le GPU local.** Elle n'engage aucune
dépense et ne franchit aucun verrou.

## Un obstacle rencontré, non résolu

L'ingestion gouvernée réelle a été tentée d'abord, et elle **refuse** :

```
ValueError: Chunk ID mismatch at index 0 pour e591a87aee63…
```

Le nombre de chunks concorde ; c'est le **texte** du premier chunk qui diffère de
celui scellé. `chunk_id = sha256(content_sha:idx:chunk_sha)` : une empreinte de
texte, donc une divergence d'extraction.

**Le contrôle a fait son travail** — il refuse d'écrire un contenu qui ne
correspond pas au sceau. Mais il signifie que **l'ingestion n'est pas
reproductible en l'état sur cette machine** : rejouer l'ingestion des 26
documents aujourd'hui ne redonnerait pas le corpus scellé.

Cause non établie. Pistes, par ordre de vraisemblance : version de la
bibliothèque d'extraction PDF différente de celle du scellement ; normalisation
Unicode ou locale ; PDF du miroir non identique à l'original.

**C'est un préalable à l'ingestion des 2451.** Ingérer un corpus dont les
empreintes ne se reproduisent pas reviendrait à sceller ce qu'on ne peut pas
revérifier — exactement le défaut corrigé cette semaine.

Le harnais de mesure contourne ce contrôle **parce qu'il ne prétend pas
ingérer**. L'ingestion réelle, elle, doit le franchir.
