# Plan gouverné — complément HGGSP après V4 DI

**Statut : PR d'activation candidate, sans opération serveur.** Ce document
ne constitue pas à lui seul une autorisation de staging. Le fichier actif
`docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json`
est inutilisable tant qu'il n'est pas présent, identique octet pour octet,
dans `origin/main` après approbation au HEAD exact et fusion de cette PR.

## Images et chaîne opérateur après fusion

- Provenance canonique : `production-image-provenance.yml`, run
  `36633288414`, tentative `1`, artifact `11062997847` (ZIP
  `4789b260c03c0cd178459e148223a506cc72244ba7ca763f967aa1e76a25c946`).
  L'inventaire a le SHA-256
  `5e8c0332d87552a6df0804add10abbbe7f6b18682c5255c5a258ccfd047da767`.
  Commit source des images : `a9e3701965503d2862a248c46fd7e7e175058c8f`
  (arbre `68a4f905a4e42faeaf7671b1fb4016643ede921f`), qui porte #271
  (migration 020, adoption V2) et #273 (Worker B pour V5). Le futur commit
  d'activation est la fusion de cette PR ; il n'a pas à égaler ce commit.
- Worker B :
  `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf`.
  Retrieval :
  `ghcr.io/cyranoaladin/rag-ingestor@sha256:11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf`.
