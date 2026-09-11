# L'écart entre un corpus gouverné et un RAG interrogeable

Document dérivé. Ne pas éditer à la main :
`scripts/go_live/build_rag_searchability_gap.py` le régénère depuis
l'audit d'ingestion, qui a interrogé une base nommée.

## Ce qui est mesuré

- texte canonique en préparation : **2473**
- contenus ingérés : **2473**
- **vecteurs présents : 0**
- colonnes vectorielles : 0
- extension vectorielle : False
- périmètre cible : **2264**

## Ce qui n'est pas mesuré

- `production_searchable` — aucune base de production n'a été identifiée ni interrogée ; ne pas savoir n'est pas une autorisation.

## Pourquoi zéro vecteur rend le RAG inexploitable

le texte est stocké, pas indexé : aucune requête ne peut l'atteindre. Un corpus qualifié servable reste inatteignable tant qu'aucun vecteur ne le référence.

La confusion joue dans un sens précis : « tout est ingéré » se lit
spontanément comme « le RAG fonctionne ». Les deux sont séparés par une
étape entière.

## Le blocage qui porte ce refus

`RAG_SEARCHABILITY` — `rag_searchability_blocker=true`.

Ce document ne se contente plus de constater : tant que les conditions
ci-dessous ne sont pas toutes tenues, le readiness refuse le go-live et
nomme cette raison.

## Conditions de fermeture

| condition | tenue |
| --- | :---: |
| `staging_vectors_present` | **non** |
| `vector_dimensions_consistent` | **non** |
| `retrieval_top_k_validated` | **non** |
| `citations_validated` | **non** |
| `scope_filters_validated` | **non** |
| `latency_validated` | **non** |
| `rollback_validated` | **non** |
| `target_scope_searchable` | **non** |

Aucune ne suffit seule. Des vecteurs sans retrieval validé ne servent
personne ; un retrieval validé sur un échantillon ne dit rien du
périmètre cible.

Le déploiement en production n'est pas autorisé par la fermeture de ce
blocage : il relève d'une décision distincte.

## Trois phrases qu'il serait faux de dire

- RAG fully ingested : le texte est stocké, pas indexé
- RAG searchable : aucun vecteur n'existe
- corpus prêt à servir : la servabilité est une qualification, pas une capacité de recherche
