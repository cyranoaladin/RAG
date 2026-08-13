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

## 9. Note ADR-0035 — statut réel, non fabriqué

`docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md` est
actuellement **« Proposé — non Accepté »**, avec l'exigence explicite d'une
review humaine `APPROVED` du Code Owner sur le head exact de « la PR
d'implémentation ».

Vérification effectuée avant ce lot : le code qui implémente réellement le
mécanisme d'ADR-0035 (`packages/contracts/src/nexus_contracts/review_binding.py`)
a été introduit par **PR #95** (« H2-B: corpus production-readiness
authority and evidence gates »), déjà mergée dans `main`
(`2182339fb9a0df49419370e5ead8b92ef4d62305`). Interrogation directe de
`gh api repos/cyranoaladin/RAG/pulls/95/reviews` : **zéro review à l'état
`APPROVED`** sur cette PR — uniquement des reviews `COMMENTED` (bot Codex et
l'auteur lui-même). Comment PR #95 a satisfait la protection de branche
Code-Owner au moment de son merge n'est pas déterminé par ce lot et n'est
pas fabriqué ici.

**Ce que ce lot n'affirme pas** : PR #99 (ce lot) n'est pas la « PR
d'implémentation » d'ADR-0035 — elle ne fait que provisionner la clé
publique et le registre F2 pour un mécanisme déjà livré en code par PR #95.
L'approbation humaine attendue sur PR #99 (trusted-review, `@abenrhouma`,
distinct de l'auteur) porte sur *ce lot précis* — provisionnement des deux
fichiers gouvernés — pas sur une acceptation rétroactive d'ADR-0035. Le
statut textuel de l'ADR n'est pas modifié par ce lot ; la question de son
acceptation formelle reste un gap ouvert, antérieur à ce lot, signalé ici
sans être résolu.

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
