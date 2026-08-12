# Lot multi-niveaux 2026-2027 — ingestion staging gouvernée

## Décision et périmètre

Le lot étend sans la reconstruire la chaîne Search-Ready de Troisième à dix
collections exact-grade. Il reste strictement limité au staging local
`LocalGitHub` : aucune approbation humaine ou production n'est fabriquée,
aucun public writer n'est activé, aucune mutation de PR #96 n'est réalisée et
PR #95 reste Draft.

Le catalogue H2-E parent reste immuable. Un descriptor append-only ajoute
seulement deux placements exacts sur des octets déjà scellés : Français
Première et Physique-Chimie Terminale. Aucun PDF, vecteur ou poids modèle
n'entre dans Git.

## Autorités et preuves

- catalogue parent :
  `301c0dcce4e49cd9b6e524708bde82b262a09b05bd52e0431233813ecf8ae04b` ;
- corpus manifest :
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- placement catalog :
  `095ca37cc4c2126d06b77106f9f1663d4f5ad881ae4952dbf5b951477fd54c39` ;
- descriptor catalogue vNext :
  `cc12e73643bcb36102a992982e756356b34a908c60d0d742ea48d2ee61cfd99b` ;
- autorité catalogue effective :
  `5cc8e30b81157fbc1789a0b82ad38cd3673276167890bced55151cbac1523c2f` ;
- inventaire candidats :
  `86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300` ;
- currentness artifact-bound :
  `2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122` ;
- PII ciblé v5 externe :
  `46d6c738ebc230dedb95ada2d07bd17a0907d75ee8aedcd556d27027ad50daa8` ;
- preflight extraction/chunking/profile/programme externe :
  `e440745c7bc04b5398863a80bf6d4ad8128fc8726d0615d6947412f8d557cf5f` ;
- rights registry :
  `e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff` ;
- programme registry V3 :
  `9822f795f7c293618305a7ed9ad9087f68a96267415472fc0c3e39d3c89aa58c` ;
- staging profile manifest :
  `47c86091687fc7a4a7e6d76aa8ff65eb02f3ab861dd15c7600dc93e6eb98b753` ;
- release eligibility :
  `2a411b4ffc3d46c13bfd5178ed7345af18d6a94a1b2568aa0a4cdb3953e7740b` ;
- aggregate release :
  `d8ee6703d3497e34e6e5273bee00da90ab9c82094f0f9a1257eef0ff91da1828`.

Le modèle d'embedding est
`intfloat/multilingual-e5-large`, dimension 1024, inventaire
`e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a`.
Le reranker est `cross-encoder/ms-marco-MiniLM-L-6-v2`, inventaire
`bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1`.
Les deux artifacts sont vérifiés et chargés hors ligne ; aucun fake vector
n'est accepté.

## Inventaire, gates et ingestion par collection

`RIGHTS_CLEAR` mesure les candidats résolus par le registre fermé. Le
preflight d'extraction/chunking ne s'exécute que sur l'intersection
`CURRENT ∩ PII_CLEAR`, d'où `EXTRACTABLE = RELEASE_ELIGIBLE` ici. Chaque
ligne Search vaut trois requêtes naturelles réussies et la discoverability
porte sur tous ses artifacts release.

