# LOT41V — Autorité de revue humaine GitHub fiable

## Verdict

**LOT41V: READY_FOR_HUMAN_REVIEW**

**GO_LIVE: NO_GO**

Le code installe une frontière GitHub fail-closed pour vérifier une décision
humaine indépendante sur le head exact d'une pull request. Il n'active aucun
writer, aucune ingestion, aucune publication et aucun verrou `*_allowed`.

La livraison reste conditionnée à une review formelle personnelle
d'`abenrhouma` sur le head final, aux checks GitHub de ce head, puis à une
fusion et un run `push` verts. La protection cible ne sera appliquée qu'après
que le workflow producteur du statut existe sur `main`.

## Identification

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-04 |
| Dépôt | `cyranoaladin/RAG` |
| Baseline `main` | `374b231ed8f68bf3b35875c915dedacee9d3313c` |
| Branche | `lot-41v-trusted-human-review` |
| Reviewer autorisé | `abenrhouma` |
| Permission GitHub relue | `write`, rôle `write` |
| Décision | ADR-0025 |
| Contrats métier | aucune évolution |
| Verrous de gouvernance | aucun changement attendu |

## Objectifs

1. Remplacer les revendications locales d'approbation par une review GitHub
   authentifiée et indépendante.
2. Lier cette review au dépôt, à la PR, à la base, au dernier head, à l'auteur
   et au reviewer au moyen d'un challenge canonique.
3. Publier un statut fail-closed depuis un workflow présent uniquement sur la
   branche de base, sans exécuter le code de la PR.
4. Rendre la protection cible stricte sans bloquer la fusion bootstrap qui
   installe le workflow.
5. Conserver le projet fermé tant que LOT41A, LOT42 et les preuves
   opérationnelles ne sont pas terminés.

## Architecture livrée

La configuration `trusted-reviewers.json` fixe le protocole, le dépôt, la base
et l'allowlist. Le noyau Python pur valide strictement les formes JSON, calcule
le challenge et rend une dataclass de décision. Il n'a aucun accès réseau.

L'adaptateur GitHub sépare deux modes :

- `--check`, lecture seule, retourne `0` uniquement si la review est valide et
  `3` lorsqu'elle reste en attente ;
- `--publish`, valide le dépôt, pose le statut `pending` avant toute lecture de
  PR, collecte deux snapshots reviews/permissions, réévalue le dernier, relit
  encore la base et le head, publie `success` ou `failure`, puis crée ou met à
  jour un commentaire géré.

La collecte utilise `gh api` avec un argv sans shell, un timeout de 30 secondes,
des pages de 100 éléments et une limite de 20 pages. Une pagination saturée,
une réponse malformée, un doublon ou une course de head échoue fermé.

Le workflow `trusted-human-review.yml` écoute `pull_request_target` et la
commande publique littérale `/nexus-trusted-review` via `issue_comment`. Ces
triggers chargent le workflow privilégié depuis la branche par défaut. Il
checkout uniquement `refs/heads/main`, avec des actions épinglées et sans
credential persistant. Les champs libres d'une PR ne sont jamais interprétés.

La politique cible exige sept checks, tous liés à l'application GitHub Actions
`15368`, dont le statut externe `trusted-human-review`. Elle exige aussi une
review, le Code Owner, le rejet des reviews obsolètes et l'approbation du
dernier push. Aucun bypass n'est admis.

La politique conserve `required_status_checks.strict = true`. Si `main`
avance, GitHub bloque donc la fusion jusqu'à intégration de cette base dans la
branche de tête ; le nouveau head invalide le statut et le challenge antérieurs.

## Fichiers concernés

- `.github/CODEOWNERS` ;
- `.github/workflows/ci.yml` ;
- `.github/workflows/trusted-human-review.yml` ;
- `scripts/ci-local.sh` ;
- `scripts/github/main-protection-policy.json` ;
- `scripts/github/main_protection.py` ;
- `scripts/github/trusted-reviewers.json` ;
- `scripts/github/trusted_human_review.py` ;
- `scripts/github/trusted_human_review_github.py` ;
- les tests de protection, challenge, adaptateur, workflow, topologie et
  failsafe sous `scripts/tests/` ;
- ADR-0025, roadmap, spécification, plan et présent rapport.

## Cycles RED → GREEN ciblés

