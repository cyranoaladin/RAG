# Préflight du candidat public blue-green — 9 octobre 2026

## Périmètre et verdict

Lot issu de `origin/main` `811674bdbcf6db38e15a8528919567ef750c3a0c`, arbre
`230873415e6c9502b8ff9b4aef76a50bfeb549e4`. Ce lot ajoute une primitive
de **qualification locale en lecture seule** du candidat public. Il ne
déploie rien et ne change ni le staging ni la production historique.

`services/rag-engine/scripts/public_blue_green_preflight.py` accepte le
Compose **résolu** de la couleur `blue` ou `green`, le SHA source, les racines
des matériaux et des secrets et les images issues du vérificateur de
provenance canonique. Le point d'entrée
`require_candidate_with_live_provenance` obtient lui-même ces images depuis le
run GitHub Actions vérifié, au SHA et à l'arbre exacts ; il refuse un digest
API opérateur divergent.

Le préflight exige exactement les trois services `pgvector`, `ingestor`,
`prometheus`, le projet `nexus-rag-blue` ou `nexus-rag-green`, les deux volumes
nommés propres à ce projet, aucun build, aucune publication du port DB, un
unique port loopback pour API et Prometheus, les deux DSN API vers le
`pgvector` du même projet et tous les binds attendus en lecture seule. Il
refuse un chemin dans n'importe quel checkout Git (y compris un worktree
frère signalé par un fichier `.git`), un lien symbolique, un hardlink de
fichier inventorié, un fichier manquant ou supplémentaire et toute empreinte
de fichier divergente.

## Liaison des matériaux au Compose signé

La release publique successeur devra contenir, à la racine des matériaux
durables hors checkout, `release-material-manifest.json` au protocole
`NEXUS-PUBLIC-MATERIAL-V1` :

```json
{"protocol":"NEXUS-PUBLIC-MATERIAL-V1","source_sha":"<SHA40 final>","files":{"configs/exemple":"<SHA256>"}}
```

Le champ `files` doit inventorier **tous** les fichiers ordinaires sous la
racine, sauf le manifeste lui-même, avec des chemins relatifs et des SHA-256
des octets réels. Aucun contenu V4/V5 rehearsal ne peut devenir public par
la seule présence dans ce répertoire : les autorisations, droits et revues
de la release successeur restent des préconditions indépendantes.

Le SHA-256 des octets du manifeste est passé comme
`NEXUS_RELEASE_MATERIAL_MANIFEST_SHA256` dans l'overlay. Docker Compose le
place dans l'étiquette résolue `nexus.release-material.sha256` de l'API. La
primitive compare cette étiquette au manifeste réellement lu, puis compare
chaque fichier au digest inventorié. Le `compose_digest` retourné utilise la
canonicalisation du vérificateur existant. Ainsi, **quand** le futur
manifeste de readiness signé attestera ce Compose résolu, sa signature liera
ce digest de matériaux au SHA final. Ce lien n'est pas encore présent dans
une signature de release finale.

## Vérifications et limites

- Cycle TDD : refus observés avant le code pour les binds omis ou ajoutés,
  volumes d'un autre projet et DSN pointant une base externe.
- `python -m pytest -q services/rag-engine/tests/test_public_blue_green_compose.py services/rag-engine/tests/test_public_blue_green_preflight.py` : 23 tests réussis, y compris fusion Docker Compose réelle et fixtures synthétiques.
- `ruff check` sur les trois fichiers Python touchés : aucun diagnostic.

**Ce préflight n'est pas encore invoqué par
`deploy_verified_release_cli.py`.** Le wrapper signé actuel ne connaît que
les trois fichiers Compose historiques et le déploiement in-place. Il reste à
matérialiser l'overlay depuis l'objet Git du SHA final, conserver un snapshot
durable des matériaux, relancer ce préflight immédiatement avant toute
mutation, confronter le `compose_digest` à une readiness V2 signée avec toutes
les preuves publiques, puis tester health, Cockpit, Nginx, rollback et C0 sur
le candidat final. Le contrôle présent ne ferme pas, à lui seul, la fenêtre
entre le préflight et un futur `compose up`. `mutation_allowed=false` dans son
résultat exprime cette limite. Aucun verdict `PRODUCTION_READY` ou
`GO_LIVE_READY` n'est produit par ce lot.
