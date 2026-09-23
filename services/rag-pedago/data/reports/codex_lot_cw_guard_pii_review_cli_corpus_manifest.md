# Rapport Codex — Lot CW-garde : empreinte du corpus dans le CLI de revue PII

Rapport de lot racine : `docs/reports/lot_go_live_cw_guard_pii_review_cli_corpus_manifest.md`.

## Fichiers créés

- `data/reports/codex_lot_cw_guard_pii_review_cli_corpus_manifest.md`

## Fichiers modifiés

- `scripts/revue_pii_cli.py`
- `tests/test_revue_pii_cli.py`

## Comportement

- `--corpus-manifest-sha256` n'a plus de valeur par défaut ; un nouveau
  brouillon exige une empreinte explicite (64 hex).
- Un brouillon qui porte déjà une empreinte la garde ; un argument différent
  est refusé sans réécriture.
- Le fichier `--corpus-manifest-authority` (par défaut celui que le producteur
  lie) doit déclarer une `authority_sha256` valide, vérifiée avant toute
  comparaison ; l'empreinte retenue doit être celle de ses octets. La
  confusion avec la valeur déclarée est nommée dans le refus.

## Tests

Tests ajoutés (rouges avant correction, verts après) :

- pas d'écrasement silencieux d'une empreinte existante ;
- empreinte existante conservée sans argument ou avec la même valeur ;
- nouveau brouillon sans empreinte refusé ;
- CLI sans valeur par défaut ;
- valeur déclarée refusée à la place de l'empreinte du fichier ;
- vérification par défaut contre le fichier d'autorité du producteur ;
- fichier d'autorité illisible, sans déclaration ou à déclaration invalide
  refusé même quand l'empreinte fournie correspond.

## Résultats

```bash
python -m pytest -q tests/test_revue_pii_cli.py tests/test_sceller_decisions_pii.py
ruff check scripts/revue_pii_cli.py tests/test_revue_pii_cli.py
mypy scripts/revue_pii_cli.py
```

```text
20 passed
All checks passed!
Success: no issues found in 1 source file
```
