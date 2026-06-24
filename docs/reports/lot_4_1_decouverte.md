# Rapport — Lot 4.1 (Découverte, mode hors réseau)

## Contexte

Lot 4.1 implémente la première phase de l’ADR-0004 : établir le plan d’acquisition sans levée de verrous, sans accès web, sans fetch, uniquement depuis :
- la taxonomie Terminale Maths (`services/rag-pedago/taxonomy/maths/terminale_specialite.yml`)
- la taxonomie Terminale NSI (`services/rag-pedago/taxonomy/nsi/terminale.yml`)
- le catalogue local `services/rag-pedago/data/reference/official_sources.yml`

Sortie principale : `services/rag-pedago/data/acquisition/pilot_terminale_plan.yml`.

## Règle de matching (déterministe)

La règle utilisée par `scrapers/discovery.py` est :

1. la source doit matcher la matière de la notion (`mathematiques` ou `nsi`) ;
2. la source doit matcher le niveau `terminale` ou ne pas imposer de niveau explicite ;
3. la source est retenue si :
   - un token de `notion_id` / `notion_label` apparaît dans `source_id`, `title` ou `applies_to`, ou
   - la source est identifiée comme source curriculaire de la matière ;
4. champs proposés pour chaque candidat :
   - `source_label`, `source_uri`, `rights`, `type_doc`, `audience`, `notion`, `source_manifest`.

## Sortie plan (résumé)

- Plan écrit : `services/rag-pedago/data/acquisition/pilot_terminale_plan.yml`
- Nombre de matières couvertes : 2 (`mathematiques`, `nsi`)
- Nombre de notions totales : 79
- Nombre total de candidats retenus : 156

### Résumé par matière

| Matière | Notions | Notions couvertes | Candidats au total |
|---|---:|---:|---:|
| mathematiques | 52 | 52 | 156 |
| nsi | 27 | 0 | 0 |

## Couverture

### Table de couverture

| Matière | Total notions | Notions couvertes (≥1 source) | Notions non couvertes |
|---|---:|---:|---:|
| mathematiques | 52 | 52 | 0 |
| nsi | 27 | 0 | 27 |

### Notions NSI non couvertes (27)

- `arbres`
- `attributs`
- `classes`
- `contraintes`
- `dictionnaires`
- `diviser_pour_regner`
- `files`
- `graphes`
- `invariants`
- `jointures`
- `listes`
- `methodes`
- `modele_relationnel`
- `parcours_graphes`
- `piles`
- `poo`
- `processus`
- `programmation_dynamique`
- `protocoles`
- `recherche`
- `recursivite`
- `reseaux`
- `routage`
- `securisation`
- `sql`
- `tests`
- `tri`

## Constat de lot 4.2

Le catalogue local `official_sources.yml` permet une couverture complète des notions de maths Terminale, mais **aucune notion NSI** n’a obtenu de source candidate.

Conclusion explicite pour Lot 4.2 : la recherche web (dans le cadre d’une levée de verrou `network_allowed` encadrée par ADR-0004) est nécessaire pour :
- enrichir le catalogue avec des sources NSI pertinentes,
- puis relancer une passe de découverte pour réévaluer la couverture.

## Contrôles gouvernance / garde-fous

- Aucun verrou levé dans cette lot (`network_allowed=false`, `ingestion_allowed=false` dans les configs de référence)
  - `services/rag-pedago/configs/pedago_interface_contract.yml`
  - `services/rag-pedago/configs/transition_authorization.yml`
- Aucun accès réseau déclenché durant l’exécution de la génération de plan et de couverture.
