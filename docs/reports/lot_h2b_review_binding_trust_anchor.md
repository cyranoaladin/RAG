# LOT H2-B — Ancre de confiance review-binding + registre de révocation gouverné (ADR-0035, F1/F2)

## 1. Verdict du lot

État technique : les deux artefacts sont provisionnés, validés round-trip
contre les contrats réels, testés (canaris de sensibilité inclus), CI verte
sur tous les checks automatisés. **Aucune activation de production** :
aucun reçu de review-binding n'a été émis, aucune autorisation LOT41A n'est
enregistrée, aucun worker de production ne tourne, aucune donnée n'a été
ingérée. `GO_LIVE_READY` reste `false`. Aucune mutation live n'a eu lieu sur
`nexus-prod` au cours de ce lot.

## 2. Périmètre

Provisionnement de deux fichiers gouvernés sous `governance/trust-anchors/`,
tous deux requis par `rag_pedago.imports.h2b_coverage_report` (F1 : ancre de
confiance ; F2 : registre de révocation) pour qu'un rapport de couverture
H2-B puisse un jour atteindre `coverage_complete=true` :

- `governance/trust-anchors/review-binding-v1.json`
- `governance/trust-anchors/authorization-revocations-v1.json`

## 3. Ancre de confiance review-binding

```
protocol_version = NEXUS-REVIEW-BINDING-V1
key_id            = review-binding-v1-2026-08-13
algorithm         = ed25519
environment       = production
```

Seule la clé **publique** est commitée. La clé privée a été générée par le
propriétaire du dépôt (Alaeddine Ben Rhouma) sur sa propre machine, avec le
script Python fourni (mêmes primitives `cryptography` que le contrat réel :
`Ed25519PrivateKey.generate()` + `Encoding.Raw`/`PrivateFormat.Raw`), et n'a
jamais été transmise, collée, journalisée ni lue par cette session ou par
un pipeline CI. Elle reste hors dépôt, hors serveur de production, hors
GitHub Actions.

## 4. Séparation des clés

```
REVIEW_BINDING_KEY_DISTINCT_FROM_PRODUCTION_READINESS_KEY=true
```

Preuve par comparaison des seules valeurs publiques (aucune clé privée
manipulée pour établir ceci) :

