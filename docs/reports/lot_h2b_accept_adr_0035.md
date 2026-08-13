# LOT H2-B — Acceptation d'ADR-0035 (changement documentaire uniquement)

## Verdict

Changement purement documentaire : `Statut: Proposé` → `Statut: Accepté`,
avec une section « Preuve d'acceptation » nouvelle. **Aucun code, aucune
migration, aucun Compose, aucun worker, aucune configuration de
gouvernance n'est touché.** `GO_LIVE_READY` reste `false`. Aucune mutation
live.

## Pourquoi maintenant

En corrigeant une erreur de vérification dans le rapport de PR #99
(`docs/reports/lot_h2b_review_binding_trust_anchor.md`), j'ai découvert que
ma vérification initiale de `gh api repos/cyranoaladin/RAG/pulls/95/reviews`
n'utilisait pas `--paginate` — cet appel tronque silencieusement à 30
résultats sur les 45 réels. Les deux reviews `APPROVED` de PR #95
(dont l'approbation finale, avec challenge trusted-review valide) tombaient
au-delà de cette troncature.

PR #95 est la PR qui introduit à la fois `docs/adr/ADR-0035-...md`
lui-même et le code qui implémente son mécanisme
(`packages/contracts/src/nexus_contracts/review_binding.py`) — aucune
autre PR ne touche ce fichier ADR (`git log` le confirme). C'est donc bien
« la PR d'implémentation » que le texte de l'ADR désigne.

## Preuve vérifiée en direct (pas déduite d'un texte historique)

```
ADR0035_IMPLEMENTATION_PR=95
ADR0035_REQUIRED_HEAD=3d0cf47133dfdba488890a9be3e6fe1fc83bd863
ADR0035_APPROVED_REVIEW_FOUND=true
ADR0035_REVIEWER=abenrhouma
ADR0035_REVIEW_COMMIT_ID=3d0cf47133dfdba488890a9be3e6fe1fc83bd863
ADR0035_TRUSTED_CHALLENGE_VALID=true
ADR0035_ACCEPTANCE_CONDITION_SATISFIED=true
```

- Review GitHub `id=4923100913`, `state=APPROVED`, `commit_id` identique au
  head réel de PR #95 (confirmé séparément via `gh pr view 95 --json
  headRefOid`), soumise `2026-08-13T03:22:26Z`.
- Challenge `NEXUS-TRUSTED-REVIEW-V1:ab4e17ab79bb118ab4661cadef9f48820a02d5c9bf3c30baa9b003d07f785fff`
  — non pris au mot : recoupé contre le run GitHub Actions réel qui l'a
  évalué (`31663947902`, job `94334449566`, `conclusion=success`), dont le
  log publie la décision machine complète (`approved: true`, mêmes head/
  base/challenge/reviewer/review_id/submitted_at).
- Aucune review `DISMISSED`/`CHANGES_REQUESTED` d'`@abenrhouma` après cette
  approbation (les deux seules `DISMISSED` du même reviewer portent sur des
  heads antérieurs du 2026-08-10).
- PR #95 mergée 13 minutes après, sans review intermédiaire
  (`merged_at: 2026-08-13T03:35:10Z`, commit `2182339fb9a0df49419370e5ead8b92ef4d62305`).

## Précédent suivi

Même mécanisme qu'ADR-0031 (commit `8c95114`, « accept ADR-0031 after
governed PR #90 review ») : un lot documentaire séparé et minimal, jamais
fusionné dans la PR d'implémentation elle-même, avec une section « Preuve
d'acceptation » enregistrant la chaîne de preuve vérifiable.

## Ce que ce lot n'affirme pas

- Aucune autorisation de publication de contenu réel. Aucun reçu de
  review-binding (`SignedScopeAuthorizationReviewBinding`) n'a été émis à
  ce jour pour aucune autorisation — LOT41A/LOT42 restent gouvernés
  séparément et indépendamment de ce changement documentaire.
- N'active, ne débloque, ni ne fabrique aucune autorité opérationnelle.

## Preuves

```
$ git diff --check
(rien)

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md --no-git
no leaks found
```

Aucun test de code n'est concerné (fichier Markdown uniquement, aucun
import, aucune logique).
