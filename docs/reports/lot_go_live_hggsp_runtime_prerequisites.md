# Lot HGGSP — prérequis runtime et autorités de scopes

## Périmètre

Branche dédiée issue exactement de
`26062eb1a1d7e8645a9a213fbf3de42ba88383fa`. Le brouillon local
`go-live/hggsp-complementary-activation` est conservé sans push.

Ce lot ajoute la sélection des jobs par release avant claim et les deux
autorités de scopes du successeur HGGSP. Il ne déplace pas la proposition
inactive d’autorisation et ne fournit aucune permission de mutation serveur.
Les images du run `36452645545` restent des preuves historiques du commit de
base ; elles sont supplantées pour la future activation HGGSP.

La proposition garde `kind=NEXUS-STAGING-HGGSP-COMPLEMENTARY-AUTHORIZATION-PROPOSAL-V1`
et `status=PROPOSED_INACTIVE`. Sa précondition documentaire d’image vaut
`PENDING_RUNTIME_PREREQUISITES_AND_FRESH_IMAGE_PROVENANCE`. Aucun fichier
d’autorisation actif HGGSP n’est créé.

## Isolation du Worker B

Sous une qualification de staging vérifiée, le Worker transmet au claim et à
la reprise des baux la paire `(release_id, release_manifest_sha256)` de cette
qualification et une allowlist explicite de collections. Les requêtes SQL
sélectionnent avant `UPDATE` les seuls jobs `publication_resume` dont
`payload.publication_attestation_id` désigne une attestation batch non
invalidée, portant la même paire de release. Elles vérifient également les
liens relationnels entre job, ressource, artefact, run et collection, ainsi
que la clé d’idempotence `publication:<attestation_id>`. La sélection utilise
`FOR UPDATE OF j SKIP LOCKED` ; les jobs exclus ne subissent aucune mutation.
La reprise des baux expirés applique la même portée. Le mode sans
qualification conserve l’ancienne signature et l’ancien comportement.

Les contre-épreuves PostgreSQL jetables couvrent la même collection avec un
ancien job V4 et un nouveau job V5, le payload forgé, l’attestation absente
ou invalidée, le mauvais manifeste, la collection étrangère, deux workers
V5 concurrents et un ancien bail V4 expiré. Elles comparent toutes les
colonnes du job V4 avant et après claim/reprise, dont statut, tentatives,
prochaine tentative, propriétaire, jeton et expiration du bail.

## Autorités de scopes

Le registre gouverné HGGSP externe, d’empreinte
`55c44631ece57a5337a3733015a57e5add6cb478c86165464fe95c2a0044f442`,
reprend les dimensions de politique V4 sans les élargir. L’autorité de
nommage, d’empreinte
`f72935d27e94d67868ab7e5bed604e4c0a2dba1943ab165918d3ced7ba0aeb8d`,
lie les deux nouveaux IDs à la release
`production-profile-gate-2026-2027-v5-hggsp`, à son manifeste
`8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`
et au registre mixte
`59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`.
Le producteur canonique reproduit les deux artefacts packagés octet pour
octet : `prod_hggsp_premiere_specialite_v3` et
`prod_hggsp_terminale_specialite_v3`. Les onze identifiants V4 restent
distincts ; les neuf artefacts V4 toujours servis gardent leurs octets.
Le manifeste scellé et le registre mixte ne sont pas modifiés.

## Frontière des prochaines images

Le Dockerfile retrieval installe `packages/contracts` dans l’image. Le
Dockerfile Worker installe ce même paquet et copie les répertoires
`ingestion_control/` et `ingestion_worker/`. Les octets nouveaux de ce lot
entreront ainsi dans les images construites **après** fusion. Aucun digest
du run historique n’est réutilisé comme digest d’activation, et aucun build
ou workflow de provenance n’a été lancé dans ce lot.

## Qualification et preuves

- `packages/contracts/tests` : 1003 réussis ; le contrôle d’export du schéma
  et la reproduction canonique des deux nouveaux artefacts passent.
- `packages/release-chain/tests` : 56 réussis.
- Six modules de tests retrieval et d’identité moteur : 332 cas collectés,
  suite terminée sans échec.
- `services/rag-engine/tests` hors intégration : 4226 cas collectés, suite
  terminée sans échec après mise à jour des deux cardinalités du registre
  client (65 scopes, dont 64 V2) et installation des métadonnées locales du
  contrat 0.22.0. Les tests de claim/reprise et du Worker B utilisent un
  PostgreSQL Docker jetable ; les 55 tests ciblés avec la cadence DI et la
  sortie 75 passent également.
- `scripts/qualification/tests` : 803 réussis, 4 ignorés.
- Ruff sur contracts et les fichiers Worker, mypy ciblé, hygiène du dépôt,
  unicité des autorités, verrous de gouvernance, topologie CI et tests de ces
  gardes : réussis.
- Le mypy complet de rag-engine et quatre tests de readiness liés à la
  capacité disque locale gardent des échecs reproduits au commit parent
  exact ; voir le rapport de dette du lot. Aucun garde n’est désactivé.
- Revue indépendante du diff indexé : aucun défaut P0/P1/P2 actionnable.

Les tests ont utilisé seulement des conteneurs PostgreSQL jetables locaux.
Aucune connexion SSH, base réelle, signature réelle, exécution du Worker
réel ou opération sur la PR #262 n’a été effectuée.

## Suite opérateur

Après fusion de la PR et au nouveau `main`, lancer le workflow
`.github/workflows/production-image-provenance.yml`. Le nouveau run devra
produire les digests Worker et retrieval destinés à la PR d’activation future.
