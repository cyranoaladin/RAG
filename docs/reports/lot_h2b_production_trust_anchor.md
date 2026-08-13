# LOT H2-B — Provisioning de l'ancre de confiance de production (Phase D)

## Contexte

`nexus_contracts.production_readiness` définit `NEXUS-PRODUCTION-READINESS-V1` :
un manifeste signé Ed25519 attestant 26 faits sur une release (SHAs de PR/merge,
identité d'arbre, digests de toutes les preuves de gouvernance, digests d'images
épinglées, verdict de gate), vérifié par `readiness_gate.py` contre une ancre
publique versionnée avant qu'un worker de production ne démarre ou ne crée un
job de mutation.

Avant ce lot : aucun workflow n'émettait ce manifeste, aucun Environment GitHub
`production` n'existait (`gh api repos/cyranoaladin/RAG/environments` → vide), et
`governance/trust-anchors/production-readiness-v1.json` n'avait jamais existé
sur aucune branche de ce dépôt (`git log --all -- "governance/trust-anchors/*"`
→ vide). `PRODUCTION_TRUST_ANCHOR_PROVISIONED=false` était donc exact.

## Décision — modèle de garde de la clé privée

Décision du propriétaire du dépôt (Alaeddine Ben Rhouma) : la clé privée Ed25519
est générée et conservée par lui-même, hors de ce dépôt et hors de l'hôte de
production. Aucun agent, aucune session Claude Code, aucun processus CI n'a
jamais eu accès à la clé privée. Seule la clé publique (64 caractères
hexadécimaux, format `Encoding.Raw`/`PublicFormat.Raw` via `cryptography`,
identique à `public_readiness_key_hex`) a été communiquée, expressément
qualifiée de partageable/commitable par le propriétaire.

Conséquence architecturale assumée : la signature d'un manifeste de readiness
réel est un acte humain ponctuel (le propriétaire exécute localement l'outil de
signature avec sa clé privée), pas une étape automatisée d'un workflow GitHub
Actions avec Environment protégé. C'est un modèle plus conservateur que celui
envisagé initialement (Environment `production` avec reviewers requis) : aucune
release ne peut être signée sans une action locale explicite du détenteur de la
clé.

## Ce que ce lot livre

- `governance/trust-anchors/production-readiness-v1.json` — ancre
  `ProductionReadinessTrustAnchor` réelle, une seule clé (`key_id
  prod-readiness-v1-2026-08-13`, `environment: production`), construite et
  round-trip-validée via le contrat réel (`ProductionReadinessTrustAnchor` +
  `parse_production_readiness_trust_anchor`), jamais assemblée à la main.
- Mise à jour du test canari `services/rag-engine/tests/test_readiness_gate.py
  ::TestTheRealGovernedRootResolvesOnAnActualCheckout` : ce test exerce
  `enforce_readiness_gate` contre la racine **réelle, non mockée** du dépôt et
  affirmait explicitement `PRODUCTION_TRUST_ANCHOR_PROVISIONED=false` (échec
  sur « governed production readiness anchor » absent). Ce lot inverse
  légitimement cette assertion : l'ancre existe désormais réellement et se
  parse ; la frontière d'échec se déplace correctement vers la validation du
  contenu du manifeste (`{}` invalide), jamais vers une résolution de racine
  cassée. Renommé en conséquence
  (`test_production_with_a_provisioned_anchor_fails_on_the_manifest_alone`),
  avec une assertion explicite que le fichier réel existe (regression canary
  dans l'autre sens si l'ancre disparaît).

## Hors périmètre de ce lot (réserves explicites)

- **Aucun outil de signature n'est livré ici.** Construire l'assembleur des 26
  faits (SHAs Git, digests de review binding / autorisation / revocation
  registry / catalog / sealed manifest / h2b report, digests d'images
  épinglées) et le CLI de signature local est un travail séparé et substantiel,
  nécessitant une lecture approfondie de `revocation_registry.py`,
  `sealed_evidence.py` et du mécanisme de digest du catalogue — non fait ici
  pour ne pas mélanger la provision de l'ancre (petite, autonome, terminée) et
  cette pièce plus large (à traiter dans un lot dédié).
- Aucun workflow GitHub Actions n'est créé. Le modèle retenu (clé détenue
  hors-repo par le propriétaire) ne nécessite pas d'Environment GitHub
  `production` pour la signature elle-même ; un Environment pourrait encore
  être utile pour *protéger le déploiement* (pas la signature), question
  distincte non tranchée ici.
- Aucune activation de production n'a lieu : ce lot rend `readiness_gate.py`
  capable de vérifier un manifeste signé réel, mais aucun manifeste réel n'a
  encore été signé, et aucun worker de production n'a démarré.

## Preuves

```
$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_readiness_gate.py tests/test_production_workers_compose.py -q
....................................................... [100%]  (57 passed)

$ PYTHONPATH=src .venv/bin/python -m pytest -q -m "not integration"   # suite complète rag-engine
.... (100% passed, aucune régression)

$ .venv/bin/python -m ruff check tests/test_readiness_gate.py
All checks passed!
```

**Dette préexistante, non introduite par ce lot** (antériorité prouvée contre
le commit parent `2182339fb9a0df49419370e5ead8b92ef4d62305` via `git stash` +
re-run) :

```
tests/test_readiness_gate.py:69: error: Unused "type: ignore" comment  [unused-ignore]
```

Présente à l'identique avant et après ce lot — non liée aux lignes modifiées
(488-513 avant édition). Non corrigée ici, hors périmètre de ce lot.

## Prochaine étape

`PRODUCTION_TRUST_ANCHOR_PROVISIONED=true` (l'ancre existe, se vérifie, et le
gate la résout correctement). Reste à construire, dans un lot séparé : l'outil
de signature local (rassemblement des 26 faits + invocation de
`sign_production_readiness_manifest` avec la clé privée détenue par
l'opérateur) avant qu'un manifeste de production réel puisse exister.
