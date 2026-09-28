# Plan gouverné — complément HGGSP après V4 DI

**Statut : préparation hors serveur.** Ce document ne constitue pas une
autorisation de staging. L'autorisation proposée dans
`docs/reports/go_live/authorizations/proposed/` est inactive ; une PR
d'activation distincte, approuvée au HEAD exact puis fusionnée, devra nommer
les opérations, les images par digest et leurs preuves de provenance.

## Identités et frontière

- V4 reste propriétaire des neuf collections DI, des 405 placements et des
  263 artefacts déjà publiés. Son manifeste et son mapping de sujets restent
  inchangés.
- `production-profile-gate-2026-2027-v5-hggsp` est propriétaire de
  `rag_nexus_hggsp_premiere_specialite` et de
  `rag_nexus_hggsp_terminale_specialite` seulement : 39 + 35 placements et
  52 artefacts disjoints des 263 V4. Le nombre de chunks est recalculé depuis
  les manifests scellés et confronté au produit.
- Son manifeste est
  `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json`
  (`8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`).
  Le registre mixte explicite est
  `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json`
  (`59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`).
  Son existence dans le dépôt n'active aucun runtime.
- Les 52 PDF ont été rescannés : 52 statuts PII `CLEARED`, zéro détection.
  La preuve du complément nomme la preuve PII V4 scellée
  (`33e3fbfb943ffded360d2db254061edebe8ccff9e08b7509ebcdf4cd305ca700`)
  et conserve la chaîne de revue signée de la population source de 315.
- La revue V4 #262, HEAD
  `079461659b60f8a8ce9458145a199599ad822bbc`, demeure ouverte, inchangée
  et non fusionnée. Les 74 jobs HGGSP V4 gardent leur état et leur empreinte
  jusqu'à la vérification indépendante de la publication successeur.
- La base historique `ragdb` reste hors périmètre. Aucune bascule `current`,
  aucun service de production ni exposition publique ne découle de ce plan.

## Phase 0 — autorité et prévol, sous une future PR distincte

1. Fusionner la PR de **production de release**, puis vérifier que le checkout
   opérateur est exactement le `main` qui contient les octets scellés. Relire
   par les chargeurs canoniques le manifeste successeur, le mapping sujets,
   les deux profils, l'inventaire, le reçu PII, les mappings niveau et type de
   document et le registre mixte version 2. Refuser toute divergence de SHA,
   toute troisième collection, toute intersection d'artefacts ou de
   placements avec les neuf collections V4.
2. Produire hors hôte une nouvelle image Worker B à partir de ce `main` et
   enregistrer son digest, le commit source et l'inventaire de provenance.
   Le chargeur du registre mixte étant nouveau, l'image précédente n'est pas
   une preuve de ces octets. Construire et épingler également l'image du
   moteur de retrieval qui embarque le chargeur v2 avant d'envisager le
   registre mixte comme cible de runtime. Ne rien reconstruire sur
   `nexus-prod`.
3. Soumettre une **nouvelle autorisation de staging** liée au manifeste
   successeur, au registre mixte, à ces images et à leurs SHA. La placer à son
   chemin actif uniquement dans cette PR d'activation. Son approbation au
   HEAD exact et sa fusion sont nécessaires avant toute mutation. L'autorité
   borne la cible à `ragdb_profile_gate_v4`, à deux collections et à 74
   placements ; elle interdit d'adopter ou republier les 405 V4 et de toucher
   aux 74 anciens jobs HGGSP V4 pendant la publication du complément.
4. Au prévol de chaque étape, mesurer la base historique et le produit DI,
   relire les 74 jobs V4 et leur empreinte
   `fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31`,
   vérifier #262 encore ouverte au même HEAD approuvé et refuser tout écart.
   Ne pas réutiliser les scripts V4 par simple changement de variables : ils
   sont liés à l'autorisation et aux attentes V4.

## Phase 1 — préparation du successeur

1. Émettre et signer une readiness **successeur** qui nomme le nouvel
   identifiant de release, le SHA du manifeste, l'image épinglée, la base
   dédiée et les deux collections. La vérifier avant chaque conteneur qui
   consomme la release. La readiness V4 reste en place.
2. Dériver deux autorisations r4 depuis les placements et les scopes de
   retrieval successeurs HGGSP, avec une autorité de noms et de SHA propre à
   cette lignée. Ces scopes doivent être distincts des scopes V4 HGGSP qui ne
   peuvent pas devenir actifs par accident : l'autorité de noms existante
   porte déjà les identifiants V4 `_v2`, et les nouveaux identifiants doivent
   être émis par un registre successeur HGGSP dédié. Relire leurs autorités puis les
   faire approuver sur une PR ouverte et au HEAD exact ; enregistrer les deux
   r4 par le CLI canonique et le rôle `ingestion_control_authority`.
3. Acquérir ou lier les 74 placements sous la **nouvelle** release, en
   vérifiant l'identité d'octets des 52 artefacts et l'absence de publication
   HGGSP préalable. Le registre mixte attribue chaque collection à un seul
   manifeste ; aucune autorisation V4 HGGSP n'est réemployée.
4. Produire une proposition de revue batch bornée aux 74 placements et à
   la chaîne PII du successeur. Attendre la décision humaine sur une PR
   distincte, ouverte et au HEAD exact ; enregistrer ensuite la revue,
   produire les 74 attestations et créer 74 nouveaux jobs de publication
   nommant l'identifiant du successeur. Vérifier zéro job supplémentaire et
   l'empreinte inchangée des 74 anciens jobs V4.

## Phase 2 — publication et vérification

1. Lancer Worker B sous l'image et la readiness épinglées, avec une liste
   positive contenant les deux seules collections HGGSP. Vérifier son
   claim scope avant tout job. La limite de cadence et l'arrêt sûr `75`
   s'appliquent ; une reprise exige un nouveau prévol et une action opérateur,
   jamais une boucle automatique.
2. Vérifier indépendamment, en lecture seule, la cible successeur
   (2 collections, 52 artefacts, 74 placements, chunks recalculés), puis
   l'union mixte (11 collections, 315 artefacts, 479 placements, 8 268
   chunks). Comparer les 405 placements V4 et leurs chunks aux preuves DI
   avant publication ; sonder le retrieval sur les deux scopes HGGSP et les
   neuf scopes V4. Revérifier `ragdb` et les 74 anciens jobs V4 inchangés.
3. Archiver le journal Worker B, le résultat des sondes, les empreintes des
   registres et le contrôle de clôture. Aucun conteneur ni preuve n'est
   supprimé par le contrôle.

## Phase 3 — retrait V4 HGGSP et #262, décision ultérieure

Après **succès** de la vérification indépendante, une autorisation et une
revue distinctes pourront permettre l'annulation canonique des 74 anciens
jobs HGGSP V4 et l'invalidation motivée de leurs attestations. Elles devront
lier exactement la liste et l'empreinte préservées, prouver la publication
équivalente sous le successeur, conserver l'historique et refuser tout SQL
manuel. Le contrôle de fermeture V4 attend encore 479 publications V4 ; son
traitement de la substitution exigera un correctif et une décision propres.
La fermeture ou la fusion de #262 n'appartient ni à ce lot ni à la publication
du complément. Un éventuel déploiement de production et le `current switch`
exigent ensuite leurs propres promotions, readiness et autorisations.
