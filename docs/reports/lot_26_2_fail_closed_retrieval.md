# LOT 26.2 — Fail-closed retrieval v2

**Date** : 2026-07-09
**Issue pilotage** : #47
**Branche** : `codex/lot26-2-fail-closed-retrieval`
**Statut** : prêt à revue

---

## Objectif du lot

Garantir que `/search/v2` ne puisse jamais exposer de chunk non `reviewed` côté parcours étudiant/public.

## Travaux réalisés

- Mise à jour de [services/rag-engine/src/ingestor/retrieval_v2_endpoint.py](../../services/rag-engine/src/ingestor/retrieval_v2_endpoint.py) :
  - filtrage SQL strict sur `review_status = 'reviewed'` pour le pipeline de `/search/v2` et le warmup cache.
  - filtrage applicatif post-DB pour rejeter toute ligne non-`reviewed` même en cas de contamination DB :
    - après chaque `cur.fetchall()` via `candidates = _filter_reviewed_candidates(...)`
    - garde dans la boucle `if candidate[8] != "reviewed": continue`
  - `SearchV2Hit.review_status` typé `Literal["reviewed"]`.
  - garde-fou cache : refus d’utiliser un cache contenant des statuts hors `reviewed`.
  - warmup cache : ne met en cache que des hits `reviewed`.

## Tests de non-régression ajoutés

- [services/rag-engine/tests/test_retrieval_v2_endpoint.py](../../services/rag-engine/tests/test_retrieval_v2_endpoint.py)
  - vérification de la clause SQL fail-closed `review_status = 'reviewed'`.
  - validation du type `SearchV2Hit` : refus de `review_status` non `reviewed`.
- [services/rag-engine/tests/test_review_visibility.py](../../services/rag-engine/tests/test_review_visibility.py)
  - `test_search_v2_source_filters_reviewed_only` : source SQL sans `needs_review`.
  - `test_student_search_does_not_return_non_reviewed` : DB mock retourne `reviewed`, `needs_review`, `rejected`, `quarantined` avec scores rerank élevés ; `/search/v2` retourne uniquement le chunk `reviewed`.
  - `test_search_v2_cache_stale_status_is_not_returned` : un cache stale avec statut non `reviewed` déclenche un recompute DB puis retient uniquement `reviewed`.
  - `test_cache_warmup_ignores_non_reviewed_candidates` : warmup ne met pas en cache de chunks non `reviewed`.
  - ajout d’un fixture `clear_cache_between_tests` (`invalidate_cache` avant/après) pour éviter la pollution croisée.

## Contraintes respectées

- Pas d’ingestion modifiée.
- Pas de workflow review modifié.
- Pas de sécurité/rôles modifiés.
- Pas de cockpit modifié.
- Pas de production touchée.

## Prochaine étape

LOT 26.2 est strictement en vue fail-closed retrieval; lots suivants restent découpés.
