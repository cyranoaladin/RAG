# Lot — reviews GitHub non soumises

Date UTC : 2026-10-10. Base : `origin/main=8b82b7c233a42762becf8080423e52efa844a635`.

Le vérificateur canonique échouait sur la PR #294 avant de pouvoir évaluer son challenge : GitHub renvoie deux reviews `PENDING` avec `submitted_at=null`. Une review non soumise ne peut ni approuver ni révoquer une approbation. Le parseur ignore uniquement ce cas précis après avoir validé son état, son identifiant et son SHA de commit. Les reviews soumises conservent l'exigence d'une date UTC canonique ; une `APPROVED` sans date reste une erreur. L'algorithme de challenge, les droits du reviewer, le HEAD exact et les autres gardes ne changent pas.

TDD : deux cas `PENDING` sans date ont d'abord échoué, puis réussi après le correctif. Un troisième cas confirme qu'une `APPROVED` sans date est refusée. Les 27 tests des modules `trusted_human_review` et adaptateur GitHub passent en venv isolé ; Ruff et `git diff --check` passent. Un contrôle live de #294 a retourné `pull_request_is_draft` au lieu d'une erreur de parsing ; une répétition ultérieure a été interrompue par une indisponibilité de `api.github.com`. Aucun statut de review ni scope n'est modifié par cette PR.