| Cycle | RED observé | GREEN obtenu |
| --- | --- | --- |
| Politique et Code Owner | quatre échecs et trois erreurs sur la politique historique et l'absence de CODEOWNERS | politique stricte et CODEOWNERS validés |
| Challenge canonique | fonctions et configuration absentes | 5 tests canoniques verts, ensuite intégrés à la suite pure |
| Décision pure | approbation exacte, révocation, fork, bots et permissions non traités | 14 tests verts |
| Adaptateur GitHub | module absent | 13 tests verts |
| Workflow privilégié | fichier absent | 6 tests verts |
| Câblage CI | trois commandes absentes des deux CI | topologie verte et 51 mutants failsafe verts |
| Origine des checks | politique aveugle à `app_id` | 34 tests de protection verts et sept checks liés à l'application `15368` |
| Permission GitHub live | les fixtures historiques utilisaient `permission=push`, alors que l'API expose `permission=write` pour le rôle `write` | noyau et adaptateur alignés, 14 + 13 tests verts |
| Review de bot live | le login réel `chatgpt-codex-connector[bot]` arrêtait l'évaluation avant le filtrage de l'allowlist | acteur bot strictement parsé mais non autorisable, puis décision live ramenée à la seule approbation manquante |
| Source du workflow de review | `pull_request_review` a chargé le YAML depuis le merge ref et échoué après le checkout de `main` | trigger supprimé, recalcul déplacé vers `issue_comment` chargé depuis la branche par défaut, 6 tests workflow verts |
| Révocation et retargeting | une erreur de première lecture pouvait laisser un ancien succès ; un changement de base n'était pas déclenché | `pending` publié avant la première lecture, repli `failure` testé et événement `edited` ajouté |
| Snapshot final | reviews, permission et dépôt n'étaient pas tous revalidés à la dernière frontière | dépôt validé avant écriture, double collecte, réévaluation finale et troisième lecture base/head |
| Atteignabilité CI locale | le câblage LOT41V était seulement recherché comme texte | sonde d'exécution avec commandes neutralisées et mutant après `exit 0` rejeté |
| Scope du commentaire | la commande pouvait lancer l'adaptateur pour une PR hors `main` | base relue par API et sortie sans mutation avant tout appel du publisher |

Les cas couvrent notamment l'auto-review, la permission insuffisante, l'ancien
head, le mauvais challenge, la révocation, le fork, les pages incomplètes, la
course de SHA, le timeout, le commentaire usurpé, une review de bot non
autorisé, les permissions du workflow, l'absence de checkout du head et
l'absence de contexte de job homonyme.

Le run GitHub `30864574764` a fourni la preuve que `pull_request_review`
chargeait le workflow proposé par la PR : ses étapes ont démarré alors que le
fichier n'existait pas sur `main`, puis le script correctement checkouté depuis
`main` était absent. Ce trigger a donc été retiré, comme `workflow_dispatch`
dont le `ref` peut être choisi par l'appelant. Le recalcul consécutif à une
review passe désormais par un commentaire littéral
`/nexus-trusted-review` ; son corps ne devient ni code, ni autorité, et le head
est relu par API avant l'évaluation.

## État GitHub observé avant livraison

Le 2026-08-04, le readback du collaborateur donne :

```json
{"permission":"write","role_name":"write","user":"abenrhouma"}
```

La première évaluation de la PR publiée a échoué fermé avec
`reviewer_permission_insufficient` parce que les fixtures modélisaient la
permission REST historique `push`. Un cycle RED → GREEN a aligné le noyau sur
les valeurs GitHub actuelles `write`/`admin`, tout en conservant le contrôle
séparé de `role_name` (`write`, `maintain` ou `admin`). Le readback suivant a
révélé que la review `COMMENTED` de `chatgpt-codex-connector[bot]` était rejetée
avant filtrage. Un second cycle RED → GREEN accepte la forme bornée d'un acteur
GitHub App pour lire toutes les reviews, sans permettre à un bot d'entrer dans
l'allowlist humaine. Le readback rend alors `current_head_approval_missing` :
la permission est établie et seule la décision humaine personnelle reste
absente.

La protection live reste volontairement celle de la transition : six checks
CI, historique strict, administrateurs inclus, conversations résolues, zéro
approbation obligatoire, pas de Code Owner obligatoire et pas d'approbation du
dernier push. Elle n'est pas modifiée avant la présence du workflow sur `main`.

Les six checks live existants sont déjà associés à l'application GitHub Actions
`15368`. Le septième ne peut être ajouté qu'après installation et preuve du
workflow.

## Limites et dépendance humaine

- Le workflow privilégié n'existe pas encore sur `main` et ne peut donc pas
  certifier sa propre PR bootstrap.
- `abenrhouma` doit personnellement lire le diff et utiliser le bouton GitHub
  **Approve** sur le head final avec le challenge exact ; aucun agent ne peut
  accomplir cet acte à sa place.
