# ADR-0009 — Canal ressources curées

- **Statut** : Accepté
- **Date** : 2026-06-27
- **Décideur** : Alaeddine Ben Rhouma (Shark)

## Contexte

Les sources encyclopédiques (Wikipedia/Wikiversité) couvrent bien les matières STEM (100%) mais pas les sujets spécifiques au système français (examen, orientation : 13%). Un canal de ressources curées (fournies par l'enseignant) est nécessaire pour compléter le corpus.

## Décision

- `curated_ingestion_allowed: false` — verrou posé, porte existante mais non alimentée.
- Le canal `curated_resources` est déclaré dans `source_admission_policy.yml` avec `admission_decision: require_human_review`.
- Aucune ressource n'est alimentée dans ce lot. Le remplissage viendra par une interface dédiée (lot ultérieur).
- La levée du verrou nécessitera un ADR dédié.

## Conséquences

- Le squelette de couverture rend VISIBLE les programmes sans source (0% remplissage).
- La porte est posée pour le futur canal curé sans modifier l'architecture existante.
