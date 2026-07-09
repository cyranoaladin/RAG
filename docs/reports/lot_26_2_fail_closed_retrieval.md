# LOT 26.2 — Fail-closed retrieval v2

**Date** : 2026-07-09
**Issue pilotage** : #47
**Branche** : `codex/lot26-2-fail-closed-retrieval`
**Statut** : prêt à revue

---

## Objectif du lot

Garantir que `/search/v2` ne puisse jamais exposer de chunk non `reviewed` côté parcours étudiant/public.

## Travaux réalisés

- Mise à jour de [services/rag-engine/src/ingestor/retrieval_v2_endpoint.py](../services/rag-engine/src/ingestor/retrieval_v2_endpoint.py) :
  - filtrage DB strict sur `review_status = 'reviewed'` pour le pipeline de /search/v2 (suppression de l’inclusion `needs_review`)
  - garde-fou cache : refus d’utiliser un cache partiellement non-review (s’il contient des entrées hors `reviewed`, recomputation DB)
  - mêmes filtres sur le warmup de cache pour éviter toute pré-chauffe avec statut non review.

## Tests de non-régression ajoutés

- [services/rag-engine/tests/test_retrieval_v2_endpoint.py](../services/rag-engine/tests/test_retrieval_v2_endpoint.py)
  - vérification de la clause SQL fail-closed `review_status = 'reviewed'`.
- [services/rag-engine/tests/test_review_visibility.py](../services/rag-engine/tests/test_review_visibility.py)
  - `test_search_v2_source_filters_reviewed_only` : source SQL sans `needs_review`.
  - `test_student_search_does_not_return_non_reviewed` : `/search/v2` retourne uniquement un chunk `reviewed`.
  - `test_search_v2_cache_stale_status_is_not_returned` : un statut stale en cache (`needs_review`) ne peut pas être réinjecté.

## Contraintes respectées

- Pas d’ingestion modifiée.
- Pas de workflow review modifié.
- Pas de sécurité/rôles modifiés.
- Pas de cockpit modifié.
- Pas de production touchée.

## Prochaine étape

LOT 26.2 est strictement en vue fail-closed retrieval; lots suivants restent découpés.
