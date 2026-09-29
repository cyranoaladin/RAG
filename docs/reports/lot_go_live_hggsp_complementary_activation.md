# Lot go-live — activation staging du complément HGGSP

## Mise à niveau du 29/09/2026 — adoption V2, migration 020, images reconstruites

Les sections suivantes décrivent l'état initial de la PR ; celle-ci les
**remplace** pour la provenance, les images et la chaîne d'adoption.

**Pourquoi.** #271 a démontré sur PostgreSQL que l'adoption V1 sous le rôle
attestor aboutit à `ATTESTATION_CONFLICT` face aux 74 attestations V4 actives,
et #273 a corrigé deux défauts qui empêchaient Worker B de publier V5. La PR
d'origine utilisait l'adoption V1, joignait l'enqueue sur l'identité
prédécesseur et épinglait des images antérieures à ces correctifs.

**Base et provenance.** `main` = `a9e3701965503d2862a248c46fd7e7e175058c8f`
(#271 et #273 fusionnées, CI post-fusion verte), intégré par fusion.
Build `production-image-provenance` run `36633288414` sur ce commit (arbre
`68a4f905a4e42faeaf7671b1fb4016643ede921f`) : artifact `11062997847`, ZIP
`4789b260c03c0cd178459e148223a506cc72244ba7ca763f967aa1e76a25c946`,
inventaire `5e8c0332d87552a6df0804add10abbbe7f6b18682c5255c5a258ccfd047da767`.
Worker A/B `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf`,
retrieval `ghcr.io/cyranoaladin/rag-ingestor@sha256:11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf`.
Dockerfiles inchangés (`feeceb78…`, `f7f53bab…`, recalculés). Le futur
commit d'activation (fusion de cette PR) n'a pas à égaler le commit source.

| Fichier exécuté | Origine | Autorité |
|---|---|---|
| CLI d'adoption V2, Worker B, `ingestor.*` | image worker | digest `2228650e…`, commit `a9e37019` |
| sonde retrieval | image ingestor | digest `11aa98d5…` |
| orchestrateur, vérificateur, prévol, `hggsp_control_schema_020.py`, `staging_v4_role_env.py`, migration 020, runner, provisionneur adopter | checkout fusionné (`/repo` ou hôte) | commit d'activation sur `main` |

Aucun fichier modifié par cette mise à niveau n'est exécuté depuis l'image :
pas de nouveau build.

**Opération ajoutée** `successor_control_schema_020_and_adopter_role`, entre
`successor_preflight` et l'enregistrement des r4 (détail et reprises :
runbook). Base `ragdb_profile_gate_v4`, schéma `ingestion_control`, 019 → 020
(octets de `main`, SHA-256 lié), rôle `ingestion_control_adopter`.
- Effets locaux à la base : 020 (contraintes, colonnes successeur), droits du
  rôle sur `ingestion_control`, `CONNECT` sur la base.
- Effet **global au cluster** : un rôle est créé dans le catalogue partagé.
- Les quatre rôles historiques ne sont pas touchés : provisionneur ciblé
  (`provision_ingestion_control_adopter_role.sh`), sans rotation, attribut ni
  appartenance ; le provisionneur canonique n'est pas relancé.
- Secret : généré sur l'hôte, conservé (0600 sous 0700) AVANT le rôle ;
  seul un vérificateur SCRAM part au serveur, journalisation coupée pour la
  transaction ; rôle sans secret ou secret incohérent : refus, jamais de
  réinitialisation.
