# Lot HGGSP V5 — runtime de Worker B pour la release complémentaire

Base : `main` = `95e8aabb9bba1b52b6542ae533ab3432a4532c09` (#271 fusionnée, CI
post-fusion verte ; contient la configuration agentique #272).
Continuité directe de #271 : son rapport
(`lot_go_live_hggsp_successor_control_resource_identity.md`, § B) avait
établi que le scénario B ne rencontre aucune contrainte produit, mais que
Worker B tel que livré ne pouvait pas publier V5 (défauts 1 et 2). #271 étant
fusionnée, les corrections arrivent par cette PR distincte.

## Défaut 1 — taxonomies exigées hors du périmètre de la release

`MultilevelVerifiedPedagogicalPlacementResolver.from_authorities`
(`services/rag-engine/src/ingestor/multilevel_verified_placement.py`) exigeait
une taxonomie scellée pour chacun des 11 profils du registre
`v3_livraison_315`. Le registre de programmes de V5 n'en scelle que 2 : le
vrai CLI refusait de démarrer
(`collection 'rag_nexus_dgemc_terminale_option' has no sealed taxonomy`).

Correction : le contrôle porte sur les collections de la release **vérifiée**
(`release_eligibility`, chargée contre l'empreinte du manifeste) — jamais sur
un argument de l'appelant. Pour chacune : un profil gouverné (nouveau refus
`release collection … has no governed profile`, qui comble un trou : une
collection de release sans profil passait la construction), une taxonomie
scellée et un programme. Le manifeste de profils reste vérifié sur le
registre complet (compte 11). Pour une release complète (V4 : 11 collections),
le périmètre est identique à l'ancien.

## Défaut 2 — `expected_state_version=0` pris pour une absence

Une ressource successeur V2 naît à `state_version=0` (défaut du schéma,
`CHECK >= 0`) ; `_require_payload` testait `not payload.get(champ)`.
Correction : présence (`None` ou chaîne vide/blanche = absent), puis type et
valeur — `expected_state_version` entier non négatif, booléens refusés ;
identifiants en chaînes non vides. Tous les producteurs du dépôt
(`staging_v4_enqueue_publication`, bancs) écrivent un entier.

## Tests

- `tests/test_multilevel_placement_resolver.py` : profil hors release sans
  taxonomie accepté ; taxonomie manquante dans le périmètre refusée ;
  collection de release sans profil refusée ; compte du manifeste vérifié
  sur le registre complet (3 profils dont 1 hors release).
- `tests/test_publication_resume.py` : version 0 et 10 acceptées ; `None`,
  `False`, `True`, `-1`, `"0"`, `1.0`, identifiant vide, blanc ou non chaîne,
  champ retiré : refusés.
- `tests/test_hggsp_v5_worker_b_authorities.py` (ex-`test_hggsp_v5_runtime_blockers.py`,
  `git mv`) : les deux `xfail(strict=True)` de #271 deviennent un test
  ordinaire. Sans Docker, sur les octets scellés de V5, la chaîne PII réelle
  et la qualification de release : les autorités de Worker B se chargent,
  11 profils, collections réclamables = les 2 HGGSP, une collection hors
  release refusée. Le cas du payload est couvert par `test_publication_resume.py`.

## Banc réel du scénario B, sans correctif injecté

`tests/integration/test_hggsp_v5_first_publication_pg.py` (opt-in
`NEXUS_HGGSP_V5_PRODUCT_BENCH=1`) : le correctif de banc
`_correctif_de_demarrage_propose` est **supprimé** ; Worker B passe
exclusivement par le vrai CLI en sous-processus, runtime tel que livré, pour
la publication, le rejeu et le cas 3.

Résultat (29/09, sur ce code) : **8 réussis en 39 min 40 s**.

| Mesure | Avant | Après publication V5 | Après rejeu |
|---|---|---|---|
| Produit HGGSP (collections / artefacts / placements / chunks) | 0 / 0 / 0 / 0 | 2 / 52 / 74 / 2590 | identique |
| Produit V4 non-HGGSP | 9 / 263 / 405 / 5678 | identique (empreinte de toutes les colonnes) | identique |
| Union produit | — | 11 / 315 / 479 / 8268 | identique |
| Jobs V5 | 74 `queued` | 74 `succeeded` | aucune itération |
| Jobs V4 HGGSP | 74 `queued`, 0 tentative | inchangés | inchangés |
| Ressources, artefacts, attestations, jobs V4 (toutes colonnes) | référence | identiques | identiques |

Identités produit : `placement_id` scellés de V5, autorisation r4 V5,
attestation V5 active par placement ; `rag_artifacts.ingestion_artifact_id`
nomme un artefact de contrôle V5 ; chunks = `chunk_sha256`/`chunk_id` scellés
dans l'ordre, modèle `intfloat/multilingual-e5-large`. Cas 3 (contre-épreuve,
fixture HGGSP V4 préexistante) : `existing placement differs from verified
input`, produit inchangé.

Portée : PostgreSQL jetable réel (contrôle 020, produit), vrais CLI et rôles,
publisher réel, E5 réel sur CPU (inventaire `58ad18db…` vérifié), PDF réels
d'un miroir local rehachés. Simulés : forge GitHub, autorisations r4 V5 de
banc, readiness signée par clé de banc, transfert dérivé de V2 restreint aux
52 objets, lignes V4 initiales du contrôle, lignes produit V4 non-HGGSP
(texte et vecteurs synthétiques). Ce n'est ni une qualification staging ni
une qualification sur l'image de production.

## Qualification

- Unitaire `rag-engine` (`-m "not integration"`) : 4253 réussis, 17 ignorés,
  0 échec, plus aucun `xfail` ; `mypy src` : 149 fichiers ; Ruff vert.
- PostgreSQL jetable, en séquence : migrations 018 et 020, coexistence
  V4/V5, rollback LOT44F : 27 réussis ; banc scénario B : 8 réussis.
- `scripts/tests/test_claude_config.py` (configuration #272) : 150 réussis.
  `scripts/qualification/tests` : 803 réussis, 4 ignorés. `scripts/tests` :
  701 réussis, 17 ignorés, 4 échecs `test_go_live_readiness` sur
  `disk_policy_ok` (seuil 40 Gio, ~11 Gio libres) — dette disque, seuil
  inchangé. Verrous de gouvernance : 18 clés conformes.

## Frontière

Aucune migration, aucun changement de schéma produit, de contrainte, de
manifeste ou de registre scellé. #270 et #262 inchangées. Aucune opération
serveur, DB réelle, signature, Worker réel ni build d'image. Après fusion et
CI post-fusion, `main` porte les octets runtime nécessaires au scénario B ;
le build `production-image-provenance` reste une décision distincte.
