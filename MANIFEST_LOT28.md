# MANIFEST — Archive LOT 28 (prête à appliquer)

## Application (workflow du dépôt : un lot = une branche = une PR)

```bash
git clone https://github.com/cyranoaladin/RAG.git && cd RAG
git checkout -b lot-28-corpus-ingestion-cockpit
# Depuis la racine du dépôt, appliquer l'overlay :
tar xzf lot-28_nexus_rag_complet.tar.gz -C /tmp
cp -rn /tmp/lot28/* .          # -n : n'écrase pas l'existant sans revue
# Exceptions — fichiers à fusionner manuellement (voir §Fichiers modifiés) :
#   services/rag-engine/configs/rag_collections.yml  (v2 → v3)
#   services/cockpit/*                               (placeholder → application)
git add -A && git commit -m "lot-28: corpus tous niveaux + ingestion continue eduscol + cockpit v2"
bash scripts/ci-local.sh       # CI locale verte requise avant PR
```

## Contenu de l'archive

| Chemin | Statut | Description |
|---|---|---|
| `docs/audits/AUDIT_LOT28_GLOBAL.md` | nouveau | Audit global + registre E-01→E-07 + plan A→D |
| `docs/adr/ADR-0015-corpus-tous-niveaux.md` | nouveau | Arborescence corpus + catalogue v3 |
| `docs/adr/ADR-0016-ingestion-continue-eduscol.md` | nouveau | Agents continus gouvernés |
| `docs/adr/ADR-0017-cockpit-v2-rag-ui.md` | nouveau | Remplacement du dashboard legacy |
| `docs/reports/lot_28_mise_au_point_globale.md` | nouveau | Rapport de lot + dettes D-28-* |
| `docs/runbooks/rag_ui_v2_deploiement.md` | nouveau | Déploiement + rollback rag-ui v2 |
| `corpus/College/…`, `corpus/Lycee/…`, `corpus/Referentiels/…` | nouveau | 55 fiches + 9 `_index.yml` |
| `services/rag-pedago/taxonomy/**` | nouveau | 39 taxonomies (validées TaxonomySpec) |
| `services/rag-pedago/agents/eduscol_agent.py` | nouveau | Agent eduscol staging-only |
| `services/rag-pedago/agents/continuous_orchestrator.py` | nouveau | Pilote de passes (CLI --plan/--run) |
| `services/rag-pedago/configs/eduscol_sources.yml` | nouveau | 20 sources (8 verified / 12 to_verify) |
| `services/rag-pedago/configs/continuous_ingestion.yml` | nouveau | Politique d'ingestion continue |
| `services/rag-engine/configs/rag_collections.yml` | **modifié** | Catalogue v3 (59 collections) |
| `scripts/continuous-ingestion.sh`, `scripts/systemd/*` | nouveau | Planificateur (timer quotidien) |
| `services/cockpit/` | **remplacé** | Cockpit v2 (React/TS/Tailwind) |

## Fichiers modifiés (fusion manuelle recommandée)

- `rag_collections.yml` : diff v2 → v3 (ajout de 24 blocs + en-tête version). Le diff est volontairement append-only avant la section `domains:`.
- `services/cockpit/` : le placeholder (AGENTS.md + README.md) est conservé ; l'application est ajoutée à côté.

## Après fusion

1. CI locale verte consignée dans le rapport de lot.
2. Phase B : revue humaine des stagings → vagues d'instanciation (`instanciee: true` progressif).
3. Déploiement cockpit : `docs/runbooks/rag_ui_v2_deploiement.md`.
4. Activation ingestion continue : runbook §Étape 5.
