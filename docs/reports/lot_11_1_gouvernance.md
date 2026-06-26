# Rapport — Lot 11.1 : Gouvernance parsing + retours bots

## Violation régularisée

Le parsing PDF (`build_correspondence_report`) tournait alors que `pdf_allowed: false` / `parsing_allowed: false`. Il était appelé depuis le constructeur de `SubjectAgent`.

### Régularisation

1. **Verrous levés** : `pdf_allowed: true # ADR-0004` et `parsing_allowed: true # ADR-0004` dans le contrat, transition_authorization, et baseline. Scope : « parsing de programmes officiels en staging ». `ingestion_allowed`, `chunking_allowed`, `embeddings_allowed` restent false.

2. **Parsing confiné** : `scripts/build_correspondence.py` vérifie `pdf_allowed` ET `parsing_allowed` avant de parser (gating réel). Produit des artefacts JSON dans `data/programmes/correspondance/`.

3. **Agents metadata-only** : `SubjectAgent._load_correspondence` lit le JSON pré-calculé, n'importe plus `programme_parser`, ne parse plus de PDF. Conforme AGENTS.md.

## Artefacts générés

- `mathematiques_seconde.json` : 20 exact, 3 partial, 4 not_found
- `nsi_premiere.json` : 11 exact, 3 partial, 11 not_found

## Retours bots corrigés

| # | Sévérité | Correction |
|---|---|---|
| P1 | Parsing hors verrou | Verrous levés tracés + parsing confiné |
| P1 | Faux compte staging (écrasement fichiers) | Filename inclut source_label |
| P1 | Gardes YAML vide/non-dict | isinstance check ajouté |
| P2 | Exceptions silencieuses level_agent | Print du fichier + raison |
| P2 | max_notions=0 ignoré | `is not None` |
| P2 | ADR-0005 arithmétique fausse | Corrigé |

## Garde-fou

```
Governance locks: baseline=17, config=17
OK: all governance locks match baseline (17 keys verified).
```

`ingestion_allowed=false`, `chunking_allowed=false`, `embeddings_allowed=false`.

## CI locale : 7/7 PASS
