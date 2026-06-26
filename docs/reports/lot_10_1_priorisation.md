# Rapport — Lot 10.1 : Priorisation réelle + exécution pilote

## Branchement correspondance BO

`SubjectAgent` charge la correspondance BO via `_load_correspondence()` :
- Cherche un PDF programme dans `data/staging/programmes/`
- Exécute `build_correspondence_report` pour obtenir le statut par notion
- Retourne `None` si aucun programme disponible (repli `no_correspondence`)

## Priorisation

`plan()` trie les notions par priorité :
1. `bo_not_found` (notions absentes du BO → à acquérir en priorité)
2. `bo_partial` (partiellement trouvées → à vérifier)
3. `no_correspondence` (pas de programme officiel disponible → ordre taxonomie)
4. `bo_found` (déjà couvertes par le BO → basse priorité)

`fetch()` consomme les notions dans cet ordre.

## Tests (5/5 PASS)

- `test_priorisation_orders_bo_not_found_first` : mock correspondance → notion_b (not_found) avant notion_c (partial) avant notion_a (found_exact)
- `test_no_correspondence_preserves_taxonomy_order` : sans correspondance → ordre taxonomie conservé, all `no_correspondence`

## Exécution pilote réelle

Orchestrateur lancé sur terminale (6 matières, max 2 notions/matière) :
- 12 notions traitées, 2 trouvées (NSI: listes, piles)
- Correspondance BO non disponible pour terminale (PDFs 404)
- Rapport hiérarchique versionné dans `data/acquisition/couverture_lot10.md`

## Docstrings vérifiées

Toutes les docstrings des agents décrivent fidèlement le comportement implémenté. Le SubjectAgent mentionne la priorisation qui est maintenant effective.

## CI locale : 7/7 PASS, garde-fou 17/17, ingestion_allowed=false
