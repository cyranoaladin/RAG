# Lot préalable HGGSP — identités de contrôle du successeur

Base de conception : `2bc65c9386aafb80d66ce25096b50c75eeeb5412`.
Ce lot ajoute une primitive runtime et une migration de contrôle. Il ne donne
aucune autorisation staging ; la PR d'activation #270 reste distincte et draft.

## Invariant de coexistence

`publication_attestations` conserve son index unique sur `resource_id` pour
les attestations actives. Les colonnes `resource_id` et `artifact_id` de
`sealed_release_adoptions` conservent leur sens historique : elles désignent
la ressource et l'artefact **acquis par le prédécesseur**. La migration 020
ajoute `successor_resource_id` et `successor_artifact_id` pour les seules
adoptions `SEALED-RELEASE-ADOPTION-V2`. Les V1 restent sans valeur dans ces
colonnes. Les deux couples artefact/ressource sont contrôlés par des clés
étrangères composites. Aucun PDF, chunk ou embedding n'est recopié : V5
possède une nouvelle ligne de métadonnées d'artefact qui nomme le même SHA,
la même taille, les mêmes types MIME et les mêmes URL gouvernées.

## Dérivation déterministe

Le document d'identité est du JSON UTF-8 canonique (`sort_keys=True`,
séparateurs `,` et `:`, `ensure_ascii=False`) portant exactement
`version=SEALED-RELEASE-ADOPTION-V2`, `release_id`, `placement_id`,
`content_sha256` et `collection`.

- Ressource V5 : UUIDv5 dans `NAMESPACE_URL`, à partir de
  `nexus:successor-control:resource:v2` suivi d'un octet NUL et du document.
- Artefact de contrôle V5 : UUIDv5 dans `NAMESPACE_URL`, avec le domaine
  `nexus:successor-control:artifact:v2` et le même document.
- `dedup_key` V5 : `successor-control-v2:` suivi du SHA-256 hexadécimal de
  `nexus:successor-control:dedup-key:v2`, octet NUL, puis document.
- Run de contrôle V5 : UUIDv5 dans `NAMESPACE_URL`, à partir de
  `nexus:successor-control:run:v2`, octet NUL, puis du JSON canonique de
  `release_id` et `collection`.

Le digest d'adoption V2 reprend celui de V1 avec sa version V2 et **les quatre
UUID de contrôle** : ressource/artefact V4 et ressource/artefact V5. Les golden
vectors et les mutations d'un UUID figurent dans
`services/rag-engine/tests/test_sealed_release_adoption.py`.

## Écriture gouvernée

Le CLI `adopt-predecessor-release --adoption-version
SEALED-RELEASE-ADOPTION-V2` vérifie la release scellée, apparie exactement
les placements, puis utilise le rôle dédié `ingestion_control_adopter` dans
une transaction sérialisable. Ce rôle peut lire et **insérer** uniquement les
faits de contrôle nécessaires ; il ne peut pas modifier les lignes V4, créer
des jobs ou attester. Une divergence d'identité ou de métadonnées refuse la
transaction entière. La reprise V1 conserve l'option par défaut et le rôle
attestor historique.

La liaison des autorités et la proposition de revue batch restent des étapes
gouvernées distinctes : elles produisent les projections V5 après l'adoption.
La revue humaine batch reste obligatoire avant l'enregistrement des
attestations V5. L'outil d'enqueue et le claim release-bound continuent ensuite
de sélectionner les seules attestations et jobs V5.

La tête du schéma passe de 019 à 020. Le runner canonique relit maintenant le
registre **après** avoir acquis son verrou transactionnel et saute le DDL si
une autre invocation a déjà inscrit la même version. Deux bootstraps
concurrents terminent donc sans rejouer les contraintes déclaratives de 020.
Le rollback officiel 020 refuse toute adoption V2 et toute valeur des deux
nouvelles colonnes avant de retirer les colonnes, FKs et index. Les migrations
018 et 019 restent inchangées.

