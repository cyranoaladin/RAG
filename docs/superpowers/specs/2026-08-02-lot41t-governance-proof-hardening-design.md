# LOT41T — Durcissement fail-closed des preuves de gouvernance

Date : 2026-08-02

## Contexte et objectif

Les revues postérieures aux LOT38 et LOT39bis ont démontré que deux diagnostics
locaux attribuent une autorité à des fichiers modifiables dans le dépôt. Le
garde de transition accepte une approbation GitHub décrite en YAML et des états
`quality/gate/review` déclarés par le même appelant que le package. L'audit
golden peut de son côté produire `HUMAN_REVIEW_APPROVED` lorsque le manifeste,
le paquet et leurs SHA-256 ont été fabriqués ensemble.

Ces chemins sont dormants : aucun runtime, publisher, accès PostgreSQL ou
écriture pgvector ne les appelle, et toutes les capacités du pilote restent à
`false`. Leur signal de gouvernance est néanmoins trompeur. LOT41T retire donc
toute autorisation fondée uniquement sur des artefacts du dépôt, corrige les
deux défauts secondaires confirmés et consigne les errata historiques. Le
projet reste `GO_LIVE: NO_GO` après ce lot.

## Décision

LOT41T applique une frontière simple : un digest recalculable prouve
l'intégrité d'un contenu, jamais l'identité ni l'autorité de son auteur. Aucun
fichier YAML, modèle Python fourni par l'appelant, commentaire GitHub générique
ou chaîne d'état ne peut désormais ouvrir une transition.

`evaluate_authorization()` conserve ses contrôles de structure et de cohérence
afin de fournir des diagnostics précis, puis refuse toute approbation locale
cohérente avec `approval.trusted_channel_unavailable`. Pour
`publish_reviewed_chunks`, il refuse en plus le package avec
`package.scope_attestation_unavailable` et
`package.trusted_attestations_unavailable`. Les champs historiques du package
restent des revendications inspectables ; `passed/passed/reviewed` n'a plus
aucune valeur d'autorisation. Cette fermeture vaut pour les entrées YAML comme
pour les objets construits en mémoire et ne dépend pas du recalcul de leurs
digests.

L'audit golden reste un diagnostic local sans réseau. Un manifeste `pending`
propre produit `HUMAN_REVIEW_PENDING`. Un ancien manifeste `approved` peut
encore être contrôlé comme revendication historique : même si les 255 cas, les
quatre attestations, les dates et tous les SHA concordent, il produit
`HUMAN_REVIEW_PENDING` avec
`human_review.trusted_channel_unavailable`, jamais
`HUMAN_REVIEW_APPROVED`. Une revendication incohérente reste
`HUMAN_REVIEW_INVALID`. Le manifeste canonique est remis à `pending`; le paquet
historique est préservé comme trace, sans autorité.

Le libellé `Couverture: 39 notions` devient
`Cardinalité du scope taxonomique: 39 notions`. Il décrit uniquement ce que
l'audit mesure et ne prétend plus démontrer la présence de ressources
pédagogiques substantielles. Enfin, l'entrypoint du CLI golden transmet
explicitement `sys.argv[1:]` à `main`, de sorte qu'un argument inattendu rende
le code `2` sans lancer l'audit.

## Frontière de confiance future

LOT41T n'ajoute ni clé publique auto-déclarée, ni callback fourni par
l'appelant, ni accès réseau dans `rag-pedago`. Ces variantes déplaceraient la
forge sans créer d'autorité indépendante.

Avant toute ouverture des capacités de validation par LOT41A, un adaptateur
hors du diagnostic local devra fournir un readback GitHub authentifié et borné.
Il devra vérifier au minimum :

- une review formelle `APPROVED`, non dismissed ni révoquée ;
- le dépôt exact, la base `main`, la PR et son head exact ;
- un reviewer issu d'un registre d'autorité et distinct de l'auteur ;
- un challenge canonique liant le digest d'autorisation ou de spécification,
  le SHA-256 du paquet et la cardinalité attendue ;
- la pagination exhaustive, la chronologie et l'échec fermé de toute réponse
  absente, ambiguë ou invalide.

