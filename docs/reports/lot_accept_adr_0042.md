# LOT — Acceptation d'ADR-0042 (changement documentaire uniquement)

## Verdict

Changement purement documentaire : `Statut: Proposé` → `Statut: Accepté`,
avec une section « Preuve d'acceptation » nouvelle. **Aucun code, aucune
migration, aucun Compose, aucun worker, aucune configuration de
gouvernance n'est touché.** `GO_LIVE_READY` reste `false`. Aucune mutation
live.

## Pourquoi maintenant

ADR-0042 (« Preuve H2 machine-lisible et registre de révocation
partagés ») a été introduit par **PR #104**, mergée le 2026-08-14
(commit `c2cf3bd86199452483adcada29ed9eb11649732b`) après cinq rounds de
revue Codex, chacun vérifié contre le producteur réel
(`h2b_coverage_report.py`) avant correction — voir
`docs/reports/lot_h2_coverage_evidence_contract.md` pour le détail
complet des cinq rounds.

`git log --all` sur un clone local ne prouve rien d'autoritaire — il ne
voit que les refs déjà récupérées localement, jamais l'historique
serveur complet (constat déjà établi et corrigé pour l'acceptation
d'ADR-0036, PR #103). La preuve retenue ici est l'historique de chemin
côté serveur GitHub, paginé :

```
$ gh api "repos/cyranoaladin/RAG/commits?path=docs/adr/ADR-0042-preuve-h2-machine-lisible-et-registre-de-revocation-partage.md&per_page=100" \
    --paginate -i | grep -i '^link:\|^HTTP'
HTTP/2.0 200 OK
# aucun en-tête Link — une seule page, rien de manqué (même méthode que PR #103)

$ gh api ".../commits?path=...&per_page=100" --paginate --jq '.[] | {sha, message: (.commit.message | split("\n")[0])}'
{"message":"feat(contracts): add H2 coverage evidence and shared revocation registry (ADR-0042) (#104)","sha":"c2cf3bd86199452483adcada29ed9eb11649732b"}
```

Un seul commit touche jamais ce fichier sur `main` : le squash-merge de
PR #104. PR #106 (documentaire, cette acceptation elle-même) est
explicitement exclue de cette preuve — elle n'apparaît pas dans
l'historique de `main` tant qu'elle n'est pas mergée, et ne doit jamais
y être comptée comme une seconde implémentation. PR #104 est donc, sans
ambiguïté, la seule PR d'implémentation possible pour cette acceptation.

```
ADR0042_IMPLEMENTATION_PR=104
ADR0042_IMPLEMENTATION_HEAD=5e3095376730595bc339fada4033f4537f519b76
ADR0042_APPROVED_REVIEW=4936762551
ADR0042_TRUSTED_WORKFLOW=31797022943
ADR0042_ACCEPTANCE_CONDITION_SATISFIED=true
```

## Preuve d'acceptation — faits vérifiés en direct

1. **HEAD exact approuvé** : `5e3095376730595bc339fada4033f4537f519b76`
   — l'état de PR #104 immédiatement avant merge.
2. **Review humaine** : `@abenrhouma`, `review_id=4936762551`,
   `state=APPROVED`, `commit_id=5e3095376730595bc339fada4033f4537f519b76`,
   soumise `2026-08-14T11:37:33Z`, corps de review portant exactement le
   challenge `NEXUS-TRUSTED-REVIEW-V1:c02da391865b2dff0e514e7fa274fbdae6e1ef65c185c73f31e70441b1590414`.
3. **Revérifié par le workflow réel** : run GitHub Actions
   `31797022943` (`trusted-human-review.yml`), `conclusion: success`,
   décision republiée `{"approved": true, "reason": "approved",
   "review_id": 4936762551, "reviewer": "abenrhouma", "head_sha":
   "5e3095376730595bc339fada4033f4537f519b76"}`.
4. **Historique complet des reviews audité** (6 au total, appel API
   unique suffisant — aucun en-tête `Link` renvoyé, donc pas de
   pagination manquée) : les 4 autres reviews sont des commentaires
   `chatgpt-codex-connector[bot]` (`state=COMMENTED`), jamais des
   décisions humaines. Aucune review `DISMISSED` ni `CHANGES_REQUESTED`
   n'existe. Une première approbation humaine (`id=4933937961`,
   `2026-08-14T04:17:37Z`, corps `"ok"`) existait sur le même commit mais
   sans le challenge requis par le protocole `/nexus-trusted-review` —
   insuffisante, explicitement remplacée par la review `id=4936762551`
   avant toute décision d'acceptation ; documenté ici pour que
   l'historique ne prête pas à confusion.
5. **Merge** : `merged_at: 2026-08-14T11:39:34Z`, commit
   `c2cf3bd86199452483adcada29ed9eb11649732b` sur `main`, moins de deux
   minutes après l'approbation valide, sans review intermédiaire.

## Ce que cette acceptation ne fait pas

- N'intègre pas les deux contrats (`h2_coverage_evidence`,
  `authorization_revocations`) dans le signer PR #100 — lot séparé,
  toujours en attente.
- N'autorise aucun contenu, ne signe aucun manifeste, ne modifie aucun
  calcul métier existant (ADR-0001 respecté — confirmé, aucun changement
  de code dans ce lot).

## Booléens finaux

```
ADR0042_STATUS_ON_MAIN=ACCEPTE
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
