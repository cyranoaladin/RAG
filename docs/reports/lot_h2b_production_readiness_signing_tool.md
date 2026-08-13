# LOT H2-B — Outil de signature du ProductionReadinessManifest

## 1. Verdict du lot

Outil livré et testé. **Aucun manifeste de production réel n'a été signé** —
ce lot livre l'outil, pas un manifeste. `GO_LIVE_READY` reste `false`.
Aucune mutation live.

## 2. Ce que fait l'outil

`services/rag-engine/scripts/sign_production_readiness_manifest_cli.py`
assemble un `ProductionReadinessManifestV1` (26 champs, contrat réel de
`packages/contracts/src/nexus_contracts/production_readiness.py`) depuis
des arguments CLI explicites et typés, le signe Ed25519, puis **revérifie
immédiatement** la signature produite contre l'ancre publique avant
d'écrire quoi que ce soit sur disque.

## 3. Ce qu'il refuse structurellement

- **Aucun booléen libre.** Il n'existe pas de `--ready true`. Chaque fait
  est soit un chemin de fichier que l'outil relit et rehash lui-même
  (`review_binding_digest`, `authorization_digest`, `trust_anchor_digest`,
  `revocation_registry_digest`, `catalog_digest`, `sealed_manifest_digest`,
  `h2b_report_digest`, `compose_digest`), soit une valeur dont le format
  est strictement validé (SHA Git 40-hex, digest OCI `name@sha256:...`).
- **Image mutable refusée.** `--application-image ingestor=...:latest`
  échoue explicitement (`pinned as`) — seul `name@sha256:<64hex>` est
  accepté, jamais un tag.
- **Tree SHA jamais dérivé du commit SHA.** `--pr-head-tree-sha` et
  `--merge-tree-sha` sont deux arguments **distincts**, calculés par
  l'appelant (`git rev-parse <sha>^{tree}`) — bug réel corrigé pendant ce
  lot (voir §6).
- **Clé privée jamais journalisée, jamais en argument.** Lue depuis
  `--private-key-file` uniquement ; la variable est explicitement écrasée
  (`"0" * len(...)`) avant toute écriture disque.
- **Revérification obligatoire avant écriture.** Si la vérification contre
  l'ancre publique échoue (mauvaise clé, mauvais environnement), l'outil
  retourne 1 et **n'écrit aucun fichier de sortie** — prouvé par mutation
  (§6).

## 4. Ce que cet outil ne fait PAS (hors périmètre explicite)

- Ne dérive **aucun** fait automatiquement depuis Git/GitHub/Docker en
  live — chaque digest est fourni par l'opérateur via un chemin de fichier
  réel, que l'outil vérifie mais ne découvre pas lui-même. L'automatisation
  de la collecte (lire `git`, interroger `gh api`, `docker inspect`) est un
  chantier séparé, plus tard, sur cette même base.
- Ne construit aucun des fichiers d'evidence qu'il consomme
  (`catalog.json`, `h2b_report.md`, etc.) — ceux-ci doivent exister au
  moment de l'appel, produits par leurs propres outils canoniques
  (`corpus_catalog_compiler.py`, `h2b_coverage_report.py`, ...).
- N'active rien : signer un manifeste ne l'enregistre nulle part, ne
  démarre aucun worker.

## 5. Tests — résultats exacts

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_sign_production_readiness_manifest_cli.py -v
25 passed in 0.37s

$ .venv/bin/python -m ruff check scripts/sign_production_readiness_manifest_cli.py \
    tests/test_sign_production_readiness_manifest_cli.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m mypy scripts/sign_production_readiness_manifest_cli.py