LOT42 vérifiera ce readback avant toute consommation de document réel. Sa
publication devra parallèlement obtenir d'un ledger autoritaire trois
attestations distinctes `quality`, `gate` et `review`. Le JSON canonique du
manifeste définit les octets effectivement proposés à la publication ; leur
SHA-256 est exactement `PublicationPackage.content_sha256`. Chaque attestation
porte ce même digest ainsi que le scope et l'ensemble d'items correspondants.
Une différence d'octets, de digest, de scope ou d'items entraîne un refus. Le
manifeste porte l'environnement, le tenant, la collection, la matière, l'année
scolaire et chaque item publié ; tous ces champs correspondent à la requête
autorisée. Après unanimité, le responsable produit la signature Ed25519
détachée déjà exigée par le plan de finalisation ; le publisher vérifie la clé
publique autorisée et non révoquée avant toute écriture. Si ces preuves
traversent un service, elles passent par API ou par `nexus-contracts` avec
SemVer et ADR, jamais par import interservice.

L'adaptateur et le ledger ne sont pas implémentés dans ce lot parce qu'aucun
consommateur runtime n'existe encore et qu'aucune autorité humaine ou clé
privée n'a été fournie. Leur absence est un refus explicite, pas une dette
silencieusement tolérée.

## Migration et errata

Le commentaire historique de la PR #82 ne constitue pas une approbation des
octets finaux : il précède le commit du paquet approuvé, ne contient ni digest
ni head et n'est pas une review GitHub formelle. Le rapport LOT39bis reçoit un
erratum qui retire le verdict d'approbation humaine et le remplace par une
revendication historique non authentifiée, désormais en attente. Le paquet de
revue conservé reçoit lui-même un bandeau daté portant ce statut et renvoyant à
l'erratum LOT41T ; son SHA-256 est donc recalculé et documenté comme digest de
la trace corrigée, jamais comme signature ni comme approbation.

Le rapport LOT38 reçoit un erratum analogue : ses tests prouvaient la cohérence
interne d'une revendication GitHub et d'un package, mais ne réfutaient ni la
fabrication de l'autorité, ni le changement de scope, ni les attestations
auto-déclarées. Aucun résultat CI historique n'est supprimé ou réécrit ; les
corrections sont ajoutées avec leur date et leur portée.

Le fixture ayant déclenché GitGuardian contient le SHA-256 exact d'un autre
fixture, pas un secret. LOT41T évite toute suppression globale du détecteur et
toute allowlist large. L'incident historique devra être classé comme faux
positif dans GitGuardian ; cette action externe ne peut pas être simulée par le
dépôt.

## Tests et preuves

Le développement suit quatre cycles TDD :

1. prouver qu'une approbation YAML ou en mémoire parfaitement cohérente reste
   refusée, y compris pour les opérations sans package ;
2. prouver qu'un package `passed/passed/reviewed`, un digest recalculé ou un
   contenu hors scope ne peut jamais autoriser une publication sans
   attestations externes ;
3. prouver qu'un manifeste et un paquet golden forgés ensemble ne produisent
   jamais `HUMAN_REVIEW_APPROVED`, puis remettre le canonique à `pending` ;
4. verrouiller le libellé de cardinalité et l'exécution directe du CLI avec un
   argument inconnu.

Les vérifications finales couvrent les suites ciblées, l'ensemble des tests de
`rag-pedago`, Ruff, mypy, les audits Make et gouvernance, puis la CI locale
racine. Le rapport `docs/reports/lot_41t_governance_proof_hardening.md`
consigne les résultats frais et maintient `GO_LIVE: NO_GO`.

Après le squash-merge vérifié sur `main`, LOT41T répond dans chacun des six fils
techniques encore ouverts des PR #81 et #82 avec le lien du correctif et sa
preuve, puis résout chaque fil et relit son état GraphQL. Le commentaire
GitGuardian de la PR #81 reçoit séparément la preuve du faux positif ; seul le
tableau de bord GitGuardian peut classer l'incident lui-même comme ignoré.

## Hors périmètre

LOT41T ne crée aucun publisher, aucune migration, aucun accès à GitHub depuis
le service, aucune clé privée, aucun nouveau contrat cross-service et aucune
écriture de données. Il ne modifie ni `rag-engine`, ni le Cockpit, ni
`packages/contracts`. Il ne lève aucun verrou et ne transforme pas une ancienne
validation humaine en preuve nouvelle.

## Retour arrière

Le retour arrière restaure uniquement les anciens diagnostics permissifs et
est donc interdit après découverte d'une régression : l'état sûr est le refus.
Si une correction opérationnelle du lot doit être annulée, les capacités
restent à `false`, le manifeste golden reste `pending` et les consommateurs
futurs doivent continuer à traiter l'absence d'autorité comme un blocage.
