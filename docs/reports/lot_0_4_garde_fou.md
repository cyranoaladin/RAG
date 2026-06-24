# Rapport — Lot 0.4 : Garde-fou robuste et testé (clôture Lot 0)

## Corrections

### 1. Robustesse pipefail

- Extraction tolérante au zéro-match : `{ grep ... || true; }` empêche `set -e` de tuer le script.
- Comptage correct sur vide : fonction `count_lines()` retourne 0 si la chaîne est vide (au lieu de 1 via `echo "" | wc -l`).
- Comparaison `comm -23` protégée contre l'entrée vide.

### 2. Script testable

Chemins overridables via variables d'environnement :
- `GOVERNANCE_CONTRACT_FILE` (défaut : `services/rag-pedago/configs/pedago_interface_contract.yml`)
- `GOVERNANCE_BASELINE_FILE` (défaut : `$SCRIPT_DIR/governance-locks.baseline`)

Comportement par défaut inchangé.

### 3. Matrice de tests

| # | Cas | Exit attendu | Exit obtenu | Résultat |
|---|-----|-------------|-------------|----------|
| 1 | Nominal (contract == baseline) | 0 | 0 | PASS |
| 2 | Verrou retiré (`chunking_allowed` manquant) | 1 | 1 | PASS |
| 3 | Swap (même compte, clé différente) | 1 | 1 | PASS |
| 4 | Zéro verrou (no-match grep) | 1 | 1 | PASS |
| 5 | Exception ADR | SKIP | — | Vérifié manuellement (lot-0.2) |

Assertions sur exit code **et** contenu de sortie : 8 assertions passées sur 8.

## CI locale

```
==============================
  CI LOCAL — SUMMARY
==============================
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  governance-guard-tests

Total: 5 passed, 0 failed
```

## Verdict bots

GitHub Actions indisponible (compte verrouillé pour facturation). Re-trigger des bots à effectuer une fois le compte débloqué. Si des P0/P1/P2 sont remontés, ils seront listés ici sans ouvrir de Lot 0.5.

## Aucune logique métier modifiée
