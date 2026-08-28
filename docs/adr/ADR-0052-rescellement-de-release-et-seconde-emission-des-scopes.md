# ADR-0052 — Rescellement de release et seconde émission des scopes de retrieval

- **Statut** : **Accepté**
- **Date** : 2026-08-28
- **Décideur** : Nexus Réussite (opérateur)
- **S'appuie sur** : ADR-0045, ADR-0051
- **Dettes traitées** : n°13 (complétude du sceau), n°18 (emplacements volatils)

## Contexte

### Le fait nouveau que cet ADR établit

ADR-0045 a posé que « toute nouvelle version de subject exige un nouvel ID de
scope et un nouveau digest, jamais une mutation silencieuse d'un scope
existant ». Il raisonnait sur *une nouvelle version de subject*, en envisageant
vraisemblablement une **nouvelle release** : contenu nouveau, identité nouvelle.

Nous établissons qu'un **rescellement** produit le même effet **à identité de
release inchangée**. Mêmes 18 collections, mêmes 26 artefacts, mêmes 730 chunks,
même `release_id` — et pourtant les 18 digests de manifests-sujets changent,
parce qu'une empreinte d'attestation qu'ils contenaient a été corrigée.

C'est le cas que la gouvernance n'avait pas prévu, et la contribution durable de
ce lot.

### La chaîne complète

1. **`_model_inventory` non récursif.**
   `services/rag-pedago/scripts/build_production_profile_release.py` parcourait
   `snapshot.iterdir()` — non récursif — filtré par `is_file()`, qui écarte les
   répertoires **sans erreur ni avertissement**.

2. **Inventaire amputé.** Le snapshot embedding réel est le cache hub
   HuggingFace (`E5TokenCounter` exige que le répertoire porte la révision pour
   nom). Ses dix fichiers plats ont été scellés ; le sous-répertoire `1_Pooling/`
   ne l'a pas été. Empreinte obtenue : `e15ab71b…`.

3. **Release scellant une empreinte sans référent.** Les 18 manifests-sujets et
   leur agrégat ont scellé `e15ab71b…`. Or aucun répertoire ne peut à la fois
   satisfaire cet inventaire — dont `modules.json` fait partie, et qui déclare un
   module `Pooling` en `1_Pooling` — et être chargeable. `sentence_transformers`
   retombait sur un téléchargement distant : `EMBEDDING_MODEL_UNAVAILABLE`.
   **L'attestation n'avait pas perdu son référent : elle ne pouvait pas en
   avoir.**

4. **Rescellement.** `_model_inventory` rendu récursif, la release ré-émise
   scelle `58ad18db…`. Diff vérifié champ par champ : seules l'empreinte
   d'inventaire embedding et les digests qui en dérivent changent. Deux rejeux
   successifs produisent des fichiers identiques.

5. **Cascade hors du bundle.** Les 18 `RetrievalScopeArtifactV2` de
   `nexus-contracts` épinglent chacun le digest de son manifest-sujet via
   `source_sha256`. Le rescellement les rend tous divergents, et le runtime
   refuse de démarrer :
   `RuntimeError: scope source SHA differs from subject release`.

### Ce que la cascade a révélé sur la méthode

Le diff du rescellement portait sur ce que le script **écrit**. Il ne portait pas
sur ce qui, ailleurs, **épingle** ses sorties. **Un diff d'écriture n'est pas un
diff d'impact.** Un balayage inverse — chercher chaque *ancienne* valeur dans la
totalité du dépôt — a établi le périmètre réel : 21 fichiers, 38 sites, aucune
troisième couche. La méthode est consignée dans
`docs/runbooks/release_reseal.md` §2.3.

## Décision

### 1. Seconde émission : 18 nouveaux scopes `_v2`

Publier dans `nexus-contracts` **0.16.0** dix-huit `RetrievalScopeArtifactV2`
supplémentaires, suffixés `_v2`, liant les digests de manifests-sujets issus du
rescellement. Le registre passe de 31 à **49 scopes**, dont 48 V2.

C'est la **deuxième application du motif d'ADR-0045**, non une invention : les
treize scopes historiques y avaient déjà été préservés au profit de nouveaux IDs.
Le compteur croîtra à chaque ré-émission — c'est le sens d'un registre en ajout
seul, pas un défaut à corriger.

