# Rapport — Lot 4.2.2 : Garde-fou par verrou (faille critique)

## Faille

`check-governance-locks.sh` autorisait **toute** déviation de verrou dès qu'un ADR apparaissait **n'importe où** dans le diff du contrat. Conséquence : avec `network_allowed: true # ADR-0004` dans le diff, n'importe quel autre verrou (y compris `ingestion_allowed`) pouvait être activé sans contrôle.

## Correction

La clause « ADR reference found in diff → allowing » est **supprimée**. Nouvelle logique :

1. **Comparaison stricte** config == baseline, clé par clé. Toute déviation → FAIL.
2. **Tout verrou `true` dans la baseline** doit porter `ADR-[0-9]+` sur sa propre ligne. Sinon → FAIL.
3. Activer un verrou = éditer baseline ET config de façon cohérente, en PR. Plus de bypass par diff.

## Démonstrations

### Demo 1 : Nominal
```
Governance locks: baseline=17, config=17
OK: all governance locks match baseline (17 keys verified).
EXIT=0
```

### Demo 2 : ingestion_allowed:true (faille fermée)
```
Governance locks: baseline=17, config=17
FAIL: config deviates from baseline:
  Expected but missing/changed in config:
    ingestion_allowed: false
  In config but not matching baseline:
    ingestion_allowed: true
BLOCKED: 1 governance violation(s).
EXIT=1
```

### Demo 3 : baseline true sans ADR
```
Governance locks: baseline=17, config=17
FAIL: network_allowed is true in baseline without ADR reference on its line.
BLOCKED: 1 governance violation(s).
EXIT=1
```

## Tests (14/14 PASS)

| Test | Cas |
|---|---|
| 1 | Nominal (all false) → PASS |
| 2 | Lock removed → FAIL |
| 3 | Swap (same count) → FAIL |
| 4 | All flipped to true → FAIL |
| 5 | Authorized true with ADR → PASS |
| 6 | **FLAW: second lock activated while ADR exists elsewhere → FAIL** |
| 7 | Baseline true without ADR → FAIL |

## CI locale : 6/6 PASS