- La politique live cible n'est pas encore appliquée.
- LOT41V ne fournit ni autorisation de scope LOT41A, ni attestations LOT42, ni
  revue substantielle du corpus, ni preuve de sauvegarde/restauration ou de
  production.
- Un compte reviewer compromis exige une révocation immédiate et une nouvelle
  allowlist.

## Procédure d'application live

1. Exécuter la CI locale exhaustive et publier la branche.
2. Ouvrir une PR vers `main`, attendre les six checks CI et résoudre tous les
   fils.
3. Calculer le challenge du head distant exact et le communiquer dans la PR.
4. Faire soumettre par `abenrhouma` une review formelle `APPROVED` contenant ce
   challenge sur une ligne distincte.
5. Pour la PR bootstrap uniquement, exécuter l'adaptateur local `--check` avec
   le head distant exact et publier sa sortie normalisée dans la conversation ;
   aucun statut privilégié n'est revendiqué avant la fusion.
6. Relire par API la permission, la review, son `commit_id`, son état et le
   head courant ; toute divergence impose un nouveau cycle.
7. Fusionner sans bypass et attendre le run `push` du SHA fusionné.
8. Sur une PR témoin, poster `/nexus-trusted-review`, puis prouver le statut
   produit par le workflow désormais chargé depuis `main`.
9. Appliquer la politique avec le SHA exact de `main` et la confirmation
   explicite `cyranoaladin/RAG@<sha>`.
10. Relire les sept checks et leurs `app_id`, les quatre règles de review,
   l'absence de bypass et les protections destructives.

## Preuves locales exhaustives

Sur le head courant, les résultats ciblés frais sont :

- `test-main-protection-policy.py` : 34 tests réussis ;
- `test-trusted-human-review.py` : 14 tests réussis ;
- `test-trusted-human-review-github.py` : 13 tests réussis ;
- `test-trusted-human-review-workflow.py` : 6 tests réussis ;
- `test-ci-local-topology.sh` : PASS ;
- `test-ci-local-failsafe.sh` : 51 réussites, 0 échec ;
- Ruff ciblé et `git diff --check` : PASS.

La première tentative exhaustive s'est arrêtée avant les tests parce que le
shell exposait Node 22.21.0 au lieu de la version 22.22.0 fixée par `.nvmrc`.
La suivante a exposé deux causes distinctes : le Python 3.11 installé par `uv`
créait des venvs liés à un préfixe `/install` absent, et l'allowlist exacte du
test d'hygiène n'incluait pas encore les trois nouvelles commandes LOT41V. La
source de vérité d'hygiène a été corrigée et testée ; aucun seuil de version ni
garde-fou n'a été assoupli.

La relance fraîche sur le head source exact
`758c4024805666f294503ae4bb79f424c6054f7b`, avec Python 3.12.3 et Node
22.22.0, a produit **16 cibles réussies et 0 échec** :

- `packages/contracts` : import du contrat réussi ;
- `services/rag-pedago` : Ruff, `mypy` sur 76 fichiers et 1 757 tests réussis ;
- `services/rag-engine` : Ruff, `mypy` sur 53 fichiers, suite non-intégration
  complète et intégration PostgreSQL réelle terminée par
  `LOT40_HYBRID_INTEGRATION=PASS` ;
- `services/cockpit` : 21 fichiers de tests, 178 tests, deux builds Next.js,
  concordance des snapshots et deux audits npm sans vulnérabilité ;
- hygiène et tests d'hygiène, topologie CI, protection de `main`, trois suites
  LOT41V, taxonomie, preuves sources, verrous et tests de gouvernance : PASS ;
- tests failsafe : 51 réussites, 0 échec ;
- baseline de gouvernance : 18 clés, configuration : 18 clés, toutes
  conformes.

Le scan frais pré-documentaire couvre les 19 commits du lot jusqu'au head
source `3b977ab16f02761453eb9f567d236424c118d52e` :

```text
gitleaks git --log-opts="origin/main..3b977ab16f02761453eb9f567d236424c118d52e" --redact --no-banner
```

Résultat : aucun secret détecté. `git diff --check origin/main...HEAD` est
également vert et le worktree ne contient aucun changement non commité avant
la présente mise à jour documentaire.

Ce rapport crée nécessairement un nouveau head après le commit source cité. Il
ne prétend donc pas que la preuve locale du parent certifie ses propres octets.
Les tests ciblés seront relancés après ce commit ; les checks GitHub obligatoires
constitueront la preuve exhaustive du head distant final.

## Prochain jalon

Obtenir la review indépendante de LOT41V, fusionner et appliquer la protection
cible, puis démarrer LOT41A. LOT41A devra consommer cette frontière sans la
confondre avec les attestations de contenu LOT42.