Success: no issues found in 1 source file

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source services/rag-engine/scripts/sign_production_readiness_manifest_cli.py --no-git
no leaks found
$ gitleaks detect --source services/rag-engine/tests/test_sign_production_readiness_manifest_cli.py --no-git
no leaks found
```

Couverture adversariale (25 tests) : manifeste complet valide + round-trip
réel via `verify_production_readiness_manifest` ; permissions 0600 sur la
sortie ; `pr_head_sha` mal formé refusé ; `pr_head_tree_sha` ≠
`merge_tree_sha` refusé par le contrat (`_bindings_hold`) ; tag d'image
mutable refusé ; liste d'images vide refusée ; doublon de nom de service
refusé ; fichier d'evidence absent refusé ; environnement non-production
refusé dès `argparse` (`choices=["production"]`) ; **mauvaise clé de
signature → revérification échoue** ; **clé déclarée `environment=test` →
jamais acceptée en production** ; **falsification post-signature
(`run_id`) → signature invalidée** ; **échec de revérification → aucun
fichier de sortie écrit** ; **reçu de revue signé par une clé non
reconnue → refusé** ; **reçu couvrant une autre autorisation → refusé** ;
**auto-approbation (reviewer == author) → refusée** ; **reçu de revue
expiré → refusé** ; **autorisation hors de sa fenêtre de validité →
refusée** ; **autorisation révoquée → refusée** ; **registre de révocation
malformé → refusé** ; **`--output` == `--private-key-file` (y compris via
lien symbolique) → refusé, clé locale intacte**.

## 6. Discipline de vérification — deux bugs réels trouvés et corrigés pendant ce lot

**Bug 1 (dans l'outil) : `pr_head_tree_sha` substitué par `pr_head_sha`.**
Le premier jet assignait par erreur le SHA de commit à la place du SHA
d'arbre Git — exactement le genre de fait fabriqué que cet outil existe
pour empêcher. Corrigé avant tout commit : deux arguments CLI distincts et
obligatoires, jamais l'un dérivé de l'autre.

**Bug 2 (dans le test, pas dans l'outil) :**
`test_main_never_writes_output_when_verification_fails` construisait son
propre `argv` à la main sans jamais créer les fichiers d'evidence requis
— le test passait, mais parce que l'outil échouait plus tôt (fichier
introuvable), jamais parce que la revérification avait réellement été
exercée. Prouvé en pratique : une régression injectée délibérément (suppression
du bloc de revérification dans `main()`) faisait **toujours passer** ce
test tel qu'il était écrit à l'origine. Corrigé en réutilisant
`_base_args(tmp_path)` (qui crée réellement les fichiers) ; réinjection de
la même régression après correction → le test échoue bien
(`assert rc == 1` reçoit `0`, `MANIFEST_DIGEST=...` imprimé, fichier de
sortie effectivement écrit). Régression retirée, suite repassée verte
(13/13), diff confirmé identique à l'état pré-injection.

## 6bis. Codex — trois constats sur ce même diff, vérifiés en direct

Trois commentaires Codex sont arrivés après le premier push (`c4d5b60`,
diff inchangé au fond au moment de leur lecture) :

- **P1 — « Verify governance artifacts before signing them ».** Constat
  exact : l'outil se contentait de hacher `--review-binding-file` et
  `--authorization-file`, jamais de vérifier qu'ils décrivent une revue
  humaine réelle, non expirée, non révoquée, portant sur l'autorisation
  présentée. `gate_result` était figé à `"pass"` sans lien avec ce que ces
  fichiers contenaient réellement. **Corrigé** : `assemble_and_sign()`
  vérifie maintenant le reçu de revue avec le vérificateur canonique
  d'ADR-0035 (`verify_review_binding`, `require_matches_authorization`,
  `require_challenge_is_bound` — `packages/contracts`, aucune primitive
  réinventée), confronte l'autorisation à sa fenêtre de validité, et la
  confronte au registre de révocation (nouveau `--review-binding-trust-
  anchor-file`, requis). 8 canaris adversariaux nouveaux
  (`TestReviewBindingIsActuallyVerified`), chacun vérifié par mutation :
  désactiver le bloc de vérification fait échouer les tests attendus pour
  la raison attendue (voir §6ter).
- **P1 — « Bind the complete image inventory to the Compose file ».**
  Constat exact et **non corrigé dans ce lot** : `--application-image` /
  `--upstream-image` et `--compose-file` sont aujourd'hui deux sources
  indépendantes — rien n'empêche qu'elles divergent (service omis, digest
  différent). Le remède que Codex suggère (dériver les images du Compose
  résolu) exige un analyseur YAML de Compose que ce dépôt n'a pas
  aujourd'hui (aucune dépendance PyYAML dans `rag-engine`, aucun fichier
  Compose commité pour valider un tel analyseur contre une forme réelle),
  et une décision sur *où* ce Compose « résolu » est obtenu (fichier du
  dépôt ? sortie de `docker compose config` sur l'hôte cible ?). C'est une
  extension d'architecture, pas une correction locale à cet outil — hors
  périmètre de ce lot signing-tool par l'esprit d'AGENTS.md (« si un lot
  exige de toucher une logique métier hors de son périmètre... s'arrêter et
  le signaler »). **Signalé ici explicitement** ; nécessite un lot dédié
  avec sa propre décision de conception.
- **P2 — « Reject output paths that alias signing inputs ».** Constat
  exact : rien n'empêchait `--output` de désigner (y compris via lien
  symbolique) le même fichier que `--private-key-file`, ce qui aurait
  silencieusement écrasé la graine de signature locale sur une invocation
  par ailleurs réussie. **Corrigé** : `_reject_output_aliasing_an_input()`
  compare le chemin résolu de `--output` à celui de chaque entrée (clé
  privée, ancres, preuves) avant tout traitement ; 4 nouveaux tests
  (`TestOutputNeverAliasesAnInput`), y compris un alias via lien
  symbolique et un passage complet par `main()` prouvant qu'aucune écriture
  n'a lieu.

## 6ter. Discipline de vérification appliquée aux trois nouveaux garde-fous

Chaque nouveau chemin de refus a été prouvé par mutation, pas seulement
écrit puis supposé correct :

```
Mutation 1 : le bloc de vérification review-binding est remplacé par un
  raise inconditionnel.
  -> Les tests qui doivent réussir (manifeste valide, round-trip) échouent.
  -> Les tests qui attendent un message *différent* (fenêtre de validité,
     registre de révocation malformé) échouent aussi, avec le message de
     la mutation au lieu du leur -- preuve qu'ils exercent réellement leur
     propre chemin de code en temps normal, pas un chemin déjà mort.
  Mutation retirée, 25/25 repassés verts.

