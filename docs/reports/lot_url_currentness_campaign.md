# Campagne d'actualité des URL — 111 URL Eduscol

> Périmètre strict : les 111 URL distinctes des 2451 contenus institutionnels.
> Ce n'est **pas** `FULL_URL_CURRENTNESS`.

## 1. Identité gelée avant la première requête

```
CURRENTNESS_CAMPAIGN_RUN_ID=422356d3f7f51f93ea9a8dbff7c37fac13586334bb32e3f30eb4297ab3c5a139
CURRENTNESS_CAMPAIGN_CODE_COMMIT=3577ae4eb47b49b109feaf70f2ccd2cef1977bf2
CURRENTNESS_CAMPAIGN_GIT_DIRTY=false
CURRENTNESS_REQUEST_POLICY_ID=NEXUS-URL-CURRENTNESS-REQUEST-POLICY-V1
CURRENTNESS_REQUEST_POLICY_SHA256=ca0fac08c10e9ed6550105d8bcd60d58c40927b802f2649d4bcfaf58cd19ff5e
EDUSCOL_URL_SET_COUNT=111
EDUSCOL_URL_SET_SHA256=331d49651762d3959b3a0b0bc475a4a3c23e983c6c58f6c5debe088d8803069e
CATALOGUE_AUTHORITY_SHA256=095ca37cc4c2126d06b77106f9f1663d4f5ad881ae4952dbf5b951477fd54c39
CORPUS_MANIFEST_SHA256=9449ba6c675b7b0195e7c7e97ae8fd5d1204df7bc8d27a2bdef3a10da9fb258a
```

Politique : `connect=10s`, `read=20s`, `max_redirects=5`, `retry=2` sur
`{429,500,502,503,504}`, `max_response=1 MiB`, `concurrency=1`,
`1 req/s/hôte`, TLS vérifié, aucune authentification, aucun contournement,
`HEAD` puis `GET` borné, redirections suivies à la main pour en garder la chaîne.

## 2. Résultat

```
EDUSCOL_DISTINCT_URLS=111    EDUSCOL_URLS_ATTEMPTED=111    EDUSCOL_URLS_UNACCOUNTED=0
RAW_DISTINCT_URLS=111        REQUEST_DISTINCT_URLS=111     URL_NORMALIZATION_COLLAPSES=0

HTTP_2XX=1   HTTP_3XX=0   HTTP_4XX=110   HTTP_5XX=0   NETWORK_ERRORS_FINAL=0
REDIRECTED_URLS=0            FINAL_DISTINCT_URLS=111

DIRECT_RESOURCE_URLS=0       NAVIGATION_URLS=111       UNKNOWN_ROLE_URLS=0
DIRECT_CONTENT_MATCH=0       DIRECT_CONTENT_MISMATCH=0

NAVIGATION_PAGE_REACHABLE=1  UNVERIFIABLE_WITH_EVIDENCE=110   URL_NOT_AVAILABLE=0

EDUSCOL_VERIFIED_CURRENT=0
EDUSCOL_CURRENTNESS_UNVERIFIED=111
EDUSCOL_CURRENTNESS_ERRORS=0
EDUSCOL_CURRENTNESS_UNACCOUNTED=0

EDUSCOL_ARTIFACT_URL_RELATIONS=2542
RELATIONS_WITH_OBSERVATION=2542    RELATIONS_WITHOUT_OBSERVATION=0

EDUSCOL_CURRENTNESS_ACCOUNTED_PERCENT=100
EDUSCOL_CURRENTNESS_VERIFIED_PERCENT=0.0
```

Les deux pourcentages sont publiés séparément, et ils ne disent pas la même
chose : **tout est compté, rien n'est vérifié**.

## 3. Le fait dominant : 110 refus serveur

`eduscol.education.gouv.fr` (107 URL) et `www.education.gouv.fr` (3) rendent
**403** à un agent non navigateur, en `HEAD` comme en `GET`. Seul
`sti.eduscol.education.fr` répond `200`.

