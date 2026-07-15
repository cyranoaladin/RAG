# LOT 27 P3 — hotfix des P2 de revue après merge prématuré

## Contexte

La PR #59 a été fusionnée par le commit
`dbdf6ec60fe345cba03ac7b2b48401a2e07e4704` alors que deux threads P2 Codex
restaient ouverts. La production n'a pas été touchée. Le déploiement reste
gelé jusqu'à la fusion de la PR de hotfix.

## Corrections

- **P2-01 — runner E2E** : le runner résout désormais Playwright depuis son
  propre répertoire `scripts/e2e` et ajoute son `node_modules` à
  `NODE_PATH` lorsqu'il est présent. Le repli vers le worktree principal est
  conservé.
- **P2-02 — statut API** : la sidebar affiche toujours le libellé neutre
  `Backend RAG v2`. Elle n'affiche `API connectée` qu'après un appel
  `/health` réussi ; sinon elle affiche `API non joignable`.

## Invariants

- Aucun changement du contrat backend, de la base de données, de Nginx, DNS
  ou firewall.
- Aucune ingestion, aucune opération Docker et aucun déploiement.
- Aucun secret n'est ajouté au dépôt.

## Validation exécutée

| Commande / contrôle | Résultat |
|---|---|
| Tests ciblés `test_e2e_runner_contract.py` et `test_ui_app_v2_admin.py` | OK — 10 passés après un cycle RED/GREEN |
| `make lint` | OK |
| `make typecheck` | OK |
| `make test` | OK |
| `bash scripts/check-governance-locks.sh` | OK |
| `bash scripts/tests/test-governance-locks.sh` | OK |
| `git diff --check` | OK |
| `node --check scripts/e2e/lot27-p3-ui-readonly.js` | OK |
| `bash -n scripts/e2e/run-lot27-p3-ui-readonly.sh` | OK |
| E2E public `current-prod` read-only | OK — 4 captures, 0 échec réseau bloquant, 0 avertissement réseau |

Artefacts E2E : `/tmp/rag-lot27-hotfix-current-prod-e2e-20260715T105946Z/`.
Les 8 événements Streamlit et 71 requêtes Segment bloquées sont classés
non bloquants par le runner ; aucune requête RAG interdite n'est signalée.

Le mode `p3-preview` n'est pas exécuté : aucun service preview local
authentifié avec un token non journalisé n'est configuré, et le gel interdit
toute préparation sur le serveur.

## Décision

La production reste inchangée et le déploiement demeure gelé jusqu'au merge
de la PR de hotfix.
