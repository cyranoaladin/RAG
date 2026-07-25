# ADR-0015 — Arborescence corpus 3e → Terminale et extension du catalogue de collections

- **Statut** : proposé (LOT 28)
- **Date** : 2026-07-26
- **Contexte** : AUDIT_LOT28_GLOBAL §2.2/§2.3 (E-01, E-02)

## Décision

1. **Arborescence corpus par niveau** (`corpus/`) :
   - `College/Troisieme/` — tronc commun cycle 4 (7 fiches)
   - `Lycee/Seconde/` — tronc commun 2de (10 fiches, SNT incluse)
   - `Lycee/Premiere/{Tronc_commun,Specialites,STMG}/`
   - `Lycee/Terminale/{Tronc_commun,Specialites,STMG}/`
   - `Referentiels/` — examens transversaux (DNB, EAF, bac général, Grand oral, EAM)
   - Les fiches historiques `corpus/Tronc_commun/` et `corpus/Specialites/` sont **conservées** (pas de suppression ; les nouvelles fiches les référencent). Leur consolidation par `git mv` vers la nouvelle arborescence est proposée au lot suivant pour préserver l'historique.
2. **Chaque répertoire porte un `_index.yml`** déclarant le routage déterministe fiche → collection cible → taxonomie. Le routage n'est jamais déduit du contenu (droits par provenance, ADR-0013).
3. **Catalogue de collections v3** : 35 → **59 entrées** (`services/rag-engine/configs/rag_collections.yml`). 24 nouvelles collections : collège complet (SVT, PC, LV, techno 3e), seconde complète (SVT, PC, SES, LV, EMC, EPS), tronc commun 1re/Tle (ES, LV, EMC, EPS), spécialités générales manquantes (HGGSP, LLCE, HLP × 1re/Tle).
4. **39 fichiers taxonomiques** livrés : les 16 référencés mais absents du dépôt (E-01, bloquant) + les taxonomies des 24 nouvelles collections — tous validés contre `TaxonomySpec` (58/60 avec le dépôt ; les 2 échecs sont préexistants : `exams/anticipee_maths.yml` et `exams/bac_general.yml` utilisent un schéma distinct, dette tracée).
5. **Aucune nouvelle collection n'est instanciée** (`instanciee: false`) : l'instanciation suit la Phase B (revue humaine des stagings, vagues progressives). Invariant M-04 préservé.

## Conséquences

- Les agents `LevelAgent` peuvent désormais découvrir une taxonomie pour chaque collection du catalogue (plus d'échec de résolution).
- Le périmètre reste : voie générale + STMG + collège 3e (D-PERIMETRE-EXPLICITE). Autres séries technologiques : convention voie extensible inchangée.
- `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` reste à la racine et est référencé par toutes les fiches.
