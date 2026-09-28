# Lot go-live — activation staging du complément HGGSP

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