| Collection | Candidats | Current | PII clear | Rights clear | Extractable | Release eligible | Review required | Documents ingérés | Placements | Chunks | Search smoke | Discoverability |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rag_nexus_maths_seconde_tc` | 6 | 1 | 5 | 6 | 1 | 1 | 5 | 1 | 1 | 44 | 3/3 | 100 % |
| `rag_nexus_francais_seconde_tc` | 8 | 2 | 8 | 8 | 2 | 2 | 6 | 2 | 2 | 44 | 3/3 | 100 % |
| `rag_nexus_maths_quatrieme_tc` | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 22 | 3/3 | 100 % |
| `rag_nexus_francais_quatrieme_tc` | 9 | 1 | 9 | 9 | 1 | 1 | 8 | 1 | 1 | 20 | 3/3 | 100 % |
| `rag_nexus_maths_premiere_gen_specialite` | 12 | 1 | 12 | 12 | 1 | 1 | 11 | 1 | 1 | 38 | 3/3 | 100 % |
| `rag_nexus_nsi_premiere_specialite` | 10 | 2 | 6 | 10 | 1 | 1 | 9 | 1 | 1 | 19 | 3/3 | 100 % |
| `rag_nexus_francais_premiere_tc` | 84 | 1 | 83 | 84 | 1 | 1 | 83 | 1 | 1 | 38 | 3/3 | 100 % |
| `rag_nexus_maths_terminale_gen_specialite` | 8 | 1 | 8 | 8 | 1 | 1 | 7 | 1 | 1 | 57 | 3/3 | 100 % |
| `rag_nexus_nsi_terminale_specialite` | 11 | 1 | 8 | 11 | 1 | 1 | 10 | 1 | 1 | 19 | 3/3 | 100 % |
| `rag_nexus_pc_terminale_specialite` | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 58 | 3/3 | 100 % |

Totaux : 150 artifacts candidats, 151 placements candidats, 150 objets
physiques ; 11 artifacts/placements release-eligible, 139 non-éligibles avec
reason codes nommés, zéro unevaluated. Currentness : 12 `CURRENT`, 138
`REVIEW_REQUIRED`. PII : 150/150 scannés, 141 `CLEARED`, 9 quarantainés,
zéro échec scanner/extraction. La ressource Python NSI Première current
`447bdee…` est quarantainée et n'entre pas dans la release.

Le preflight final couvre 11/11 artifacts, 137 pages et 359 chunks : couverture
de pages 100 %, chunks vides 0, metadata page nulles 0, chunks E5 oversized 0,
maximum 384 tokens réels.

## Programmes, Quatrième et Seconde

- `Niveau.quatrieme` est ajouté au contrat versionné, aux six schémas JSON et
  aux contrats cockpit générés.
- Les deux collections et taxonomies exact-grade Quatrième sont créées depuis
  les références officielles, programme
  `BOEN_special_11_2018-07-26_aj_2020`.
- La voie des collections Seconde est normalisée à `generale` et alignée avec
  profils, programme registry et scopes.
- Maths Seconde utilise `BOEN_14_2026-04-02_MENE2602914A` ; Français Seconde
  utilise `BOEN_special_1_2019-01-22`.
- Maths Première utilise `BOEN_14_2026-04-02_MENE2602917A` ; NSI Première
  résout indépendamment `BOEN_special_1_2019-01-22`.
- Maths, NSI et Physique-Chimie Terminale utilisent leurs références
  `BOEN_special_8_2019-07-25` exactes.

## Pipeline réel, réconciliation et idempotence

Le principal E2E utilise deux PostgreSQL/pgvector jetables et une campagne
`LocalGitHub` staging : dix grants LOT41A étroits, onze jobs Worker A vers
`NEEDS_REVIEW`, onze reviews/attestations LOT42 exactes, onze jobs Worker B
vers `RETRIEVAL_ELIGIBLE`, puis pgvector. Aucun publisher manuel et aucun stub
d'autorisation n'est utilisé.

Réconciliation aggregate ↔ DB :

- missing/unexpected artifacts : 0/0 ;
- missing/unexpected placements : 0/0 ;
- missing/unexpected chunks : 0/0 ;
- wrong chunk SHA/page/model/vector dimension : 0/0/0/0 ;
- orphan authority pins et missing attestation pins : 0/0 ;
- fake vector rows : 0.

Le batch complet de onze `publication_resume` est remis en queue et rejoué.
Chaque outcome porte `embedded=false` ; les compteurs restent 11 artifacts,
11 placements, 359 chunks/vecteurs. Duplicates artifact/placement/chunk/vector
et nouveaux embeddings au second run : tous 0.

Les CLI dédiées chargent toutes les autorités path+digest avant le PostgreSQL
control et refusent un environnement autre que `rehearsal`. Un E2E subprocess
réel couvre dans une même campagne Maths Quatrième et NSI Première : Worker A,
LOT42 et Worker B E5 CPU passent sans SHA métier codé dans Python.

## Retrieval réel

Dix scopes V2 nommés et indépendamment révocables distinguent cible élève et
curriculum evidence. Le registry n'utilise ni wildcard ni collection fournie
par le client. Les rôles `teacher` lisent `internal`; le rôle `student` reste
refusé.

Le vrai `api_v2:app` est démarré par uvicorn sur socket localhost. Son lifespan
vérifie DB, aggregate release, E5 et reranker offline. L'acceptance exécute :

- picker signé exact pour les dix scopes ;
- readiness vraie collection par collection ;
- 30/30 requêtes naturelles, trois par collection, zéro résultat vide ;
- concepts attendus dans le top hit, citation/page/source/path/droits exacts ;
- 11/11 artifacts découverts, dont les deux artifacts Français Seconde ;
- tentative scope Maths avec payload Français refusée HTTP 403 ;
- cross-collection leaks et wrong-scope leaks : 0.

Le seuil reranker canonique reste `1.90`. Une première probe « raisonnement et
démonstration » a produit un logit 0,423 car la ressource dédiée est
`REVIEW_REQUIRED`; elle a été remplacée par une question portant sur le
programme release-eligible, sans modifier le seuil.

## NSI historique

Diagnostic read-only de la base `rag_pgvector` historique :

- NSI Première : 0 ligne existante ; 19 chunks dans la nouvelle release
  gouvernée ; 0 ligne legacy ;
- NSI Terminale : 24 lignes existantes pré-migration 004 ; 19 chunks dans la
  nouvelle release gouvernée propre ; 24 lignes legacy ;
- `NSI_LEGACY_CERTIFIED_AS_GOVERNED=false`.

Aucune ligne historique n'est supprimée, migrée ou certifiée rétroactivement.

## Activation, sécurité et état externe

Les huit collections auparavant dormantes sont activées canoniquement après
réconciliation exacte ; les deux collections NSI étaient déjà instanciées.
Les snapshots cockpit reflètent mécaniquement les mêmes états. Aucune autre
collection n'est activée. Le gate runtime V2 exige `readiness=true` ; une
release absente, driftée ou non réconciliée reste fermée.

- `PUBLIC_WRITER=false` ;
- `PRODUCTION_DEPLOYMENT=false` ;
- `PR96_UNCHANGED=true` ;
- `TRUSTED_HUMAN_REVIEW=FAIL_EXPECTED_DRAFT` ;
- GitGuardian 36021438 et 36021439 : findings historiques à dismissal humain,
  sans réécriture de l'historique.

## Vérifications

- ingestion + idempotence + vrai HTTP/E5/reranker : `1 passed` en 402,26 s ;
- CLI Worker A/B multi-collections réel : `1 passed` en 61,82 s ;
- revue indépendante finale : APPROVE, aucun finding Critical/Important ;
- CI locale canonique : PASS, 16 cibles sur 16, zéro échec ;
- CI GitHub native : à consigner après le push du HEAD final.
