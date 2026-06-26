# Rapport — Lot 12.1 : Conformité chunking + purge dettes

## A. Défauts structurants corrigés

### A1. chunk_id / doc_id / chunk_sha256
Chaque chunk porte : `chunk_id` (`{niveau}_{matiere}_{notion}#{index}`), `doc_id` (déterministe), `chunk_sha256` (SHA-256 du texte). Validé : 0 champ manquant sur 124 chunks.

### A2. Collision multi-niveaux
Chemin : `data/chunks/{niveau}/{matiere}_{notion}.jsonl`. Deux niveaux + même notion → deux fichiers distincts.

### A3. Bug `<sup>` corrigé
- `<sup class="reference">` → décomposé (retiré)
- `<sup>2</sup>` → unwrapped (texte "2" conservé)
- 16 notions re-fetchées APRÈS fix, re-chunkées.

## B. Dettes P1/P2 corrigées

| # | Correction |
|---|---|
| B1 | Staging nettoyé même quand aucun résultat accepté (fichiers stale éliminés) |
| B2 | Parsing filename : matières à underscore (histoire_geo, physique_chimie) parsées correctement |
| B3 | YAML malformé → return False (try/except dans les gates) |

## Scan FULL-TEXT pollution

```
FULL-TEXT scan: 124/124 clean
Missing required fields: 0
```

Scan sur le TEXTE ENTIER de chaque chunk (pas une fenêtre), avec 23 marqueurs de pollution indépendants.

## CI locale : 7/7 PASS, garde-fou 17/17
