# ADR-0046 — Manifeste de corpus servable lié au registre Nexus

- **Statut** : Accepté pour livraison coordonnée RAG → Nexus
- **Date** : 2026-08-30
- **S'appuie sur** : ADR-0002, ADR-0026, ADR-0035, ADR-0045

## Contexte

Le moteur RAG possède aujourd'hui les collections physiques et les artefacts
indexés, tandis que Nexus doit devenir l'autorité produit des ressources et de
leurs versions. Une collection ou un identifiant content-addressed interne ne
peut pas devenir une seconde identité documentaire. Nexus ne doit pas non plus
maintenir manuellement un second mapping `courseKey → collection`.

Les deux dépôts ont besoin d'un contrat versionné qui permette à Nexus de
demander un corpus exact et au moteur de prouver les versions de ressources et
chunks réellement utilisés. Le déploiement doit rester compatible avec le
runtime actuellement en production pendant la phase d'expansion.

## Décision

`nexus-contracts` reste l'unique autorité de schéma interservices. La version
`0.15.0` ajoute, sans rendre obligatoires les nouveaux champs des appels V1
existants :

- `ResourceRegistryBootstrap` pour l'export gouverné initial ;
- `ServableCorpusManifest` pour lier corpus, année scolaire, version de
  programme, scope, ResourceVersion, hash de contenu, chunk et locator ;
- `ServableCorpusIndex` pour annoncer uniquement le manifeste actif N et, au
  plus, N-1 avec une date de retrait explicite ;
- les bindings optionnels de manifeste dans `RetrievalRequest`, puis les
  identités canoniques complètes et atomiques dans `RetrievalResult` ;
- `RetrievalError` pour les échecs internes stables et non sensibles ;
- un binding court `request_sha256 + manifest_sha256` dans l'enveloppe
  d'identité interne.

Les schémas gardent le namespace `$id` historique `v0.5`, conformément à
ADR-0026. Leur package SemVer et leur SHA-256 détaché sont scellés dans
`packages/contracts/schema/contracts.lock.json`. Le SHA est une preuve
d'intégrité, pas une signature cryptographique. L'authenticité de livraison
repose sur le commit RAG revu et piné par Nexus ; aucun secret de signature
nouveau n'est inventé dans ce lot.

La canonicalisation utilise JSON UTF-8, clés triées et séparateurs compacts.
Les artefacts exportés restent JSON lisible avec clés triées et newline final.
Le vecteur d'identité fixe rend les octets de signature vérifiables dans chaque
runtime consommateur.

## Identités canoniques

- `ingestion_control.resources.resource_id` devient `resourceId` Nexus ;
- `ingestion_control.artifacts.artifact_id` devient `resourceVersionId` Nexus ;
- `ingestion_control.artifacts.sha256` devient `contentSha256` ;
- `public.rag_artifacts.artifact_id`, égal au hash de contenu, reste une
  identité interne RAG et ne devient jamais un `resourceVersionId` ;
- `public.rag_chunks.chunk_id` et son locator identifient la preuve citée.

Un résultat qui fournit une partie de cette identité doit fournir tous les
champs. Un digest, une version, un hash ou une relation incohérente échoue
fermée.

## Propriété et livraison

Le dépôt RAG possède le manifeste du corpus effectivement servable. Nexus
possède le Resource Registry et la résolution
`courseKey + task/mode + role → corpusId`. Le manifeste RAG référence les
identités et le digest du Registry Nexus ; il ne redéfinit aucune ressource.

Ordre de livraison :

1. publier le package et l'export bootstrap additifs ;
2. importer et sceller le Resource Registry dans Nexus ;
3. publier côté RAG les manifests N/N-1 liés au Registry ;
4. déployer et vérifier les endpoints RAG rétrocompatibles ;
5. seulement ensuite déployer Nexus avec les digests pinés.

Une incompatibilité de package, schéma, Registry ou manifeste rend la
capability RAG indisponible. Elle n'autorise ni collection historique implicite
ni génération non groundée silencieuse.

## Conséquences

- aucune migration DB n'est introduite par ce contrat ;
- `/search/v2` actuel reste compatible tant que les nouveaux bindings ne sont
  pas encore exigés par le cutover coordonné ;
- le futur runtime devra produire les identités canoniques complètes, sans DTO
  local divergent ;
- année scolaire et version de programme restent explicites sans revendiquer
  la couverture candidat libre ou une modélisation de langue non approuvée ;
- le texte des chunks, les vecteurs, les chemins locaux, les DSN et les PII ne
  figurent jamais dans les manifests.

## Rollback

Avant activation Nexus, retirer la publication des nouveaux artefacts suffit :
les champs existants sont restés compatibles. Après activation, conserver N-1
jusqu'à `retireAt` et repiner Nexus vers ce manifeste revu. Aucun rollback ne
peut réintroduire un mapping manuel course→collection ou confondre UUID de
ResourceVersion et hash RAG.