Mutation 2 : l'appel à `_reject_output_aliasing_an_input(args)` est retiré
  de `main()`.
  -> `test_main_refuses_before_touching_any_file_when_output_aliases_the_key`
     échoue : `rc == 0` au lieu de `1`, et le manifeste est bien écrit
     par-dessus la graine de signature (`MANIFEST_DIGEST=...` imprimé).
  Mutation retirée, 25/25 repassés verts.
```

## 7. Limitations

- Aucune clé privée de production n'a été utilisée par cet outil dans ce
  lot — seulement des graines de test triviales (`"11"*32`, `"22"*32`).
- Aucun manifeste réel n'a été assemblé ni signé pour PR #97, #98 ou #99.
- La collecte automatique des faits (git/GitHub/Docker live) reste à
  construire.
- L'outil n'a pas encore été exercé contre les vrais fichiers d'evidence
  de production (catalogue de disposition réel, rapport H2-B réel) —
  ceux-ci n'existent pas encore tant que PR #98 n'est pas enregistrée.

## 8. Booléens finaux

```
PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=true
FREE_FORM_READINESS_BOOLEAN_ALLOWED=false
SIGNED_MANIFEST_VERIFY_ROUNDTRIP=true
REVIEW_BINDING_ACTUALLY_VERIFIED_BEFORE_SIGNING=true
OUTPUT_PATH_CANNOT_ALIAS_A_SIGNING_INPUT=true
COMPOSE_IMAGE_INVENTORY_CROSS_BINDING=false  # Codex P1, signalé §6bis, hors périmètre de ce lot
PRODUCTION_MANIFEST_SIGNED=false
GO_LIVE_READY=false
```
