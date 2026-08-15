# Incident : dérive de challenge NEXUS-TRUSTED-REVIEW-V1 sur PR#108/#112/#113 — 2026-08-15

> Ce rapport est une **nouvelle décision de gouvernance sur l'état courant de `main`**,
> pas une falsification rétroactive de l'historique des reviews GitHub.
> **Cette ratification ne rend PAS rétroactivement valides les reviews originales
> de PR#108, PR#112 et PR#113.**

## 1. Résumé

Le 2026-08-15, quatre PR (#107, #108, #112, #113) ont été rebasées sur `main` en
succession rapide, un challenge `/nexus-trusted-review` a été posté pour chacune,
puis approuvées et mergées dans un intervalle de ~70 minutes (10:15–11:08 UTC).

Pour trois d'entre elles (#108, #112, #113), la PR a reçu une mise à jour
(« Update branch » / merge de `main`) **entre** l'émission du challenge et la
soumission de l'approbation GitHub. Le protocole `NEXUS-TRUSTED-REVIEW-V1` lie le
challenge à un couple exact `(base_sha, head_sha)` : la review soumise portait donc
le challenge calculé pour l'**ancien** couple, alors que le commit réellement
approuvé/mergé (`commit_id` de la review) était le **nouveau** couple. Le workflow
`trusted-human-review.yml` a correctement détecté ce désaccord — les check-runs
`Evaluate trusted human review` et `Evaluate trusted human review (head-pinned)`
affichent `conclusion=failure` sur les quatre commits réellement mergés de #108,
#112, #113.

Le merge a néanmoins abouti car **`Evaluate trusted human review` n'a jamais fait
partie des `required_status_checks` de la protection de branche `main`** — ce
gate n'a donc jamais été appliqué mécaniquement par GitHub ; il n'était vérifié
que manuellement, et cette vérification manuelle a été insuffisamment refaite
après les notifications d'approbation de l'opérateur pour #108/#112/#113.

## 2. Timeline (UTC, 2026-08-15)

| Heure | Événement |
|---|---|
| 09:54–09:56 | Rebase de #107/#108/#112/#113 sur `main` (tip `3308fcf`, après merge de PR#115) ; runs `pull_request_target` automatiques (non déclencheurs du challenge remis à l'opérateur). |
| 10:05:29–10:05:32 | Commentaires `/nexus-trusted-review` postés explicitement sur les quatre PR ; challenges calculés et communiqués à l'opérateur pour #107 (`d8cdb59`), #108 (`dad6d30`), #112 (`17fde45`), #113 (`6850d93`) — base commune `3308fcf`. |
| 10:15:13 | Review APPROVED sur #107, `commit_id=d8cdb59` — identique au head challengé. |
| 10:15:21 | PR#107 mergée (`439255f`). `main` avance. |
| 10:15:51 | Review APPROVED sur #108, `commit_id=21d4e9b` — le head de #108 avait déjà bougé (merge de `main`/#107) depuis le challenge posté pour `dad6d30`. |
| 10:31:15 | PR#108 mergée (`5f44a46`). `main` avance. |
| 10:33:22 | Review APPROVED sur #112, `commit_id=6518688` — head déjà avancé depuis le challenge posté pour `17fde45`. |
| 10:45:43 | PR#112 mergée (`c2c08dd`). `main` avance. |
| 11:07:19 | Review APPROVED sur #113, `commit_id=9db3918` — head déjà avancé depuis le challenge posté pour `6850d93`. |
| 11:08:41 | PR#113 mergée (`9589079`). |
| ~12:30 | Audit indépendant déclenché par l'opérateur : détection de la dérive, gel des merges, présent rapport. |

## 3. Cause racine

1. **Parallélisme sans sérialisation** : les quatre PR ont été traitées en
   parallèle plutôt qu'une à la fois, avec des « Update branch » déclenchés entre
   challenge et approbation.
2. **Le challenge lie `(base_sha, head_sha)` exacts** (`build_expected_challenges`,
   `scripts/github/trusted_human_review.py:300`) — tout mouvement de l'un ou
   l'autre invalide un challenge déjà transmis, même si le contenu propre de la PR
   n'a pas changé.
3. **Gate non appliqué mécaniquement** : `Evaluate trusted human review` n'était
   pas dans `required_status_checks` de la protection de `main` — seul un audit
   manuel (fait rigoureusement pour #107, insuffisamment refait pour #108/#112/#113
   après les notifications d'approbation) faisait office de gate réel.

## 4. Verdict par PR

| PR | `TRUSTED_REVIEW_VALID` (original) | Review ID | Challenged base/head | Final (mergé) base/head | Head-pinned check-run sur le commit mergé |
|---|---|---|---|---|---|
| #107 | **true** | `4943630995` | `3308fcf` / `d8cdb59` | `3308fcf` / `d8cdb59` (inchangé) | `failure` (aucune ré-évaluation post-approbation — le workflow n'est jamais re-déclenché par une soumission de review ; non requis à l'époque du merge) |
| #108 | **false** | `4943631990` | `3308fcf` / `dad6d30` | `439255f` / `21d4e9b` | `failure` |
| #112 | **false** | `4943659291` | `3308fcf` / `17fde45` | `5f44a46` / `6518688` | `failure` |
| #113 | **false** | `4943707823` | `3308fcf` / `6850d93` | `c2c08dd` / `9db3918` | `failure` |

Pour #107, le challenge et le `commit_id` de la review coïncident exactement —
l'approbation est cryptographiquement valide pour le commit réellement mergé,
même si le check-run lui-même n'a pas été relancé après coup (limite structurelle
distincte, documentée en §7).

## 5. Delta exact post-challenge — preuve d'absence de changement propre non revu

Pour chaque PR, comparaison `git diff`/`git log` entre le head challengé et le
head final mergé :

### PR#108 (`dad6d30..21d4e9b`)
```
Commits ajoutés : 439255f (merge commit de PR#107 dans main), 21d4e9b (merge de main dans la branche)
Fichiers : 6 fichiers, tous identiques au contenu de PR#107 (Lot C — atomic deployment wrapper)
```
`439255f` == `mergeCommitSha` officiel de PR#107 (vérifié via `gh pr view 107 --json mergeCommit`).
Aucun commit propre à la branche de #108 n'apparaît dans cet intervalle.
**PR108_POST_CHALLENGE_NOVEL_CHANGE=false**

### PR#112 (`17fde45..6518688`)
```
Commits ajoutés : 439255f (#107), 5f44a46 (#108), 6518688 (merge de main dans la branche)
Fichiers : 11 fichiers, exactement l'union du contenu de PR#107 + PR#108
```
`5f44a46` == `mergeCommitSha` officiel de PR#108. `439255f` == celui de PR#107.
Aucun commit propre à la branche de #112 n'apparaît dans cet intervalle.
**PR112_POST_CHALLENGE_NOVEL_CHANGE=false**

### PR#113 (`6850d93..9db3918`)
```
Commits ajoutés : 439255f (#107), 5f44a46 (#108), c2c08dd (#112), 9db3918 (merge de main dans la branche)
Fichiers : 14 fichiers, exactement l'union du contenu de PR#107 + PR#108 + PR#112
```
`c2c08dd` == `mergeCommitSha` officiel de PR#112.
Aucun commit propre à la branche de #113 n'apparaît dans cet intervalle.
**PR113_POST_CHALLENGE_NOVEL_CHANGE=false**

## 6. Conclusion sur le revert

```
PR108_POST_CHALLENGE_NOVEL_CHANGE=false
PR112_POST_CHALLENGE_NOVEL_CHANGE=false
PR113_POST_CHALLENGE_NOVEL_CHANGE=false

NO_REVERT_REQUIRED=true
ORIGINAL_REVIEWS_REMAIN_INVALID=true
```

Tout le contenu présent sur `main` à `9589079a05761473ca3c7de1b54ee6d5be6b9d31`
(tree `6bb6ee82529922c5be95a34de7b89eaf52233b92`) provient exclusivement de PR dont
le **contenu propre** a été soumis, revu et — pour #107 au minimum — validé par un
challenge cryptographiquement exact. Aucun octet non revu n'a atteint `main` via
cette dérive. **Cela ne rend pas les approbations originales de #108/#112/#113
valides** : elles restent, au sens strict du protocole, des approbations données
sur un couple `(base_sha, head_sha)` différent du commit réellement mergé.

## 7. Remédiation appliquée

### 7.1 Protection de branche

Avant modification, sauvegarde intégrale de la configuration de protection de
`main`, horodatée `20260815T123848Z`, conservée en artefact d'audit local
(scratchpad de session, hors dépôt — sortie brute de
`gh api repos/cyranoaladin/RAG/branches/main/protection`) :
- `sha256=f49b5d112e2b84ceded59e0b120043f691aba197b361147ed9afdeb9bab58275`

`required_status_checks.contexts` avant :
```
packages/contracts
services/rag-pedago
services/rag-engine
services/cockpit
governance locks guard
repository controls
```

Ajout du **seul** contexte suivant, sur autorisation explicite de l'opérateur
(`GO_ADD_HEAD_PINNED_REQUIRED_CHECK=true`) :
```
Evaluate trusted human review (head-pinned)
```

Le check implicite `Evaluate trusted human review` (déclenché par `issue_comment`,
qui peut s'attacher au mauvais SHA — voir `lot_fix_trusted_review_check_sha.md`)
n'a **pas** été rendu requis, conformément à l'instruction.

Après modification, relecture live confirmée :
```
HEAD_PINNED_CHECK_REQUIRED=true
EXISTING_REQUIRED_CHECKS_PRESERVED=true
```
Diff structurel avant/après limité exclusivement à l'ajout de ce contexte —
aucune autre clé de la protection (reviews requises, enforce_admins, linear
history, force-push, deletion, conversation resolution, lock_branch,
fork_syncing) n'a été modifiée.

**Commande de rollback** (à n'exécuter que sur décision explicite) :
```
gh api repos/cyranoaladin/RAG/branches/main/protection \
  --method PUT \
  --input branch_protection_backup_20260815T123848Z.json
```

### 7.2 Nouvelle règle de sérialisation des human gates

```
HUMAN_GATE_SERIALIZATION=true
```

Procédure désormais obligatoire, une PR à la fois :
1. Choisir une PR unique.
2. La mettre à jour avec `main` si nécessaire.
3. Attendre la fin de tous les changements sur cette PR.
4. Relever `base_sha` et `head_sha` exacts.
5. Geler cette PR et n'entamer aucun autre merge vers `main` pendant ce temps.
6. Calculer/poser le challenge.
7. Demander une unique approbation à l'opérateur.
8. Après réponse, revérifier : base SHA courant, head SHA courant, `commit_id`
   de la review, challenge exact, et **succès du check requis
   `Evaluate trusted human review (head-pinned)`**.
9. Merger avec `expected_head_sha` explicite.
10. Attendre la CI post-merge sur `main`.
11. Seulement ensuite, passer à la PR suivante.

Si `base` ou `head` change après génération du challenge :
`CHALLENGE_STALE=true` → jeter l'ancien challenge → recalculer → nouvelle
approbation obligatoire. Aucune exception.

## 8. Portée

Ce rapport documente l'incident, corrige la protection de branche pour qu'il ne
puisse plus se reproduire silencieusement, et établit la procédure de
sérialisation. Il ne modifie aucun code de service, aucun contrat, aucune donnée
du corpus.
