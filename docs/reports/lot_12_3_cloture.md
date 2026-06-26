# Rapport — Lot 12.3 : Clôture chunking

## A2bis — Test collision multi-niveaux

Test `test_multi_niveau_no_collision` : deux staging files (premiere + terminale, même matiere/notion) → deux fichiers JSONL distincts sous `data/chunks/{niveau}/`, doc_id et chunk_id différents. Pas d'écrasement.

## B7 — bo_only nettoyé

- Stop-list structurelle (DETTE-9.1-B résolue) : Annexe, Sommaire, Préambule, Programme, Contenus, Capacités attendues, Démonstrations, etc.
- Filtre artefacts PDF : mots mono-token avec digits rejetés (Csinab2 éliminé)
- Titres tronqués filtrés par la stop-list
- `bo_only` maths seconde : 20 → 6 (restant = vrais sujets mathématiques)

## B5 — Test pollution-au-milieu

Test `test_pollution_detected_in_middle` : texte propre en tête/queue avec chrome au milieu ("modifier le code", "Aller au contenu") → `navigation_suspected=True`.

## C — Cosmétique

- `subject_agent.report()` : `ACCEPTED_STATUSES` au lieu de hardcoded tuple
- DETTE-11.1-A déplacée dans section Parsing/gating
- DETTE-12-A (exposants) et VIGILANCE-RETRIEVAL (statut_enseignement) inscrites au BACKLOG
- DETTE-9.1-B marquée résolue
- `_nsi_structure_titles` : utilisé en fallback (grep confirme l'appel ligne 141), documenté

## Confirmation

- `model_validate` : 124/124 ChunkMeta + 16/16 ChunkMetadata (inchangé)
- Full-text 0 pollution (inchangé)
- CI locale : 7/7 PASS ; gouvernance 17/17 ; embeddings/qdrant/ingestion = false

## Chunking clos et mergeable
