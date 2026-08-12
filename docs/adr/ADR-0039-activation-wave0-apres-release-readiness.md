# ADR-0039 — Activation canonique Wave 0 après release readiness exacte

**Statut : Acceptée**
**Date : 2026-08-12**
**Décideur : Nexus Réussite**

## Contexte

Les collections `rag_nexus_maths_troisieme_tc` et
`rag_nexus_francais_troisieme_tc` étaient activées uniquement par un overlay
staging. La chaîne gouvernée définie par les ADR-0036 à ADR-0038 est désormais
matérialisée dans PostgreSQL + pgvector staging avec les modèles canoniques et
réconciliée avec le manifest agrégé Wave 0.

Le booléen `instanciee` ne constitue jamais à lui seul une autorisation de
serving. Le runtime doit conserver une seconde condition indépendante : le
manifest désigné par `RAG_RELEASE_MANIFEST_PATH` et
`RAG_RELEASE_MANIFEST_SHA256` doit être valide et sa matérialisation dans la
base doit être exacte.

## Décision

Activer dans le catalogue canonique uniquement :

- `rag_nexus_maths_troisieme_tc` ;
- `rag_nexus_francais_troisieme_tc`.

L'overlay staging Wave 0 devient une dérivation vide du catalogue canonique.
Aucune autre collection ne change d'état.

Cette décision s'inscrit dans
`services/rag-pedago/configs/transition_authorization.yml` : les capacités
techniques déjà autorisées (`server_start_allowed`, `runtime_api_allowed` et
`ingestion_allowed`) ne sont pas élargies. En particulier,
`real_documents_allowed=false` et `curated_ingestion_allowed=false` restent
inchangés ; l'activation du catalogue n'est ni une autorisation de production,
ni une approbation humaine de la PR Draft.

Le démarrage de l'API refuse une collection Wave 0 activée si le manifest est
absent, si son digest diverge ou si la réconciliation produit un écart. Le
picker, `/search/v2` et `/chat` restent fermés dans les mêmes cas. Les
collections historiques hors release Wave 0 conservent leur comportement.

## Preuves préalables

L'activation est autorisée seulement après observation de toutes les propriétés
suivantes sur la base staging réconciliée :

- `MISSING_ARTIFACTS=0` et `UNEXPECTED_ARTIFACTS=0` ;
- `MISSING_PLACEMENTS=0` et `UNEXPECTED_PLACEMENTS=0` ;
- `MISSING_CHUNKS=0` et `UNEXPECTED_CHUNKS=0` ;
- SHA et métadonnées de page conformes au manifest ;
- modèle `intfloat/multilingual-e5-large`, dimension 1024 ;
- placements `reviewed`, `current` et `active` ;
- `FAKE_VECTOR_ROWS=0`.

Le manifest reste l'autorité des ensembles attendus. Le catalogue n'autorise
ni ajout implicite, ni wildcard, ni repli sur la seule présence de lignes.

## Conséquences

Le runtime peut exposer les deux collections uniquement lorsque les deux gates
sont simultanément vrais : activation canonique et release evidence exacte.
Une base partielle ou un manifest dérivé d'un autre HEAD provoque un échec au
démarrage avant le chargement des modèles. Toute future activation exige sa
propre décision et ses propres preuves ; ADR-0039 n'autorise ni Wave 1 ni les
ressources multi-niveaux du cycle 4.