Ce 403 est enregistré comme `UNVERIFIABLE_WITH_EVIDENCE`, jamais comme
`STALE` : ne pas pouvoir vérifier n'est pas vérifier le contraire.

**Aucun contournement n'a été tenté.** Se faire passer pour un navigateur
aurait produit des chiffres, pas une preuve — et aurait violé la protection que
le site a explicitement posée. Lever ce blocage relève d'un accord avec
l'institution ou d'un canal autorisé, pas d'un en-tête falsifié.

## 4. Aucune URL directe de document — fait structurel

```
DIRECT_RESOURCE_URLS=0   NAVIGATION_URLS=111
```

Le `url_source` du catalogue est **toujours** une page de navigation
institutionnelle : 109 URL sans extension, 2 en `.htm`, zéro `.pdf`. Aucune
comparaison d'octets n'était donc possible, même sans les 403 — et comparer
l'empreinte d'une page HTML à celle d'un PDF aurait été une comparaison entre
deux choses différentes.

Conséquence à retenir : **la preuve d'actualité par identité de contenu ne peut
pas venir de ce catalogue.** Elle exigerait une URL directe de document, que
les autorités reçues ne portent pas.

## 5. Ce que la campagne n'a pas décidé

Les 54 contenus multi-URL conservent toutes leurs relations ; aucun verdict par
précédence. Les 21 contenus multi-statuts conservent leurs statuts intacts :
actualité et `statut_source` sont deux dimensions séparées.

```
SERVING_SEMANTICS=UNDEFINED_PENDING_AUTHORITY
```

## 6. Un compteur que j'ai dû corriger

La première sortie annonçait `RELATIONS_WITH_OBSERVATION=2929` contre un
dénominateur de 2542. Je comptais les **lignes de preuve** et non les paires
distinctes contenu×URL : un même contenu peut être décrit par plusieurs lignes
de catalogue portant la même URL sous des scopes différents. Le dénominateur
était gonflé et la couverture mentait. Corrigé — 2542 sur 2542.

## 7. Découverte pour les 79 hors catalogue

Autorités examinées, dans l'ordre : métadonnées Drive, manifestes par niveau et
par scope, `corpus.sha256`, `metadonnees-exports.sha256`, catalogue complet,
champs `source_url` déjà gouvernés du dépôt.

```
OUTSIDE_CATALOGUE_TOTAL=79
DIAGNOSTICS      38  → FOUND=0  NOT_FOUND=38
INTERACTIVES     37  → FOUND=0  NOT_FOUND=37
COMPLEMENTS       3  → FOUND=0  NOT_FOUND=3
DOCUMENTATION     1  → FOUND=0  NOT_FOUND=1

OUTSIDE_CATALOGUE_URL_EVIDENCE_FOUND=0
OUTSIDE_CATALOGUE_URL_EVIDENCE_NOT_FOUND=79
OUTSIDE_CATALOGUE_URL_UNACCOUNTED=0
OUTSIDE_CATALOGUE_IN_CORPUS_SHA256_MANIFEST=0
```

Faits qui expliquent le résultat : l'inventaire Drive ne porte **aucun champ
d'URL** ; les manifestes par niveau et par scope ne portent que
`sha256, taille_octets, chemin, objet_source` — pas d'URL ; et **aucun des 79
n'apparaît dans `corpus.sha256`**, qui ne couvre que le corpus Eduscol.

`NOT_FOUND` signifie ici « aucune preuve dans les autorités examinées », pas
« aucune URL n'existe ». Aucune recherche par ressemblance de nom de fichier
n'a été faite.

Aucune archive `.ggb` n'a été ouverte : l'analyse interne attend le gate de
réacquisition et les protections hostile-archive.

## 8. Portée

```
FULL_URL_DISCOVERY_COMPLETE=false
FULL_CURRENTNESS_COMPLETE=false
```

Les 2451 contenus institutionnels ont une provenance prouvée par empreinte ;
aucun n'a d'actualité vérifiée. Les 79 restent sans preuve d'URL dans les
autorités disponibles.
