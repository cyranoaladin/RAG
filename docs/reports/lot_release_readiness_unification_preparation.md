# Dette `release_readiness` — mesure préparatoire du lot d'unification

> Ce document ne corrige rien. Il mesure, pour que le lot post-#153 parte
> d'un périmètre établi plutôt que d'une estimation.

## 1. L'état accepté comme transitoire par #153

```
RELEASE_READINESS_IMPLEMENTATIONS=2
SERVICE_RELEASE_READINESS_DUPLICATED_LINES=1913
BYTE_IDENTICAL=true
SHA256=323ab3a796ba8b7a15d28cb2635cef2b2ba182a9fbf0dfb7e022473ed5db9025
```

Le contrôle transitoire tient sur deux jambes : l'égalité **octet pour octet**
vérifiée par une épreuve, et le déclencheur C1 qui couvre désormais la surface
runtime. Ni l'une ni l'autre ne supprime la duplication ; elles rendent la
divergence détectable au lieu de silencieuse.

## 2. Les consommateurs à préserver

### Production (6)

| Module | Ce qu'il consomme |
|---|---|
| `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py` | chargement du registre + liaison de déploiement |
| `services/rag-engine/src/ingestor/multilevel_verified_placement.py` | attente de release |
| `services/rag-engine/src/ingestor/ingestion_worker/multilevel_cli.py` | attente de release |
| `services/rag-engine/src/ingestor/ingestion_worker/multilevel_publication_resume_cli.py` | attente de release |
| `services/rag-engine/src/ingestor/resource_registry_bootstrap_cli.py` | attente de release |
| `services/rag-pedago/scripts/build_production_profile_release.py` | production de release |

### Images qui embarquent la copie (2)

```
services/rag-engine/infra/Dockerfile.ingestor-v2
services/rag-engine/infra/Dockerfile.multilevel-worker-production
```

C'est la contrainte structurante. `Dockerfile.ingestor-v2` est une **allowlist
de `COPY`, sans parseur** : installer `nexus-release-chain` y ferait entrer
`nexus-pdf-page-policy`, donc `pypdf`. L'unification ne peut donc pas se faire
en ajoutant simplement la dépendance à l'image de lecture.

### Épreuves (13 fichiers)

`test_release_readiness.py` (14 références), `test_v2_runtime_surface.py`,
`test_multilevel_scope_registry.py`, `test_multilevel_placement_resolver.py`,
`test_multilevel_worker_cli.py`, `test_multilevel_staging_catalogue.py`,
`test_multilevel_real_ingestion_contract.py`, les trois épreuves d'intégration,
`test_build_production_profile_release.py`, et côté qualification
`compute_promoted_content_set.py` + son épreuve.

## 3. Les trois voies possibles, et ce qu'elles coûtent

**(a) Dépendance de paquet dans les deux images.** La plus directe. Coût réel :
`pypdf` entre dans le runtime de lecture, dont l'allowlist a été construite
pour l'exclure. À ne retenir que si l'on accepte d'élargir cette surface, ou si
`nexus-release-chain` est d'abord scindé pour ne plus dépendre de la politique
de page.

**(b) Scinder `nexus-release-chain`.** Extraire la partie « attente de release »
qui ne dépend d'aucun parseur, et n'installer que celle-là dans l'image de
lecture. Le plus propre, le plus long : il faut établir quelle part des 1913
lignes dépend réellement de `nexus-pdf-page-policy`.

**(c) Générer la copie au lieu de la maintenir.** L'image copie un fichier
produit à la construction depuis le paquet canonique. La duplication disparaît
du dépôt sans changer les dépendances de l'image. Reste à décider ce qui
garantit la fraîcheur de la génération.

Ma recommandation est **(b)**, précédée d'une mesure : combien des 1913 lignes
touchent la politique de page. Si la réponse est « peu », (b) devient courte et
supprime la duplication sans élargir aucune surface.

## 4. Ce que le lot devra prouver

```
RELEASE_READINESS_IMPLEMENTATIONS=1
SERVICE_RELEASE_READINESS_DUPLICATED_LINES=0
RUNTIME_RELEASE_SEMANTICS=C1_RELEASE_SEMANTICS
CONSUMERS_PRESERVED=6 production + 2 images + 13 fichiers d'épreuves
```

Aucune fusion de #151 ni #150 avant ce lot.
