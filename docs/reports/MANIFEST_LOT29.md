# MANIFEST — Archive LOT 29 : revue par panel d'agents experts (ADR-0018)

## Application (après fusion du LOT 28)

```bash
cd ~/Bureau/RAG
git checkout main && git pull
git checkout -b lot-29-revue-agents-experts
tar xzf lot-29_revue_agents_experts.tar.gz -C /tmp
cp -r /tmp/lot29/* .
# puis : tests, CI locale, commit, push, PR (même procédure que LOT 28)
```

## Contenu

| Chemin | Statut | Description |
|---|---|---|
| `docs/adr/ADR-0018-revue-par-agents-experts.md` | nouveau | Décision : revue par panel d'agents (amende ADR-0005/0009/0016) |
| `docs/reports/lot_29_revue_agents_experts.md` | nouveau | Rapport de lot |
| `services/rag-pedago/configs/review_policy.yml` | nouveau | Politique du panel (consensus, seuils, règles dures) |
| `services/rag-pedago/agents/reviewers.py` | nouveau | RightsExpert / SubjectExpert / QualityExpert |
| `services/rag-pedago/agents/review_panel.py` | nouveau | Orchestrateur + CLI (--plan/--run) |
| `services/rag-pedago/tests/unit/test_review_panel.py` | nouveau | 10 tests unitaires (10/10 verts) |
| `services/cockpit/src/sections/ReviewSection.tsx` | **modifié** | Page « Revue agents » (verdicts signés, plus de boutons manuels) |

## Vérifications déjà effectuées

- 10/10 tests unitaires du panel (approbation unanime, désaccord → quarantaine, reviewer en échec fail-closed, droits inconnus → quarantaine, intégrité, hors programme, page WAF).
- Bout en bout : `--plan` liste les artefacts pending ; `--run` écrit les verdicts signés dans les manifestes + ledger append-only.
- Lint ruff propre ; cockpit rebuildé (version preview sauvegardée).

## Usage

```bash
cd services/rag-pedago
PYTHONPATH="$(pwd):$(pwd)/../../packages/contracts/src" python3 -m agents.review_panel --plan
PYTHONPATH="$(pwd):$(pwd)/../../packages/contracts/src" python3 -m agents.review_panel --run
cat data/reports/review_panel_latest.md
```