### 2. Les 18 `_v1` restent packagés et intacts

ADR-0045 le motive explicitement : le `source_sha256` d'un scope publié « ne peut
pas être réécrit sans invalider son identité canonique **et les enveloppes déjà
émises** ». Une enveloppe porte `scope_id` et `scope_digest` ; muter l'artefact
invaliderait toute enveloppe en circulation.

Leur dépréciation exigerait de prouver qu'aucune enveloppe ne les référence.
Décision distincte, hors de ce lot, **portée en dette n°21**.

### 3. `release_id` reste `production-profile-gate-2026-2027-v1`

Le contenu n'a pas changé. Bumper l'identité affirmerait un changement qui n'a
pas eu lieu, et invaliderait sans raison toute référence à la release.

**L'asymétrie assumée** — la release ne versionne pas, les scopes versionnent —
n'est pas une incohérence, parce que les deux versionnements ne mesurent pas la
même chose :

- le `release_id` désigne **ce que la release atteste** : un contenu, un
  périmètre, un ensemble de collections. Inchangés.
- le suffixe de scope est imposé par une **règle d'immuabilité** : ADR-0045
  interdit de réécrire un artefact publié, quelle qu'en soit la raison. Les
  scopes versionnent parce qu'on ne peut pas les modifier, pas parce que la
  release aurait changé d'identité.

Un `release_id` stable dont les manifests changent de digest reste vérifiable :
c'est `release-registry.json`, via `expected_manifest_sha256`, qui désigne l'état
courant. L'identité nomme la chose ; le digest nomme sa version.

**Limite reconnue** : rien ne relie explicitement un scope `_v2` au *fait* qu'il
procède d'un rescellement plutôt que d'un contenu nouveau. Un lecteur du seul
registre ne peut pas distinguer les deux cas. Cet ADR est ce lien ; l'inscrire
dans l'artefact serait plus robuste et relève d'une évolution de contrat
ultérieure.

### 4. Unicité du couple `(collection, source_sha256)`

ADR-0045 fixe la sélection au démarrage par le couple exact, « zéro comme
plusieurs correspondances sont des refus ». Une collision ne servirait donc pas
un mauvais scope : elle **empêcherait le démarrage**, reproduisant le mode de
panne dont ce lot fait sortir.

Vérifié avant écriture : **48 couples V2, 48 distincts, 0 collision**. Une même
collection porte légitimement plusieurs scopes — historique et production, puis
`_v1` et `_v2` — ce qui doit rester unique est le couple, jamais la collection
seule.

Verrouillé par
`packages/contracts/tests/test_production_profile_scope_registry.py::test_scope_collection_and_source_digest_pair_is_unique`,
vérifié rouge sur une collision fabriquée. Un second test,
`test_resealed_scopes_never_mutate_their_v1_counterpart`, échouerait si une
ré-émission future réécrivait un `_v1` au lieu d'ajouter un `_v2`.

## Conséquences

- `nexus-contracts` 0.16.0, évolution **strictement additive** : 31 → 49 scopes,
  aucun artefact existant modifié, aucun contrat V1 rompu ;
- la release rescellée dispose à nouveau d'une couverture retrieval exacte 18/18,
  par les `_v2` ;
- les clients qui valident d'anciennes enveloppes continuent de le faire par les
  `_v1` ;
- toute ré-émission ultérieure suivra ce motif : nouveaux scopes, jamais mutation
  — et devra exécuter le balayage inverse du runbook avant de conclure sur son
  périmètre ;
- cet ADR ne constitue ni une autorisation de contenu, ni une ingestion, ni un
  cutover production.

## Ce que cet ADR ne tranche pas

- la **dépréciation** des scopes `_v1` (dette n°21) ;
- le sort des manifests `multilevel/`, qui déclarent une empreinte embedding
  (`e2c7384b…`) ne correspondant à aucun artefact sur disque : inertes tant que
  `release-registry.json` ne les référence pas, bloquants à leur activation ;
- le dimensionnement du miroir PDF au passage aux 2451 contenus du corpus source
  (dette n°18).