## Qualification locale

- PostgreSQL jetable : ancien modèle V1 → `ATTESTATION_CONFLICT` ; nouveau
  modèle V2 → 74 ressources et 74 artefacts de contrôle distincts, 74
  attestations V4 toujours actives, 74 attestations V5 actives, 74 jobs V5.
  Snapshots de toutes les colonnes V4 ressource, artefact, attestation et job
  identiques avant/après adoption, enqueue et claim V5. Rejeu : zéro nouvelle
  ressource, artefact, adoption, attestation ou job. Une erreur forcée sur la
  74e adoption annule l'ensemble.
- PostgreSQL jetable : installation depuis 000, upgrade 018→020, contrôle de
  propriété artefact/ressource, replay, rollback 020 avant V2 et refus du
  rollback après V2. La suite ciblée 020 compte 8 tests réussis ; les deux
  contre-épreuves historiques de rollback et de bootstrap concurrent ont
  été adaptées à la tête 020 et passent.
- Suite unitaire `rag-engine` : verte avec `PYTHONPATH` pointant vers ce
  worktree ; `mypy` : 149 fichiers sans erreur ; Ruff, `bash -n`, verrous de
  gouvernance, unicité d'autorité et hygiène dépôt : verts.
- `scripts/qualification/tests` : 803 réussis, 4 ignorés. `scripts/tests`
  hors tests de disponibilité go-live : 457 réussis, 17 ignorés. Quatre tests
  go-live échouent dans l'environnement local car `disk_policy_ok` exige
  40 Gio libres et la machine n'en a que 25 Gio ; le code de cette politique
  et ses tests sont inchangés par ce lot. Le run `scripts/ci-local.sh` a été
  interrompu pendant le téléchargement d'une dépendance CUDA de 423 Mo ;
  les cibles contracts (1012 tests), pdf-page-policy (23 tests) et import
  release-chain avaient réussi avant cette interruption. La CI GitHub de la
  PR reste la qualification intégrale à consulter avant toute fusion.

## Reprise de revue : rollback 020 et scénario B

Revue complémentaire sur `de3fcd72333c6e2dbb8428bb6d29ba5f7c9dd9de`
(base `2bc65c9386aafb80d66ce25096b50c75eeeb5412`, inchangée à la reprise).

### A. Appartenance d'un artefact après rollback 020 (P1)

**Reproduction.** Sur PostgreSQL jetable, rollback canonique 020 → 019 puis
vérification d'une adoption V1 : `artifact_belongs_to_release()` lève
`psycopg.errors.UndefinedColumn: column "successor_artifact_id" does not
exist`. Le `OR` SQL n'évite pas la résolution d'une colonne absente.

**Correction.** Le texte de la requête est choisi à chaque appel par
`successor_identity_schema_available()` (aucun cache) : sur 019, prédicat V1
seul, sans aucune colonne `successor_*` ; sur 020, prédicats V1 et V2. Sur
019 aucune ligne V2 ne peut exister (le rollback est refusé tant qu'il en
reste) : un artefact successeur n'y est jamais reconnu. Pas de `return True`,
pas d'`except` général, pas de repli d'une autorité V2 vers V1.
`persist_successor_control_adoption()` refuse désormais elle-même, avant
toute écriture, un schéma sans 020 (`adoption V2 requires control schema
migration 020`) : le refus ne dépend plus du seul garde du CLI.

**Tests** (`tests/integration/test_migration_020_successor_control_identity.py`,
runners canoniques, vraies migrations) :

- `test_artifact_membership_survives_019_020_and_rollback` : sur 019 avec
  données V1, puis après upgrade 020 sans V2, puis après rollback
  020 → 019 — artefact acquis sous sa release accepté, artefact adopté par V1
  accepté, mauvaise release refusée, artefact absent refusé. Une même
  connexion applicative traverse upgrade et rollback et exécute le prédicat
  au-delà du seuil d'auto-préparation de psycopg : ni hypothèse de schéma ni
  requête préparée ne survit au schéma pour lequel elle a été construite.
  **Rouge** sur l'implémentation défectueuse (`UndefinedColumn` après
  rollback), vert avec le correctif.
