# PLAN — Provisionnement du GitHub Environment `production`

## Statut

**Plan uniquement. Aucune configuration créée par ce document.** Créer
ou modifier un GitHub Environment est une action de niveau administrateur
du dépôt (Settings → Environments), hors périmètre d'une PR de code et
hors de ce que je peux exécuter moi-même sans un geste humain explicite
sur l'interface GitHub (ou un jeton avec des droits d'administration que
je n'ai pas et ne dois pas demander). Ce document prépare la décision ;
il ne l'exécute pas.

`PRODUCTION_GITHUB_ENVIRONMENT_EXISTS=false` (vérifié en direct,
`gh api repos/cyranoaladin/RAG/environments` → `{"total_count":0,
"environments":[]}`, reconfirmé au moment de la rédaction de ce plan).
Tant que cet Environment n'existe pas, la clause `environment:
production` déjà présente dans `_produce-h2-evidence.yml` et
`promote.yml` (PR #109/#110) reste une **intention YAML sans application
réelle** côté GitHub — aucun approbateur requis n'est aujourd'hui
appliqué avant qu'un de ces jobs ne s'exécute.

## 1. Environments actuels

```
$ gh api repos/cyranoaladin/RAG/environments
{"total_count":0,"environments":[]}
```

Aucun. Le seul Environment à créer pour l'instant : `production` (nom
exact déjà référencé par `environment: production` dans les deux
workflows existants — ne pas en créer un autre nom sans changer aussi
ces deux fichiers).

## 2. Identité de l'approbateur requis

Collaborateurs actuels du dépôt :

```
$ gh api repos/cyranoaladin/RAG/collaborators --jq '.[] | {login, permissions}'
{"login":"cyranoaladin","permissions":{"admin":true,...}}
{"login":"abenrhouma","permissions":{"admin":false,"push":true,...}}
```

`abenrhouma` est l'identité qui a émis chaque approbation
`/nexus-trusted-review` valide de cette mission (challenge
cryptographique dans le corps de la review, jamais un simple « ok »)
sur PR #99, #101, #103, #104, #106 — c'est l'identité humaine de
décision déjà établie par ce protocole tout au long de la session.
**Recommandation** : `abenrhouma` comme `required_reviewers` de
l'Environment `production`. `cyranoaladin` porte les droits admin du
dépôt (peut committer/pousser du code) mais ne doit jamais être
lui-même l'approbateur qui gate son propre code — voir §4.

Ceci reste une recommandation à valider par l'opérateur humain, pas une
affectation déjà décidée par ce document.

## 3. Politique de branche de déploiement

`deployment_branch_policy` doit restreindre aux runs déclenchés depuis
`main` uniquement — cohérent avec le refus déjà codé dans les deux
workflows (`if`/refus explicite sur `github.ref != 'refs/heads/main'`,
PR #109/#110/#112). Recommandation :

```json
{
  "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User", "id": "<abenrhouma_user_id>"}]}],
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}
}
```

avec une règle de branche personnalisée limitée à `main` — GitHub ne
propose pas nativement "n'importe quelle branche protégée" comme
condition suffisante ici tant que `main` n'a pas de règle de protection
de branche classique la désignant explicitement compatible; à vérifier
au moment de la configuration réelle plutôt que supposé.

## 4. Empêcher l'auto-revue (prevent self-review)

GitHub Environments ne propose pas systématiquement un réglage natif
"empêcher l'auteur de la PR d'approuver son propre déploiement" au même
titre que la protection de branche classique — **si disponible** dans
l'UI du dépôt au moment de la configuration réelle, l'activer. À
défaut, la garantie repose sur la discipline déjà établie tout au long
de cette mission : le code est committé/poussé par l'identité
opératrice (Claude, sous le compte git `cyranoaladin@gmail.com`), jamais
approuvé par la même identité — `abenrhouma` reste la seule identité qui
approuve, jamais celle qui committe. Documentée ici comme contrôle
compensatoire explicite si le réglage natif n'existe pas.

## 5. Politique de bypass administrateur

Recommandation : **aucun bypass admin autorisé** pour l'Environment
`production` — même `cyranoaladin` (droits admin du dépôt) ne doit pas
pouvoir contourner l'approbation requise pour un déploiement réel.
GitHub permet de restreindre qui peut bypasser une règle d'Environment
via les réglages de branche protégée associés ; à configurer strictement
(pas de "Allow specified actors to bypass required workflows" pour ce
gate spécifique, sauf décision explicite contraire de l'opérateur).

## 6. Wait timer

Recommandation : `wait_timer = 0`, sauf raison contraire explicite de
l'opérateur. Rien dans ADR-0036 ni dans les workflows déjà écrits
n'exige un délai de retenue automatique après approbation — l'approbation
humaine elle-même (via le protocole `/nexus-trusted-review` déjà en
place, séparé de ce gate d'Environment) est la retenue voulue.

## 7. Secrets nécessaires

**Aucun.** Confirmé par les deux workflows existants
(`test_never_signs_and_never_touches_a_private_key`,
`_produce-h2-evidence.yml`'s docstring « le workflow *constate*, il ne
signe pas ») : aucune clé de signature production-readiness, ni aucun
autre secret long-vécu, ne doit jamais être ajouté aux secrets de cet
Environment. Le seul jeton utilisé par ces workflows est
`${{ github.token }}`/`secrets.GITHUB_TOKEN`, éphémère et scopé au run,
déjà couvert par les permissions `contents: read`/`actions: read`/
`packages: read|write` minimales déjà en place — jamais un secret
d'Environment dédié à ajouter pour ce lot.

## 8. Séquencement recommandé

Ne pas provisionner cet Environment avant le premier run réel de
promotion production (`promote.yml`), pour éviter de configurer une
protection contre un scénario encore théorique et risquer de devoir la
retoucher avant qu'elle ait jamais servi. Quand ce sera le prochain
blocker irréductible du chemin de mise en production réelle (c'est-à-dire
quand tout le reste — PR #100 finalisée, campagne/autorisation réelle
construite, image de production réellement construite — sera prêt et
qu'il ne restera plus que ce geste d'administration GitHub), présenter
**une seule action humaine** : la configuration de cet Environment selon
ce plan (ou une version amendée par l'opérateur), pas avant.

## 9. Booléens finaux

```
PRODUCTION_GITHUB_ENVIRONMENT_EXISTS=false
PRODUCTION_GITHUB_ENVIRONMENT_PLAN_DOCUMENTED=true
PRODUCTION_GITHUB_ENVIRONMENT_PROVISIONED=false
REQUIRED_REVIEWER_IDENTITY_RECOMMENDED=abenrhouma
SECRETS_REQUIRED=none
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
