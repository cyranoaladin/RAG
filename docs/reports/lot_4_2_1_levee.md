# Rapport — Lot 4.2.1 : Levée de verrou tracée

## Transition enregistrée

`transition_authorization.yml` : `network_allowed: true` avec commentaire ADR-0004 et scope (GET-only, whitelist, robots.txt, rate limit). Cas d'autorisation `network_fetch_authorized_adr_0004` ajouté.

## Baseline restaurée (17 clés)

`governance-locks.baseline` contient `network_allowed: true  # ADR-0004`. Le garde-fou surveille 17 clés (pas 16).

## Démonstration garde-fou

**Avec trace ADR (passe)** :
```
Governance locks: baseline=17, current=17
OK: all governance locks match baseline (17 keys verified).
```

**Sans trace ADR — activation non tracée (échoue)** :
Testé via test suite (test 2: lock removed → exit 1, message "deviate from baseline"). 8/8 guard tests pass.

## Tests de gouvernance réarmés

- `REQUIRED_FALSE_FLAGS` : `network_allowed` **restauré** dans les 3 scripts d'audit
- `AUTHORIZED_TRUE_FLAGS` dict ajouté : un flag à `true` est accepté SI il est dans ce dict + ADR référencé
- Test négatif : un flag autorisé à `true` mis à `false` → rejet (`must be true (authorized under ADR-0004)`)
- Un flag non autorisé mis à `true` → toujours rejeté

## Import lazy de `requests`

`scrapers/fetch.py` : `requests` et `urllib.robotparser` importés **à l'intérieur** de `governed_fetch()` / `_get_robots()`, pas au niveau module. Le test `test_import_manifest_no_network_modules_loaded` passe en batch (snapshot avant/après, vérifie les modules **nouvellement** chargés).

## robots.txt conservateur

Si `robots.txt` ne peut pas être récupéré → `disallow_all = True` (refus par défaut).

## Tolérance ci-local.sh

Revenue à **1** (seul `test_real_draft_guard` préexistant).

## CI locale : 6/6 PASS, garde-fou 17/17
