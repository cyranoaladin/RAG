# ADR-0041 — Activation multi-niveaux après réconciliation exacte

- **Statut** : Acceptée pour le staging gouverné
- **Date** : 2026-08-12
- **Décideur** : Nexus Réussite
- **S'appuie sur** : ADR-0036, ADR-0038, ADR-0039, ADR-0040

## Contexte

ADR-0040 a introduit la Quatrième sans autoriser son activation. Depuis, un
inventaire scellé de 150 artefacts a été entièrement évalué. Onze artefacts,
répartis sur les dix collections de l'extension prioritaire, satisfont
simultanément les gates de currentness, droits, PII, extraction, programme,
profil et chunking.

Le pipeline gouverné réel LOT41A → Worker A → LOT42 → Worker B a publié ces
onze artefacts et leurs onze placements dans une base PostgreSQL + pgvector
staging propre avec le modèle `intfloat/multilingual-e5-large`. Le snapshot
produit contient exactement 359 chunks, puis un replay complet n'a créé aucun
embedding supplémentaire. La réconciliation avec le manifest agrégé
`MULTILEVEL_AGGREGATE_RELEASE_V1` est exacte.

## Décision

Activer dans le catalogue canonique les huit collections jusque-là dormantes :

- `rag_nexus_maths_seconde_tc` ;
- `rag_nexus_francais_seconde_tc` ;
- `rag_nexus_maths_quatrieme_tc` ;
- `rag_nexus_francais_quatrieme_tc` ;
- `rag_nexus_maths_premiere_gen_specialite` ;
- `rag_nexus_francais_premiere_tc` ;
- `rag_nexus_maths_terminale_gen_specialite` ;
- `rag_nexus_pc_terminale_specialite`.

Les collections NSI Première et Terminale étaient déjà déclarées
`instanciee=true` ; cette décision ne certifie aucune ligne historique et ne
change pas leurs flags. Seules les nouvelles lignes gouvernées du manifest
multi-niveaux constituent la preuve de release staging.

L'activation reste subordonnée à un second gate indépendant : le runtime doit
charger les couples explicites `(manifest_path, manifest_sha256)`, refuser les
collisions entre releases et réconcilier exactement chaque collection avec la
base. Pour une identité V2, une readiness absente ou fausse interdit retrieval
et picker. Les identités V1 historiques conservent leur comportement.

## Limites

Cette ADR n'autorise ni déploiement de production, ni writer public, ni merge,
ni passage de la PR Draft à Ready. Elle ne change aucune clé de
`transition_authorization.yml` : notamment `real_documents_allowed=false` et
`curated_ingestion_allowed=false` restent inchangées. LocalGitHub demeure la
seule autorité humaine simulée de la campagne staging.

## Conséquences

- une base vide, partielle ou contenant une ligne inattendue reste non ready ;
- un manifest absent, drifté, concurrent ou lié à d'autres inventaires modèle
  bloque le démarrage avant trafic ;
- le snapshot Cockpit reflète mécaniquement les huit activations ;
- une collection sans release éligible ne pourrait pas être activée par cette
  décision ; l'inventaire courant en fournit au moins une pour chacune des dix.
