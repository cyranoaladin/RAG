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

## Codex — deux constats réels, corrigés successivement avant merge

**Round 1 (review sur `3841862`).** `git log --all` sur le clone local ne
prouve rien d'autoritaire — cette commande ne voit que les refs déjà
récupérées localement, et ma première version de ce rapport ne
distinguait pas explicitement la présente PR documentaire (#103, qui
modifie légitimement ce même fichier) d'une éventuelle « autre PR
d'implémentation ». Corrigé par un premier remplacement, interrogeant
GitHub directement : `gh api commits?path=...` (historique serveur sur
`main`) **et** `gh pr list --state all --json files` (toutes les PR, tout
état, filtrées sur ce chemin).

**Round 2 (review sur `56692ac`), constat plus profond et confirmé
empiriquement avant d'être accepté.** Le second des deux remplacements
ci-dessus était lui-même silencieusement incomplet : `gh pr list --json
files` compile sa liste de fichiers via GraphQL avec un fragment
`files(first: 100)` — un plafond dur de 100 fichiers par PR, jamais
paginé par ce flag. PR #95 a réellement changé bien plus de fichiers, il
suffirait qu'un autre PR de plus de 100 fichiers ait cette ADR au-delà
des 100 premiers pour qu'elle disparaisse silencieusement du résultat.
**Vérifié avant de corriger, pas supposé :**

```
$ gh --version
gh version 2.45.0

$ gh pr view 95 --json files --jq '.files | length'
100   # plafonné — PR #95 a en réalité changé bien plus de fichiers

$ GH_DEBUG=api gh pr list --state all --json number,files -S "..." --limit 1
fragment pr on PullRequest{number,files(first: 100) {nodes {...}}}
```

**Correction retenue : abandonner ce second contrôle plutôt que le
réparer, et s'appuyer uniquement sur le premier** (`commits?path=...`),
qui n'est pas affecté par ce plafond — c'est un endpoint REST qui
interroge directement l'historique serveur d'un chemin, sans passer par
une liste de fichiers par PR.

**Round 3 (review sur `e434a13`), sur la justification de cette méthode,
pas sur la méthode elle-même — encore vérifié avant d'être accepté ou
rejeté.** La justification initiale invoquait « ce dépôt fusionne
exclusivement par squash ». Codex a relevé que `2182339` (le commit
cité) serait un commit de merge à deux parents, contredisant cette
affirmation. **Vérifié directement, pas supposé :**

```
$ git rev-list --parents -n 1 2182339fb9a0df49419370e5ead8b92ef4d62305
2182339fb9a0df49419370e5ead8b92ef4d62305 a956441645d48107ab983fad62b80f0848345e81
```

Un seul hash après le commit : **un seul parent**, pas deux — l'affirmation
précise de Codex (« a two parents ») est factuellement fausse, vérifiée en
direct. Vérification symétrique sur le commit de merge de PR #90 cité en
exemple par Codex (`e539dbb71e6710d2b275c268b0d5d22aa7fb8e9a`) : lui aussi
un seul parent. Aucun des deux n'est un commit de merge à deux parents.

**Mais la conclusion plus large de Codex — ne pas fonder la preuve sur une
hypothèse de méthode de fusion — est retenue, car la justification
initiale n'en avait de toute façon pas besoin.** `commits?path=...`
(comme `git log <chemin>`) parcourt le graphe de commits complet
atteignable depuis la pointe de la branche, en remontant tous les
parents — squash, rebase, ou merge à deux parents ne changent rien à
cette exhaustivité : tout commit qui a un jour modifié ce chemin devient
nécessairement un ancêtre de `main`, et apparaît donc dans ce résultat,
quelle que soit la stratégie de fusion utilisée. La preuve ne repose donc
pas sur « ce dépôt fusionne toujours de la même façon » (affirmation
non vérifiée et non nécessaire), mais sur la complétude structurelle du
parcours d'historique par chemin — vraie indépendamment de la stratégie.
Le texte est corrigé pour ne plus invoquer le squash comme justification.

Le champ des PR *non fusionnées* (ouvertes ou fermées sans merge) reste
hors de portée de cette méthode, mais n'est pas pertinent ici : le
mécanisme d'acceptation (précédent ADR-0031/ADR-0035) exige une PR
**mergée** avec review approuvée sur son HEAD exact — une PR jamais
fusionnée ne peut structurellement jamais être « la PR d'implémentation »
au sens de ce mécanisme.

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

- **Aucune autre PR fusionnée ne touche jamais ce fichier** — vérifié via
  l'historique serveur GitHub d'un chemin (`commits?path=...`, non
  plafonné), voir section Codex ci-dessus pour la méthode retenue et
  celle rejetée après vérification empirique.
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