- `test_v2_membership_names_successor_identities_and_keeps_rollback_closed` :
  adoption V2 par le vrai chemin ; chaque artefact successeur appartient à
  V5, l'artefact prédécesseur n'appartient jamais à V5 et reste à sa release ;
  avec la preuve V2 présente le rollback reste refusé (`rollback 020
  refused`), tête 020 conservée.
- `test_v2_adoption_is_refused_explicitly_on_schema_019` : V2 sur 019 →
  `SealedReleaseAdoptionError`, aucun artefact successeur écrit (rouge avant
  correction : `UndefinedColumn`).

Suites 018 et 020 : 20 réussites.

### B. Scénario B : ce qui bloque réellement

Le blocage annoncé plus haut dans une version antérieure de ce rapport
(« identité unique de `public.rag_artifact_placements` ») supposait une
ligne produit HGGSP V4 déjà présente. Ce n'est pas le scénario autorisé.

**Décision B reproduite** (`tests/integration/test_hggsp_v5_first_publication_pg.py`,
opt-in `NEXUS_HGGSP_V5_PRODUCT_BENCH=1`) :

- contrôle (schéma réel jusqu'à 020) : 74 ressources, artefacts de contrôle,
  attestations actives et jobs V4 HGGSP, jobs **en file, jamais exécutés** ;
- produit (schéma réel) : 405 placements V4 non-HGGSP déjà servis
  (9 collections, 263 artefacts, 5678 chunks), **zéro** ligne HGGSP. Ces
  lignes sont une fixture d'état initial : identités scellées réelles,
  texte et vecteurs de chunks synthétiques. Le relevé opérateur
  `PLACEMENTS=9 263 405 CHUNKS=5678 HGGSP=0` est une preuve historique,
  non relue pendant ce lot ;
- chaîne V5 par les vrais CLI et rôles : adoption V2, liaison des autorités,
  proposition de revue batch (chaîne PII réelle), approbation sur la forge
  du banc, `record-release-batch-attestation`, mise en file par
  `staging_v4_enqueue_publication`, Worker B, rejeu.

Cibles recalculées depuis les autorités scellées (test
`test_les_cibles_se_recalculent_depuis_les_autorites_scellees`) :

| Périmètre | Collections | Artefacts uniques | Placements | Chunks uniques |
|---|---:|---:|---:|---:|
| V4 non-HGGSP préservée | 9 | 263 | 405 | 5678 |
| HGGSP V5 | 2 | 52 | 74 | 2590 |
| Union logique | 11 | 315 | 479 | 8268 |

Aucun contenu ni chunk n'est commun à HGGSP V5 et à V4 non-HGGSP. Les 74
placements HGGSP de V4 et de V5 sont identiques champ par champ (même
`placement_id` canonique) : seule l'autorité diffère. Les 74 lignes
d'artefact de contrôle V5 désignent 52 contenus physiques.

**Résultat 1 — le vrai CLI de Worker B ne démarre pas sur V5.**

```
MULTILEVEL_PUBLICATION_WORKER_STARTUP_FAILED: collection 'rag_nexus_dgemc_terminale_option' has no sealed taxonomy
```

Aucun job réclamé, produit HGGSP toujours vide. Deux défauts runtime
bloquent le scénario B **avant** toute écriture produit :

1. *Démarrage.* `MultilevelVerifiedPedagogicalPlacementResolver.from_authorities`
   (`src/ingestor/multilevel_verified_placement.py`) exige une taxonomie
   scellée pour **chacun des 11 profils** du registre `v3_livraison_315`,
   que le manifeste de profils de V5 (`763c2ad1…`) lie en entier et dont il
   vérifie le compte. Le registre de programmes scellé de V5 ne porte que
   les 2 taxonomies HGGSP. Aucun `--profiles-dir` admissible ne contourne
   ce refus. Les arguments Worker B préparés par #270 (lus, non exécutés :
   `--profiles-dir services/rag-engine/configs/ingestion_profiles/v3_livraison_315`)
   nomment ce même registre de 11 profils.
   *Correction minimale proposée* : borner ce contrôle de démarrage aux
   collections de la release (`release_eligibility`), en exigeant pour
   chacune un profil et une taxonomie ; le manifeste de profils reste
   vérifié sur le registre complet.