- Octets exécutés : le CLI d'adoption V2, Worker B et `ingestor.*` viennent
  de l'image ; l'orchestrateur, le vérificateur, le prévol, le dérivateur de
  DSN, la migration 020, le runner et le provisionneur adopter viennent du
  checkout fusionné (monté en `/repo` ou exécutés sur l'hôte). Aucun de ces
  derniers n'est requis dans l'image : pas de nouveau build.
- Première action opérateur après fusion : signer localement la readiness
  successeur avec
  `scripts/go_live/sign_staging_hggsp_successor_readiness.sh`, sous la clé
  privée gardée hors du dépôt. Aucune graine n'est lue avant le contrôle
  d'autorisation fusionnée. Vérifier les deux fichiers signés.
- Ensuite, `scripts/go_live/staging_hggsp_complementary.sh run` exécute dans
  cet ordre : `successor_readiness_install`, `successor_preflight`,
  `successor_control_schema_020_and_adopter_role`,
  `successor_scope_authorization_registration_r4`,
  `successor_sealed_ingestion_or_binding`,
  `successor_batch_review_proposal`. Ce dernier s'arrête obligatoirement pour
  une revue batch humaine distincte. Une reprise explicite, après revue
  approuvée au HEAD exact, permet `successor_batch_review_record`,
  `successor_attestations`, `successor_publication_job_enqueue`,
  `successor_worker_b_publication`, `successor_independent_verification`.
- Avant l'enregistrement r4, renseigner `SCOPE_REVIEW_PR` et
  `SCOPE_REVIEW_HEAD` d'une revue humaine des deux artefacts r4, distincte de
  #262. Le script vérifie l'approbation live au HEAD exact. Le jeton GitHub
  de lecture gouverné doit être disponible pour chaque contrôle live.
- Le Worker B journalise et borne conjointement
  `claim_release_id=production-profile-gate-2026-2027-v5-hggsp` et
  `claim_scope=rag_nexus_hggsp_premiere_specialite,rag_nexus_hggsp_terminale_specialite`.
  Le filtre est appliqué dans la transaction de claim par la liaison
  `job → publication_attestation_id → publication_attestations.release_id`.
- Les deux scopes successeurs sont ceux livrés par #269 :
  `prod_hggsp_premiere_specialite_v3` et
  `prod_hggsp_terminale_specialite_v3`. Leurs autorités V4 historiques
  restent inchangées.

## Opération `successor_control_schema_020_and_adopter_role`

Cible : base `ragdb_profile_gate_v4`, schéma `ingestion_control`,
019 → 020 (`020_successor_control_resource_identity.sql`, octets de
`main`), rôle `ingestion_control_adopter`. Logique :
`scripts/go_live/hggsp_control_schema_020.py apply` sur l'hôte, sous le
compte administratif du conteneur PostgreSQL, qui n'est transmis à aucun
conteneur.

1. **Préflight en lecture seule, valable sur 019** : base et rôle
   administratif, tête 19 (ou 20 déjà présente : jamais rejouée), registre des
   migrations contigu et SHA-256 identiques aux fichiers, aucun job en cours
   ni sous bail, aucun conteneur worker actif, espace disque suffisant pour
   la sauvegarde. Les colonnes de 020 ne sont nommées qu'une fois prouvées
   présentes. Le prévol HGGSP (autorité fusionnée, #262 live, V4, 74 anciens
   jobs, `ragdb`) précède l'étape comme toutes les autres.
2. **Sauvegarde** `pg_dump -Fc` de la base cible, 0600 sous un répertoire
   0700, relue par `pg_restore --list`.
3. **Secret** (`/srv/nexus-staging/secrets/hggsp-adopter`, 0700 ; fichier
   0600, propriétaire vérifié, liens refusés), généré par `secrets` et
   CONSERVÉ avant le rôle : secret et rôle absents → création ; secret seul →
   réutilisé ; rôle et secret présents → connexion réelle exigée ; rôle
   présent sans secret, ou secret incohérent → **refus, aucune
   réinitialisation**. Jamais dans un argument, une sortie, un journal ni un
   fichier versionné.
4. **Migration** par `bootstrap_ingestion_control_schema.sh` (runner
   canonique, superutilisateur : propriété historique des tables),
   `lock_timeout` de 020 respecté : une contention est un arrêt explicite.
5. **Rôle** par `provision_ingestion_control_adopter_role.sh`, provisionneur
   CIBLÉ : aucun autre rôle n'est touché (pas de rotation, d'attribut ni
   d'appartenance). Le serveur ne reçoit qu'un vérificateur SCRAM calculé sur
   l'hôte, la journalisation des instructions étant coupée pour la
   transaction. **Effet global au cluster** : un rôle est créé (catalogue
   partagé) ; ses privilèges de données sont bornés à la base cible.
6. **DSN** : `staging_v4_role_env.py --adopter-only` écrit le seul
   `ingestion-control-adopter.env` (0600), sans relire ni réécrire les cinq
   fichiers existants.
7. **Vérifications** : connexion adopter réelle ; droits EFFECTIFS
   (appartenances, PUBLIC, fonctions `SECURITY DEFINER`, écriture produit,
   CREATE de schéma) ; empreintes des tables de contrôle identiques
   avant/après (colonnes 020 exclues) ; tête 20 et contraintes de 020 ;
   aucune adoption V2 créée. Les accès hérités de PUBLIC hors mandat (CONNECT
   sur d'autres bases, lecture produit) sont **rapportés**, jamais corrigés
   par un `REVOKE` global.

Reprise : chaque exécution repart de l'état réel (marqueur ignoré). Fichier
secret, DDL et DSN ne sont pas une transaction atomique : l'ordre 3 → 5
empêche un rôle utilisable sans secret conservé. Rollback 020 → 019 : runner
canonique, refusé dès qu'une adoption V2 ou une valeur `successor_*`
existe ; il laisse le rôle, son secret et le fichier DSN en place (état
résiduel à documenter, aucune suppression automatique). Aucun rollback
automatique après une panne de dérivation.

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

## Phase 0 — prérequis accomplis et gardes à maintenir

1. La PR de **production de release** est fusionnée. Le checkout opérateur doit
   rester exactement le `main` qui contient les octets scellés. Relire
   par les chargeurs canoniques le manifeste successeur, le mapping sujets,
   les deux profils, l'inventaire, le reçu PII, les mappings niveau et type de
   document et le registre mixte version 2. Refuser toute divergence de SHA,
   toute troisième collection, toute intersection d'artefacts ou de
   placements avec les neuf collections V4. La construction complémentaire
   vérifie en outre les octets des liaisons d'autorité V4 contre le SHA-256
   `60bd9df71425e42a20287a88344f74b330510998c451107094786307855673fe`,
   puis les manifestes E5 et reranker contre leurs inventaires `SHA256SUMS`
   épinglés. Le delta de catalogue et les descripteurs d'autorité logiques
   copiés doivent également correspondre aux empreintes source scellées.
2. Les images Worker B et retrieval ont été construites hors hôte depuis le
   `main` contenant #271 et #273. Leur provenance est le run `36633288414`,
   lié au commit source `a9e3701965503d2862a248c46fd7e7e175058c8f`.
   Les images antérieures (run `36476516316`) ne contiennent ni l'adoption V2
   ni les correctifs Worker B : elles sont refusées. Ne rien reconstruire sur
   `nexus-prod`.
3. La présente PR soumet une **nouvelle autorisation de staging** liée au
   manifeste successeur, au registre mixte, à ces images et à leurs SHA. Elle
   place le fichier à son chemin actif, mais son approbation au
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
3. Adopter les 74 placements sous la **nouvelle** release par l'adoption
   **V2** (`--adoption-version SEALED-RELEASE-ADOPTION-V2`, DSN adopter), qui
   crée 74 ressources et 74 artefacts de contrôle successeurs distincts des
   lignes V4 — l'adoption V1 heurterait les 74 attestations V4 actives
   (`ATTESTATION_CONFLICT`, démontré par #271). Vérifier l'identité d'octets
   des 52 artefacts, puis la filiation par ensembles et identités
   (`--verify-v2-lineage`) : prédécesseurs = les 74 ressources V4 HGGSP dont
   l'attestation reste active, successeurs disjoints, anciens jobs
   inchangés. Aucune autorisation V4 HGGSP n'est réemployée.
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