| | key_id | public_key |
|---|---|---|
| production-readiness (PR #97) | `prod-readiness-v1-2026-08-13` | `9a426a44...e305a` |
| review-binding (ce lot) | `review-binding-v1-2026-08-13` | `bae8268b...b0d4f` |

`key_id` distincts, `public_key` distinctes, `protocol_version` distincts
(`NEXUS-PRODUCTION-READINESS-V1` vs `NEXUS-REVIEW-BINDING-V1`) — deux
autorités indépendantes par construction, jamais interchangeables : le
contrat `TrustAnchor.key()` de chaque module refuse une clé déclarée pour
un autre protocole avant même de comparer les octets.

## 5. Chemins gouvernés

| Fichier | Chemin | Résolu par |
|---|---|---|
| Ancre review-binding | `governance/trust-anchors/review-binding-v1.json` | `h2b_coverage_report._GOVERNED_TRUST_ANCHOR_PATH`, dérivé de `_GOVERNED_REPOSITORY_ROOT` (remontée depuis l'emplacement du module, jamais un chemin machine-local) |
| Registre de révocation F2 | `governance/trust-anchors/authorization-revocations-v1.json` | `h2b_coverage_report._GOVERNED_REVOCATIONS_PATH` |

Les deux chemins sont **refusés en argument** (`--authority-trust-anchor`,
`--authority-revocations`) dès que `environment=production` :
`TRUST_ANCHOR_ARGUMENT_FORBIDDEN` / `REVOCATION_REGISTRY_ARGUMENT_FORBIDDEN`
si une valeur différente du chemin gouverné est fournie. Aucun chemin de
code ne permet à une ancre ou un registre de production de venir d'ailleurs.

## 6. Registre de révocation F2

```json
{
  "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
  "revoked_authorization_ids": []
}
```

**Un registre vide gouverné n'est pas un registre absent.** L'absence de
fichier produit `REVOCATION_REGISTRY_MISSING` — refus explicite, parce
qu'elle ne distingue pas « rien n'est révoqué » de « personne n'a regardé ».
Le fichier ci-dessus est la preuve, versionnée et committée, que quelqu'un a
vérifié qu'aucune autorisation LOT41A n'est aujourd'hui révoquée — c'est
correct à la date de ce lot puisqu'aucune autorisation de production n'est
encore enregistrée en base (PR #98 non approuvée, non enregistrée). Ce
fichier devra être régénéré (nouveau contenu, nouveau digest) le jour où
une révocation réelle doit y apparaître.

Ceci est un mécanisme **distinct** de
`ingestor.ingestion_control.revocation_registry` (le registre runtime du
worker de production, préparé séparément comme artefact de déploiement sur
le serveur — non commité, car c'est une donnée opérationnelle montée au
runtime, pas une déclaration de gouvernance versionnée). Les deux registres
répondent à des questions différentes pour des consommateurs différents.

## 7. Tests — résultats exacts

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/test_h2b_coverage_report.py -q
........................................................................ [ 82%]
...............                                                          [100%]
87 passed in 1.24s

$ .venv/bin/python -m ruff check tests/test_h2b_coverage_report.py
All checks passed!

$ .venv/bin/python -m mypy tests/test_h2b_coverage_report.py
tests/test_h2b_coverage_report.py:431: error: Argument 13 to "generate_coverage_report" ...
tests/test_h2b_coverage_report.py:1591: error: Argument 1 to "Path" ...
tests/test_h2b_coverage_report.py:1924: error: List item 0 has incompatible type ...
Found 4 errors in 1 file (checked 1 source file)

$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_readiness_gate.py \
    tests/test_production_workers_compose.py -q   # rag-engine, unaffected
....................................................... [100%]

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source governance/trust-anchors/review-binding-v1.json --no-git
no leaks found
$ gitleaks detect --source governance/trust-anchors/authorization-revocations-v1.json --no-git
no leaks found
```

**Antériorité des 4 erreurs mypy** : identiques (même lignes, même
messages, à un décalage de numéro de ligne près dû aux insertions de ce
lot) à celles déjà documentées comme préexistantes dans
`docs/reports/lot_h2c_lot41a_v2_philosophie_terminale.md` et
`docs/reports/lot_h2b_production_trust_anchor.md`, prouvées contre le
commit parent via `git stash` + rejeu. Non introduites par ce lot, non
situées dans le code ajouté ici, non corrigées ici (hors périmètre).

Toutes les commandes ci-dessus ont été exécutées dans un environnement
`PYTHONPATH=.` strictement isolé de `rag-engine` (`import ingestor` échoue),
reproduisant exactement l'isolation du job CI `services/rag-pedago` — leçon
tirée du vrai échec CI corrigé plus tôt sur ce même lot (import
interservice interdit par AGENTS.md, retiré au commit suivant).

## 8. Canaris de sensibilité — preuves

Tous ajoutés dans ce lot (`TestProductionTrustAnchorSensitivityCanaries`
existait déjà pour l'ancre de production-readiness ; les tests suivants
sont nouveaux, pour review-binding et F2) :

| Scénario | Test | Résultat |
|---|---|---|
| Ancre review-binding manquante | *(couvert par construction : `h2b_coverage_report._resolve_trust_anchor_path` lève `TRUST_ANCHOR_MISSING` si le fichier gouverné n'existe pas — testé indirectement par la suite existante, non dupliqué ici)* | RED garanti par le code, pas un nouveau test dédié |
| Ancre ambiguë (deux protocol_version identiques sous governance/) | `test_the_repository_ships_exactly_the_provisioned_review_binding_anchor` (assert `len(candidates) == 1`) | RED si >1, prouvé par construction du test (échouerait avec `assert 2 == 1` si un doublon apparaissait) |
| Mauvais protocole | Discrimination par `document.get("protocol_version") == "NEXUS-REVIEW-BINDING-V1"` — un fichier d'un autre protocole n'entre jamais dans `candidates` | Exclu par construction |
| Clé publique malformée | `parse_trust_anchor` (contrat réel, `Field(pattern=_HEX_ED25519)`) — refus Pydantic fail-closed | RED garanti par le contrat, exercé par `test_a_malformed_public_key_fails_closed` (ancre production-readiness, même mécanisme partagé) |
| Mauvais environnement (`test` au lieu de `production`) | boucle `for key in anchor.keys: assert key.environment == "production"` dans le nouveau test | RED si violé |
| Registre de révocation manquant | `TestGovernedRevocationRegistry::test_an_absent_governed_registry_refuses_in_production` (suite préexistante) + `test_the_repository_ships_the_governed_revocation_registry` (nouveau, real-root) | RED confirmé par la suite existante |
| Registre de révocation malformé | `TestGovernedRevocationRegistry::test_a_registry_without_protocol_version_is_refused`, `test_a_registry_with_duplicate_ids_is_refused`, `test_a_registry_with_unknown_keys_is_refused` (suite préexistante, non dupliquée) | RED confirmé par la suite existante |
| Fichiers gouvernés valides | `test_the_repository_ships_exactly_the_provisioned_review_binding_anchor`, `test_the_repository_ships_the_governed_revocation_registry` (nouveaux, contre la vraie racine du dépôt, jamais un tmp_path synthétique) | PASS |

## 9. Note ADR-0035 — statut réel, vérifié en direct (corrigé)

**Correction d'une erreur de vérification antérieure de ce rapport.** La
version précédente affirmait « zéro review `APPROVED` » sur PR #95, sur la
base de `gh api repos/cyranoaladin/RAG/pulls/95/reviews` **sans
pagination** — cet appel tronque silencieusement à 30 résultats, alors que
PR #95 en porte 45. Les deux reviews `APPROVED` existent bel et bien, mais
tombaient au-delà de la troncature. Reproductible :
`gh api ... --paginate` renvoie bien 45 entrées, dont deux `APPROVED`.

`docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md` (introduite
par **PR #95** elle-même, même commit que le code qui implémente son
mécanisme — `git log` ne montre aucune autre PR touchant ce fichier) exige
une review `APPROVED` du Code Owner sur le head exact de « la PR
d'implémentation ». Vérification complète, en direct, sur les objets de
review individuels (jamais sur `reviewDecision` seul) :

```
ADR0035_IMPLEMENTATION_PR=95
ADR0035_REQUIRED_HEAD=3d0cf47133dfdba488890a9be3e6fe1fc83bd863
ADR0035_APPROVED_REVIEW_FOUND=true
ADR0035_REVIEWER=abenrhouma
ADR0035_REVIEW_COMMIT_ID=3d0cf47133dfdba488890a9be3e6fe1fc83bd863
ADR0035_TRUSTED_CHALLENGE_VALID=true
ADR0035_ACCEPTANCE_CONDITION_SATISFIED=true
```

Preuve : review `id=4923100913`, `state=APPROVED`, `commit_id` identique au
head réel de PR #95 au moment de l'approbation (`3d0cf471...`, confirmé par
`gh pr view 95 --json headRefOid`), corps
`NEXUS-TRUSTED-REVIEW-V1:ab4e17ab79bb118ab4661cadef9f48820a02d5c9bf3c30baa9b003d07f785fff`.
Le challenge n'est pas pris au mot : le run GitHub Actions réel
(`31663947902`, job `Evaluate trusted human review`, `conclusion=success`,
`2026-08-13T03:26:57Z`) a recalculé et publié la même décision côté
machine : `{"approved": true, "head_sha": "3d0cf471...", "reviewer":
"abenrhouma", "review_id": 4923100913, ...}`. Aucune review `DISMISSED` ou
`CHANGES_REQUESTED` d'`abenrhouma` n'existe après cette approbation (les
deux seules `DISMISSED` trouvées datent du 10/08, sur des heads antérieurs
`f2a662bc...`/`e9708fec...`, bien avant l'approbation finale du 13/08). PR
#95 a mergé 13 minutes après, sans nouvelle review entre-temps.

**Conclusion : la condition d'acceptation d'ADR-0035 est satisfaite.** Ce
rapport ne prétend plus qu'il existe un gap de review sur PR #95 — il n'y
en a pas. Suivant le précédent établi par ADR-0031 (commit dédié `8c95114`,
« accept ADR-0031 after governed PR #90 review »), la mise à jour du statut
textuel de l'ADR a fait l'objet d'un lot documentaire distinct et minimal,
jamais fusionné dans la PR d'implémentation elle-même : **PR #101**
(« docs(adr): accept ADR-0035 after governed PR #95 review »), approuvée
humainement par `abenrhouma` (review `id=4926402363`, `state=APPROVED`,
`commit_id=26ead2694418ba914d1e71c62d4b5d6c9d0958a5` — identique au head de
PR #101), challenge trusted-review revérifié `SUCCESS` (run GitHub Actions
`31695238933`), puis mergée (`merge_commit=35ec35e5f25e1e81e394d6e0280e40701134fd35`).
Cette base (`35ec35e5f25e1e81e394d6e0280e40701134fd35`) est le point de
rebase de la présente branche. Statut vérifié en lisant directement le
fichier ADR sur ce commit, pas déduit du texte de PR #101 :

```
ADR0035_STATUS_ON_BASE_MAIN=ACCEPTE
```

**Ce que ce lot n'affirme toujours pas** : PR #99 (ce lot) n'est pas la
« PR d'implémentation » d'ADR-0035 — elle provisionne la clé publique et le
registre F2 pour un mécanisme déjà livré et déjà formellement approuvé par
PR #95. L'approbation humaine attendue sur PR #99 porte sur *ce lot
précis*, pas sur ADR-0035.

## 10. Limitations — ce que ce lot ne fait pas

- Aucune clé privée review-binding n'existe dans ce dépôt, sur le serveur,
  ou dans un pipeline CI.
- Aucun reçu de review-binding signé (`SignedScopeAuthorizationReviewBinding`)
  n'a été émis pour aucune autorisation.
- Le manifeste de production readiness (`ProductionReadinessManifestV1`)
  n'est pas signé.
- PR #98 (LOT41A-V2) n'est ni approuvée, ni enregistrée en base.
- Aucun worker de production ne tourne.
- Aucune mutation de base de données de production.
- Aucune bascule publique, aucun changement de `/opt/rag-v2/current`.

## 11. Booléens finaux

```
REVIEW_BINDING_TRUST_ANCHOR_PROVISIONED_CANDIDATE=true
GOVERNED_AUTHORIZATION_REVOCATION_REGISTRY_PRESENT=true
REVIEW_BINDING_RECEIPT_ISSUED=false
PRODUCTION_LOT41A_REGISTERED=false
PRODUCTION_WORKERS_DEPLOYED=false
GO_LIVE_READY=false
```
