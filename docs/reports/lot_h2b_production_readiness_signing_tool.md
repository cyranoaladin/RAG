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
13 passed in 0.27s

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

Couverture adversariale (13 tests) : manifeste complet valide + round-trip
réel via `verify_production_readiness_manifest` ; permissions 0600 sur la
sortie ; `pr_head_sha` mal formé refusé ; `pr_head_tree_sha` ≠
`merge_tree_sha` refusé par le contrat (`_bindings_hold`) ; tag d'image
mutable refusé ; liste d'images vide refusée ; doublon de nom de service
refusé ; fichier d'evidence absent refusé ; environnement non-production
refusé dès `argparse` (`choices=["production"]`) ; **mauvaise clé de
signature → revérification échoue** ; **clé déclarée `environment=test` →
jamais acceptée en production** ; **falsification post-signature
(`run_id`) → signature invalidée** ; **échec de revérification → aucun
fichier de sortie écrit**.

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
PRODUCTION_MANIFEST_SIGNED=false
GO_LIVE_READY=false
```
