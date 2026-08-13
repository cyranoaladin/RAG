# LOT H2-B — Acceptation d'ADR-0036 (changement documentaire uniquement)

## Verdict

Changement purement documentaire : `Statut: Proposé` → `Statut: Accepté`,
avec une section « Preuve d'acceptation » nouvelle. **Aucun code, aucune
migration, aucun Compose, aucun worker, aucune configuration de
gouvernance n'est touché.** `GO_LIVE_READY` reste `false`. Aucune mutation
live.

## Pourquoi maintenant

ADR-0036 (« chaîne de promotion gouvernée ») a été introduit par **PR #95**
— la même PR qui a introduit ADR-0035, déjà accepté séparément
(`docs/reports/lot_h2b_accept_adr_0035.md`, commit `35ec35e`). Les deux
documents partagent donc, par construction, exactement la même review
humaine d'implémentation : aucune autre PR ne touche jamais
`docs/adr/ADR-0036-chaine-de-promotion-gouvernee.md`
(`git log --all --oneline -- <fichier>` : seuls les commits de la branche
de PR #95 apparaissent).

Une instruction humaine a explicitement demandé de ne **pas** supposer
que PR #95 (ni PR #102) est la PR d'implémentation sans preuve — l'audit
ci-dessous établit ce fait depuis l'historique Git et l'API GitHub, pas
depuis un raisonnement par analogie avec ADR-0035.

## Preuve vérifiée en direct (pas déduite d'un texte historique, pas réutilisée sans revérification)

```
ADR0036_IMPLEMENTATION_PR=95
ADR0036_IMPLEMENTATION_HEAD=3d0cf47133dfdba488890a9be3e6fe1fc83bd863
ADR0036_APPROVED_REVIEW_FOUND=true
ADR0036_REVIEWER=abenrhouma
ADR0036_REVIEW_COMMIT_MATCH=true
ADR0036_TRUSTED_CHALLENGE_VALID=true
ADR0036_TRUSTED_WORKFLOW_SUCCESS=true
ADR0036_ACCEPTANCE_CONDITION_SATISFIED=true
```

- **Aucune autre PR ne touche jamais ce fichier** :
  `git log --all --oneline -- docs/adr/ADR-0036-chaine-de-promotion-
  gouvernee.md` ne retourne que des commits appartenant à la branche de
  PR #95 (`2182339` sur `main`, plus les commits pré-squash `98b8832`/
  `534b8d7`/`4563e2c` de cette même branche).
- Review GitHub `id=4923100913`, `state=APPROVED`, `commit_id` identique
  au head réel de PR #95 (`3d0cf471...`, confirmé par
  `gh pr view 95 --json headRefOid,mergeCommit,mergedAt`), soumise
  `2026-08-13T03:22:26Z`. Reconfirmée **fraîchement** pour ce lot (pas
  réutilisée depuis l'acceptation d'ADR-0035 sans revérification) via
  `gh api repos/cyranoaladin/RAG/pulls/95/reviews --paginate`.
- Challenge `NEXUS-TRUSTED-REVIEW-V1:ab4e17ab79bb118ab4661cadef9f48820a02d5c9bf3c30baa9b003d07f785fff`
  revérifié contre le run GitHub Actions réel (`31663947902`,
  `conclusion=success`, reconfirmé pour ce lot).
- Aucune review `DISMISSED`/`CHANGES_REQUESTED` d'`abenrhouma` après cette
  approbation (reconfirmé fraîchement) — les deux seules `DISMISSED`
  portent sur des heads antérieurs du 2026-08-10.
- PR #95 mergée 13 minutes après approbation, sans review intermédiaire.

## Ce que ce lot n'affirme pas

- N'active, ne débloque, ni ne fabrique aucune autorité opérationnelle.
- Ne signifie pas que la chaîne de promotion qu'ADR-0036 décrit est
  entièrement construite. Elle continue d'être bâtie incrémentalement :
  manifeste de readiness (PR #95/#97), liaison de revue scellée (PR #99),
  provenance d'image de production (PR #102, mergée
  `a81ca0669022930dad035dcf105e26e9128df509`) — chacun un lot séparé,
  gouverné indépendamment. Restent notamment non construits : Environment
  GitHub protégé, compte `nexus-deployer`, wrapper de déploiement hôte
  (`DEPLOY_WRAPPER_IMAGE_VERIFICATION=false`), rotation des clés,
  transparence des manifestes émis.
- N'accepte aucun autre document — seul le statut textuel d'ADR-0036 est
  modifié.

## Précédent suivi

Même mécanisme qu'ADR-0031 (commit `8c95114`) et qu'ADR-0035
(`docs/reports/lot_h2b_accept_adr_0035.md`) : un lot documentaire séparé
et minimal, jamais fusionné dans la PR d'implémentation elle-même, avec
une section « Preuve d'acceptation » enregistrant la chaîne de preuve
vérifiable.

## Preuves

```
$ git diff --check
(rien)

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source docs/adr/ADR-0036-chaine-de-promotion-gouvernee.md --no-git
no leaks found
```

Aucun test de code n'est concerné (fichier Markdown uniquement, aucun
import, aucune logique).