- Accès hérités de PUBLIC (par exemple `CONNECT` sur d'autres bases) :
  rapportés par l'opération, jamais corrigés par un `REVOKE` global.

**Chaîne corrigée.** Adoption `--adoption-version SEALED-RELEASE-ADOPTION-V2`
sous le DSN adopter, sortie contrôlée au premier passage comme au rejeu ;
filiation V2 vérifiée par ensembles et identités (`--verify-v2-lineage`,
lecture seule) ; enqueue joint sur `successor_resource_id` /
`successor_artifact_id` ; readiness successeur, autorisation, preuve, plan
et vérificateur épinglent les nouvelles images. Interdits ajoutés : rotation
ou réalignement des rôles historiques, réinitialisation du mot de passe
adopter, migration au-delà de 020, migration produit.

**Qualification (sur ce code).**
- PostgreSQL réel, opt-in `NEXUS_HGGSP_PG=1` —
  `test_hggsp_control_schema_020_pg.py` : 10 réussis (départ 019 avec les
  quatre rôles historiques et des lignes V4 acquises par les primitives ;
  rôles historiques identiques ; cinq DSN historiques non réécrits ; aucune
  valeur secrète ni vérificateur en sortie ni dans le journal serveur en
  `log_statement=all` ; rejeu sans rotation ; mauvaise base, job en cours,
  rôle sans secret, secret incohérent, DSN divergent refusés sans écriture ;
  reprises après secret, après migration, après rôle ; rollback permis sans
  V2 puis refusé après une adoption V2 réelle sous le DSN dérivé ; parité des
  droits avec le provisionneur canonique ; vérificateur SCRAM accepté par
  PostgreSQL). `test_staging_hggsp_chain.py` sur PostgreSQL : 2 réussis
  (schéma d'enqueue aligné sur la forme V2, `state_version=0`).
- `scripts/qualification/tests` : 943 réussis, 7 ignorés (dont les tests PostgreSQL opt-in) ; parmi eux 24 tests unitaires de l'opération 020 (`test_hggsp_control_schema_020.py`), les mutations de la filiation V2 et de l'autorisation.
- `scripts/tests` : 701 réussis, 17 ignorés, 4 échecs `test_go_live_readiness` sur `disk_policy_ok` (5 Gio libres, seuil 40 Gio inchangé) — dette disque préexistante ; configuration #272 (`test_claude_config.py`) incluse.
- Limites : secrets et forge synthétiques ; aucune base staging lue ; les
  tests PostgreSQL ne sont pas exécutés par la CI (opt-in).

**Brouillon préservé.** Un fichier non suivi du worktree (ancienne version de
`test_hggsp_successor_attestation_coexistence_pg.py`, remplacée par la
version fusionnée de #271) bloquait l'intégration de `main` ; il a été
déplacé, sans suppression, hors du dépôt
(`~/nexus-agent-handoffs/pr270-untracked-20260929T223232/`).

## Périmètre

La branche part exactement de `2bc65c9386aafb80d66ce25096b50c75eeeb5412`
(arbre `2960a1a3ca9cc3110623e3870df95de4f45e504c`), après fusion des
prérequis runtime #269. Le brouillon local antérieur est préservé. Ce lot ne
construit aucune image et n'effectue aucune opération serveur.

La release `production-profile-gate-2026-2027-v5-hggsp` garde son manifeste
`8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`.
Le registre mixte v2 garde son SHA-256
`59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`.
Les deux seules collections successeurs sont
`rag_nexus_hggsp_premiere_specialite` et
`rag_nexus_hggsp_terminale_specialite` : 2 collections, 52 artefacts,
74 placements, 2 590 chunks attendus.

## Autorité et provenance

La proposition inactive a été déplacée par `git mv` au chemin actif candidat
`docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json`.
Le protocole `NEXUS-STAGING-HGGSP-COMPLEMENTARY-AUTHORIZATION-V1` porte le statut
`ACTIVE_AFTER_MERGE`. Il n'est consommable que si les octets liés sont dans
`origin/main`, si le checkout est au HEAD de main et si la PR qui introduit
l'autorisation est fusionnée avec revue canonique au HEAD exact. La garde
locale et la garde embarquée des images refusent la branche de PR avant tout
accès à la base. Aucune seconde autorité HGGSP active ne subsiste.

La preuve `docs/reports/evidence/staging_hggsp_image_provenance.json` lie le
workflow `production-image-provenance.yml`, run `36476516316`, tentative 1,
artifact `10993199399`, inventory SHA-256
`826bbdd474ff5714aafa091b1d0414f90335b17bca4686b2f6826d0299fca761`,
ZIP SHA-256
`4d4a664cbcf69f800dcd72850cf77845175333eeb9990e849fa7cde36441723b`,
source commit et arbre exacts. Les images finales sont :

- retrieval : `ghcr.io/cyranoaladin/rag-ingestor@sha256:e9a2e5dd5681911afe950c8852de36f907ed8945c97d736ebcb9debab206ad14` ;
- Worker A/B : `ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:14aef8482dc3f322101b0bb3383d442c278386f383c2aaf42a3cca7acbd0416e`.

Le run `36452645545` et les digests `c2e0bf60…` / `4d4ce473…` sont conservés
comme historique, sans fonction dans cette activation.

## Chaîne future, après fusion seulement

Le signer local produit deux fichiers Ed25519 distincts de la readiness V4 et
lie release, manifeste, deux images, base, collections et registre mixte. Il
refuse l'autorisation non fusionnée avant lecture de la graine privée. La
graine reste hors dépôt ; aucune signature réelle n'a été faite.

L'orchestrateur suit dix étapes : installation de readiness, prévol,
enregistrement r4, liaison ou acquisition scellée, proposition de revue batch,
**arrêt humain**, enregistrement de cette revue distincte, attestations,
enqueue de 74 nouveaux jobs, Worker B lié à la release, puis vérification
indépendante. Une revue des deux r4 au HEAD exact est une précondition de leur
enregistrement. Les scopes runtime `prod_hggsp_premiere_specialite_v3` et
`prod_hggsp_terminale_specialite_v3` proviennent de #269 ; le producteur r4
de ce lot ne les réémet pas.

Avant chaque écriture, le prévol relit #262, le produit V4
9/263/405/5678, les 74 vieux jobs HGGSP V4 et leur empreinte
`fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31`,
l'absence de publication ou de jobs successeurs avant leur étape, et
l'intangibilité de `ragdb`. L'enqueue exige l'attestation relationnelle V5 et
crée des jobs par le producteur canonique. Il n'expose aucune commande CLI
d'enqueue directe : l'orchestrateur mesure `ragdb` et relit #262/V4 avant
d'appeler la primitive dans le conteneur. Un rejeu des 74 jobs déjà présents ne crée
aucun doublon, même si un job est terminé. Un job en échec bloque le rejeu.
Le Worker #269 filtre par release
dans la transaction de claim. La vérification indépendante attend HGGSP
2/52/74/2590, V4 9/263/405/5678 et union 11/315/479/8268, sonde les onze
scopes avec la correction multi-placement, puis s'arrête avant tout retrait
des 74 anciens jobs V4.

## Qualification et dette de base

Les suites HGGSP, PostgreSQL jetable, contrats, release-chain, Worker
release-bound, scripts, Ruff, mypy, Bash, verrous, unicité d'autorité et
hygiène ont été exécutées. La qualification `scripts/qualification/tests`
compte **904 tests passés et 4 ignorés**, y compris les contre-épreuves
PostgreSQL jetables. Le retrieval multi-placement sur PostgreSQL compte
**26 tests passés**. `scripts/ci-local.sh` a été tenté ; ses premiers
lots ont passé (contrats 1 012 tests, politique PDF 23 tests, import
release-chain), puis son installation locale de `rag-pedago` est restée
bloquée plus de trois minutes sur la roue `nvidia_cublas` de 423 Mo. Cette
exécution a été arrêtée sans changer de garde et les suites pertinentes ont
été lancées séparément. L'état CI GitHub de la PR sera lu après son ouverture.

La suite générale `scripts/tests` compte 551 tests passés, 17 ignorés et
quatre échecs du contrôle `test_go_live_readiness.py` liés à
`disk_policy_ok` ont été reproduits octet pour octet sur le commit parent ;
ils sont consignés dans
`docs/reports/lot_go_live_hggsp_complementary_activation_dettes.md`. Aucun
garde HGGSP n'a été assoupli pour les masquer.

Aucun SSH, aucune connexion à une base réelle, aucun Worker réel, aucune
signature réelle, aucun r4 ni enqueue réel, aucune mutation de #262, aucune
bascule `current` et aucun déploiement de production n'ont été effectués.