2. *Première itération.* L'adoption V2 crée la ressource successeur en
   `NEEDS_REVIEW` avec `state_version=0` (défaut du schéma, `CHECK >= 0`),
   que l'outil de mise en file recopie fidèlement dans le job.
   `publication_resume._require_payload` teste `not payload.get(champ)` et
   prend ce 0 pour une absence : `publication_resume payload is missing
   ['expected_state_version']`.
   *Correction minimale proposée* : ne tenir pour absents que `None` et la
   chaîne vide. La promotion attend précisément cette version 0.

Ces deux corrections touchent la logique runtime de Worker B, hors du
périmètre autorisé de cette reprise (compatibilité après rollback) : elles
**ne sont pas livrées**. Elles sont reproduites sans Docker, en CI, par
`tests/test_hggsp_v5_runtime_blockers.py` (deux `xfail(strict=True)` qui
n'acceptent que le message exact du défaut et basculeront dès la correction).

**Résultat 2 — sous ces deux seules corrections, la première publication
V5 réussit.** Le banc rejoue le même `main()` du CLI, mêmes arguments, même
readiness, mêmes rôles, en appliquant localement les deux corrections
proposées (`_correctif_de_demarrage_propose`) ; claim release-bound,
vérifications live, promotion, publisher gouverné et E5 réel restent ceux du
dépôt.

| Mesure | Avant | Après publication V5 | Après rejeu |
|---|---|---|---|
| Produit HGGSP (collections / artefacts / placements / chunks) | 0 / 0 / 0 / 0 | 2 / 52 / 74 / 2590 | identique |
| Produit V4 non-HGGSP | 9 / 263 / 405 / 5678 | identique, empreinte de toutes les colonnes inchangée | identique |
| Union produit | — | 11 / 315 / 479 / 8268 | identique |
| Jobs V5 | 74 `queued` | 74 `succeeded` | 74 `succeeded`, aucune itération |
| Jobs V4 HGGSP | 74 `queued`, 0 tentative | inchangés | inchangés |
| Ressources, artefacts, attestations, jobs V4 (toutes colonnes) | référence | identiques | identiques |

- Chaque placement produit HGGSP a le `placement_id` scellé de V5, son
  contenu, sa collection et son actualité ; `authorization_id` est
  l'autorisation r4 V5 (jamais V4) ; `publication_attestation_id` est une
  attestation V5 active, une par placement, liée par l'adoption V2 à la
  ressource et à l'artefact successeurs.
- Les chunks de chaque artefact reproduisent, dans l'ordre, les
  `chunk_sha256` et `chunk_id` scellés ; modèle `intfloat/multilingual-e5-large`.
- Rejeu : l'outil de mise en file rend `crees=0 deja_publies=74` ; Worker B
  s'arrête sur inactivité sans réclamer de job ; aucune ligne produit ou de
  contrôle ne change.
- Durée : 33 min sur CPU (16 cœurs) pour le module complet, cas 3 inclus.

**Blocage produit : non reproduit dans le scénario B.** Aucune contrainte
ni garde produit n'intervient quand le produit HGGSP est vide : le publisher
insère 52 artefacts puis 74 placements sous leurs autorités V5. Aucune
migration produit n'est nécessaire pour ce parcours.

**Cas 3 — contre-épreuve seulement.** Si le produit portait déjà les 74
placements HGGSP sous autorité V4 (fixture : Worker B V4 ne peut pas les
produire, ses mappings ne gouvernent pas HGGSP), la première itération V5
est refusée par `_insert_placement` (`governed_publisher_v2.py`) :
`existing placement differs from verified input` — `ON CONFLICT
(placement_id) DO NOTHING` puis relecture, dont `authorization_id` et
`publication_attestation_id` (V4) diffèrent de l'attestation V5. Produit
inchangé. C'est le refus voulu d'un remplacement d'autorité non autorisé,
pas le blocage du scénario B.

### Identités comparées

- `ingestion_control.artifacts` : 74 lignes de métadonnées V5 (UUIDv5 de
  contrôle), distinctes des 74 lignes V4, pour 52 contenus.
- `public.rag_artifacts` : identité = SHA-256 du contenu (52 lignes) ;
  `ingestion_artifact_id` nomme un artefact de contrôle V5, jamais V4.
- `public.rag_artifact_placements` : identité canonique scellée (74
  `placement_id`, identiques en V4 et V5) ; `authorization_id` =
  autorisation r4 V5, `publication_attestation_id` = attestation V5.

## Qualification de la reprise

- PostgreSQL jetable, en séquence (jamais deux suites Docker en parallèle) :
  migrations 018 et 020, coexistence V4/V5, répétition de rollback LOT44F :
  27 réussis ; banc scénario B complet (E5 réel, CPU) : 9 réussis.
- Suite unitaire `rag-engine` (`-m "not integration"`) : 4235 réussis,
  1 ignoré, 2 `xfail` stricts (défauts 1 et 2), 0 échec ; `mypy src` :
  149 fichiers sans erreur ; Ruff : vert ; verrous de gouvernance : 18 clés
  conformes ; `git diff --check` : propre.
- `scripts/qualification/tests` : 803 réussis, 3 ignorés, 1 échec
  d'environnement (le test lance l'interpréteur `services/rag-pedago/.venv`,
  absent de ce worktree ; le repli n'a pas `pypdf`). `scripts/tests` :
  551 réussis, 17 ignorés, 4 échecs `test_go_live_readiness` sur
  `disk_policy_ok` (17 Gio libres, 40 exigés). Aucun fichier `scripts/` n'est
  modifié par ce lot ; le seuil de disque n'est pas abaissé et rien n'a été
  nettoyé.

## Portée des preuves

- PostgreSQL réel (jetable) pour le contrôle et le produit, migrations et
  runners canoniques, rôles opérationnels.
- Publisher réel ; E5 réel (`intfloat/multilingual-e5-large`, inventaire
  `58ad18db…` vérifié par `verify_embedding_artifact`) sur CPU ; PDF réels
  relus depuis un miroir local et rehachés.
- Simulés : forge GitHub, autorisations r4 V5 de banc, readiness de staging
  signée par une clé de banc, manifeste de transfert (dérivé de V2, restreint
  aux 52 objets V5), lignes V4 initiales du contrôle, lignes produit V4
  non-HGGSP (texte et vecteurs synthétiques).
- Deux corrections runtime appliquées par le banc seul (voir plus haut) :
  la publication V5 n'est **pas** qualifiée sur le runtime tel que livré.
- Aucune opération serveur, aucune DB réelle, aucun Worker réel, aucune
  signature, aucun build d'image.

## Frontière du lot

Ce lot ne change ni le schéma produit, ni les 405 placements V4, ni #270 ou
#262, et ne constitue pas une autorisation de lancer Worker B V5. Avant tout
`production-image-provenance` destiné au scénario B, les octets runtime
doivent encore porter les corrections des défauts 1 et 2 (Worker B et
publication_resume) ; une image construite sur le `main` actuel refuserait
de démarrer sur V5. Aucun build ni opération serveur ne fait partie de cette
PR.
