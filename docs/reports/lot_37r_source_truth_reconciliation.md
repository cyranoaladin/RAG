# LOT37R — Réconciliation de la source de vérité

## Verdict

**LOT37R_READY_FOR_MERGE**

Ce verdict porte uniquement sur la réconciliation Git, la topologie CI,
l'hygiène du dépôt et la protection de `main`. Le verdict global **GO_LIVE**
reste **NO_GO** jusqu'au LOT47 et à sa fenêtre publique entièrement verte.

## Périmètre

| Élément | Valeur vérifiée |
|---|---|
| Baseline `origin/main` et ref GitHub `main` | `b70c3eead488299672f057c366c7df32c4297f34` |
| Source de la CI locale finale | `756aba8f61c647ae99cad756148fd5340c493c7e` |
| Source du run PR initial | `eb3a70bccb7e58712082bbf3af396bf2c89ffbe6` |
| Conception, tête de la PR 79 | `c794e4894c81b9d35e2063ae1989a559270a8335` |
| Fusion de la conception, PR 79 | `b70c3eead488299672f057c366c7df32c4297f34` |
| Branche | `lot-37r-source-truth-reconciliation` |
| PR de remplacement | [PR 80](https://github.com/cyranoaladin/RAG/pull/80), ouverte et brouillon |
| Observation UTC du readback final | `2026-07-31T21:27:02Z` |

LOT37R ne modifie aucun code sous `services/` ou `packages/`, aucune dépendance,
aucun verrou de gouvernance, aucun corpus et aucun runtime. Il ne lit ni
n'applique les stashes. La CI locale prouve la source `756aba8…`; le run PR
versionné prouve la tête de code initiale `eb3a70b…`. Les checks de la tête
documentaire finale devront réussir après son push : ils ne sont pas tenus pour
acquis dans ce rapport. Seuls revue, squash et fusion de la PR 80 transformeront
la tête ainsi validée en source de vérité `main`.

## Réconciliation PR 56/77

L'état ci-dessous a été relu sur GitHub le 31 juillet 2026. Les rollups anciens
peuvent agréger plusieurs événements ; les nombres rapportent donc exactement
les conclusions exposées par GitHub au moment de la lecture.

| PR | État et tête | Diff | Conclusions des checks | Idées réutilisées dans LOT37R | Changements explicitement exclus | Décision |
|---|---|---:|---|---|---|---|
| [PR 56](https://github.com/cyranoaladin/RAG/pull/56) | ouverte, brouillon, en retard sur `main`; `ca471616ae4270e96561f56724f14f2b7728bfd3` | 12 fichiers, +626/−0 | 5 `SUCCESS`, 0 échec | intention fail-closed et preuve de non-régression, sans reprise globale du diff | `Makefile` racine, configuration pytest racine, régression globale, E2E production, smoke racine et extension du runbook go-live | `SUPERSEDED_AFTER_LOT37R_MERGE` |
| [PR 77](https://github.com/cyranoaladin/RAG/pull/77) | ouverte, brouillon, en retard sur `main`; `5763e7b65ea09114c8114caab9b1ff45c67ab3ac` | 40 fichiers, +959/−52 | 13 `SUCCESS`, 2 `FAILURE` sur `full regression` | sentinelle anti-réentrance, découplage de l'audit, test de topologie, garde d'hygiène, déplacement des manifests et politique de protection | `Makefile` racine, régression globale, E2E production, pytest racine, fixtures réseau, dépendances et code des services | `SUPERSEDED_AFTER_LOT37R_MERGE` |

Aucune des deux PR n'est fusionnée, fermée ou supprimée par cette tâche. Leur
fermeture et la suppression de leurs branches restent conditionnées à la fusion
du remplacement et à la revalidation de `main`.

## Inventaire des stashes

L'inventaire provient uniquement de `git stash list
--format='%gd%x09%H%x09%gs'`. Aucun contenu de stash n'a été ouvert.

| Référence | Commit immuable | Branche ou lot inféré du message | Disposition |
|---|---|---|---|
| `stash@{0}` | `906558ab06c384dd3b5ed0ed5387646a06585427` | LOT38, transition de gouvernance bloquée | `NOT_DELIVERED` |
| `stash@{1}` | `7ffde33ac4255e314762a0fc4616f8fc7fb03d4a` | LOT39–40 restant après l'index LOT38 | `NOT_DELIVERED` |
| `stash@{2}` | `529d5bd520b31c951cd7a97c9e90b1dc69cf0da0` | LOT38–40 avant séparation | `NOT_DELIVERED` |
| `stash@{3}` | `3784c29fe845457986be7d40dadbd0ac080efdf4` | LOT27, contrôle d'intégration temporaire | `NOT_DELIVERED` |
| `stash@{4}` | `74c4c913cbb3d81ce1f0ca2f78303a08b3b9815a` | LOT26.3, sécurité des rôles v2 | `NOT_DELIVERED` |
| `stash@{5}` | `8c35ed42921b1d5d844776b3b95228d7fd67ae20` | LOT26.3, artefacts locaux différés depuis `main` | `NOT_DELIVERED` |
| `stash@{6}` | `d36fad5058e7d02e8c481a49218fdc91d846bc9c` | LOT1.1, chunking pédagogique historique | `NOT_DELIVERED` |

## Dettes

Les 17 titres substantiels de `docs/reports/lot_0_dettes.md` sont conservés,
y compris les éléments résolus ou historiques. La classification applique la
règle fail-closed de la conception : droits, notions, contenu non revu,
chunking, contrat, sécurité et reproductibilité restent bloquants jusqu'à la
preuve LOT43. Le statut de résolution est distinct de cette classification.

| Dette ou titre historique | Classification | Statut de résolution au `main` courant | Preuve revérifiée | Lot destination |
|---|---|---|---|---|
| `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` | `non_bloquante_avec_preuve` | résolue | les deux fichiers de tests real-draft, identiques à `origin/main`, donnent 23 tests réussis ; la fixture valide est suivie | LOT37R, preuve conservée |
| `test_real_draft_unlock_gate` et son erreur interne pytest | `non_bloquante_avec_preuve` | résolue | même exécution ciblée : 23 tests réussis, sans erreur interne ; le patch est désormais scopé au module | LOT37R, preuve conservée |
| Résolution monorepo `nexus-contracts` | `bloquante_pilote` | contournement éditable opérationnel, industrialisation non démontrée | `ci-local.sh` et les deux Makefiles installent `packages/contracts` en éditable ; aucun workspace `uv` n'est versionné | LOT43, manifeste reproductible |
| Commit ROADMAP poussé sur `main` hors PR | `non_bloquante_avec_preuve` | écart historique irréversible, récidive techniquement bloquée | `93f5ba8` est ancêtre de `origin/main` ; le readback live impose désormais PR, checks stricts et administrateurs inclus | LOT37R, contrôle de branche |
| Erreurs d'import rag-engine, LOT21 | `non_bloquante_avec_preuve` | résolues dans le chemin canonique d'installation | la cible locale `services/rag-engine` est verte après `make install`; ses sources sont identiques à `origin/main` | LOT43, scellement d'environnement |
| `api.py` — moteur historique en sursis | `bloquante_pilote` | active | `origin/main` conserve le monolithe de 2 243 lignes et `resolve_collection()` ; aucun import de `database.py` ni INSERT vers `rag_chunks` n'y a été trouvé | LOT41 pour l'isolation des routes, LOT45 pour la preuve production |
| Vigilance sur le partage potentiel de `rag_chunks` | `bloquante_pilote` | risque de configuration toujours présent, chemin d'écriture legacy non observé | les configurations legacy et v2 déclarent encore `rag_chunks`; `api.py` n'importe pas `database.py` et ne contient aucun INSERT vers cette table | LOT40 pour l'isolation physique, LOT45 pour le readback cible |
| Décision D-LEGACY-CI | `non_bloquante_avec_preuve` | invariant actif | la cible `services/rag-engine` exécute les tests non-intégration sans exclure le marqueur legacy et reste verte | LOT45, décision explicite de maintien ou décommissionnement |
| R1 — Dédup fallback base-name | `bloquante_pilote` | active, aucune réfutation exhaustive versionnée | le script LOT22 consomme toujours la décision `dedup.kept`; aucun test courant ne prouve l'absence de faux positif homonyme sur le manifeste pilote futur | LOT42, revue exhaustive du manifeste corpus |
| R2 — 30 PDF scannés en holding list | `bloquante_pilote` | active pour les données LOT22 | le moteur possède un fallback OCR, mais aucune preuve versionnée ne démontre le traitement ou l'exclusion justifiée des 30 fichiers | LOT42, qualification ressource par ressource |
| R3 — proxy mots×1.3 non unifié | `bloquante_pilote` | active | `pedagogical_chunker.py` calcule toujours `len(text.split()) * 1.3` | LOT42 pour le chunking pilote, LOT43 pour le manifeste runtime |
| R4 — `notions[]` vide sur les chunks LOT22 | `bloquante_pilote` | active pour l'index historique ; contrat encore permissif par défaut | le contrat de chunk conserve une liste vide par défaut ; aucun manifeste pilote de 39 notions n'est encore publié | LOT42, matrice programme–notions et publication gouvernée |
| R5 — seuil de similarité | `bloquante_pilote` | résolue historiquement à `1.90`, calibration encore provisoire | `retrieval_v2.py` conserve le seuil configurable `1.90` et la preuve 15/15–10/10, sans baseline du corpus pilote final | LOT43, calibration et seuils absolus |
| R6 — hybride BM25/RRF et rerank CrossEncoder | `bloquante_pilote` | rerank présent, hybride explicitement différé | le module RRF existe, tandis que `retrieval_v2.py` indique que l'hybride est désactivé pour le corpus mono-matière | LOT40 pour le retrieval hybride nominal, LOT43 pour la mesure |
| R7 — `review_status=needs_review` servi historiquement | `bloquante_pilote` | endpoint élève gouverné corrigé, chemin historique encore permissif et revue du corpus pilote non réalisée | `retrieval_v2_endpoint.py` filtre seulement `reviewed`, tandis que `scripts/retrieval_v2.py` conserve `reviewed, needs_review`; aucune décision unanime couvrant le futur manifeste pilote n'existe encore | LOT41 pour isoler le chemin historique, LOT42 pour la revue à 100 % et la publication signée |
| R8 — chunker heading-aware et ré-ingestion | `bloquante_pilote` | partiellement résolue pour les notebooks, PDF encore en mode linéaire | le chunker structure le Markdown ; le rapport LOT25a limite explicitement la résolution aux notebooks et conserve le proxy PDF | LOT42 pour la ré-ingestion, LOT43 pour la qualité mesurée |
| R9 — `requirements-ingestion.txt` non versionné | `bloquante_pilote` | active sous ce nom et sans environnement d'ingestion intégralement scellé | aucun fichier `requirements-ingestion.txt` n'est suivi ; les exigences engine épinglent plusieurs paquets mais gardent notamment `psycopg` en plage | LOT43, manifeste déterministe des dépendances et artefacts |

Décompte : 12 `bloquante_pilote`, 5 `non_bloquante_avec_preuve`, 0
`hors_perimetre`. Aucune dette n'est masquée par un verdict vert de LOT37R.

## Topologie CI

Le graphe est désormais unidirectionnel : `scripts/audit/rag-pr-audit.sh` ne
contient aucun appel à `scripts/ci-local.sh`. La sentinelle
`NEXUS_CI_LOCAL_RUNNING` est testée et exportée avant la résolution de
`SCRIPT_DIR`, l'installation ou toute exécution de service. Les tests
comportementaux de topologie, hygiène, politique et fail-safe sont raccordés à
la CI locale ; le job distant `repository controls` exécute les mêmes portes de
dépôt.

| Contrôle | SHA-256 |
|---|---|
| `scripts/ci-local.sh` | `39e581aa79819c6f4254ccb51b78dca1b17d250872e469fca912ee9de0475dc5` |
| `scripts/audit/rag-pr-audit.sh` | `364495a03dc134a5e4d757231920cca9af8720612ed37918736af1d24e6e09ad` |
| `scripts/check-repository-hygiene.sh` | `0ff65849fd73d165c04820291248a167c6abb1b6e639a3d03798e4ce6ecc9281` |
| `scripts/tests/test-ci-local-topology.sh` | `bb1d285703292e412bce3594e197b48b628f2b3fb25b6bcbb75b893687ae4144` |
| `scripts/tests/test-ci-local-failsafe.sh` | `38244befc505b0a5a2022261d41af3893ba1e32086488f1a58f13149cc9b60c3` |
| `.github/workflows/ci.yml` | `2f18502100c616817620daa8cdd75713bc8b62930010ee385568893954dd0db2` |

## Protection de main

La politique versionnée a pour SHA-256
`950b967c022691c68c469b04cdb7be808a8d9e224c2f7bf1523fbf97813e64fb`.
Le GET live protège `main` au SHA
`b70c3eead488299672f057c366c7df32c4297f34` avec exactement six contextes,
`strict=true`, `enforce_admins=true`, historique linéaire et résolution des
conversations obligatoires. Les suppressions et force-pushes sont interdits,
les reviews de PR sont présentes avec zéro approbation générale requise, et
les trois listes de bypass sont vides.

Historique d'application, sans reconstruction de preuve : un unique PUT a été
émis depuis la tête précédente `2c7d47e51e48558f22f57c43d671b4bd373dbb77`,
après concordance avec le même SHA protégé de `main`. Le PUT a abouti, puis le
premier normaliseur a refusé la relecture parce que GitHub omettait le champ nul
`restrictions`. Aucun second PUT n'a été émis. Le journal stdout d'application
est donc vide et son SHA-256 est l'empreinte canonique du fichier vide,
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Le diagnostic stderr n'a pas été conservé dans un fichier ; aucun journal
d'erreur n'est inventé. L'unicité du PUT est donc une observation opérateur de
la session, non une propriété démontrable cryptographiquement faute de stdout ou
stderr d'application persistant. Le fait opérationnel consigné reste qu'aucun retry n'a été exécuté.
La preuve de l'état obtenu repose sur le readback brut, sa
normalisation durable et les checks GET-only, pas sur le journal vide.

Le correctif TDD `eb3a70bccb7e58712082bbf3af396bf2c89ffbe6` accepte uniquement
l'omission de ce champ nul. Ses 31 tests passent. Un check GET-only final est
vert. Les journaux GET-only de préflight et de contrôle final sont identiques ;
chacun a le SHA-256
`b199b4de4737e2df1922af7940d3798fcb0d838e9314b0346652a9f94233ddd9`.
La réponse brute GET reste hors Git et a le SHA-256
`a1ac6aa04be0a2fcd443e13a68d0faf3182eab0d1754cf55362298de3512f2dc` ;
sa forme gouvernée expurgée est versionnée avec le SHA-256
`d62a4ddddb6dc39a3e4d0eee816b96ee8f05a474af5bd61de023d6d75e0207c9`.

Le nombre d'approbations générales reste à zéro parce que le dépôt ne compte
qu'un collaborateur : exiger sa propre approbation rendrait toute PR
impossible à fusionner. La PR, les six checks stricts, l'inclusion des administrateurs et
la résolution des conversations restent obligatoires. Cette adaptation solo
ne remplace pas les décisions humaines : LOT41A, LOT43A et l'environnement
GitHub `production` demeurent des portes distinctes sans bypass.

## Matrice de preuve

La synthèse locale versionnée a le SHA-256
`c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` ;
elle a été comparée au journal brut SHA-256
`d6b2e39ea9c84aedb006b1dbd969b89e635fb901f73df82b90a5f2b3635d2ab7`.
La preuve PR versionnée correspond au run immuable initial de la tête de code
`eb3a70bccb7e58712082bbf3af396bf2c89ffbe6`. Son SHA-256 est
`b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` ;
hors seul ajout de `observedAt`, elle correspond à la capture normalisée source
SHA-256 `cf96bc37944d872a63a89c5a853d1c2f76a39b8cc7c9dc12ce4d9149020459f8`.
Les checks de la tête documentaire créée par le présent rapport seront attendus
après push et ne sont pas revendiqués par cette capture initiale.

| Critère | Propriétaire | Commande ou procédure | Environnement | Artefact | SHA-256 | Verdict |
|---|---|---|---|---|---|---|
| `packages/contracts` | auteur technique LOT37R | cible `packages/contracts` de `bash scripts/ci-local.sh` | worktree isolé au SHA `756aba8…`, Python 3.11, Node 22.22.0 | `evidence/lot_37r/ci-local-summary.txt` | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `services/rag-pedago` | auteur technique LOT37R | cible `services/rag-pedago` de la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `services/rag-engine` | auteur technique LOT37R | cible `services/rag-engine` de la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `services/cockpit` | auteur technique LOT37R | cible `services/cockpit` de la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `repository-hygiene` | auteur technique LOT37R | garde d'hygiène depuis la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `repository-hygiene-tests` | auteur technique LOT37R | tests comportementaux d'hygiène | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `ci-topology-tests` | auteur technique LOT37R | tests comportementaux de topologie | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `main-protection-policy-tests` | auteur technique LOT37R | tests unitaires de politique | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `governance-locks` | auteur technique LOT37R | garde des verrous depuis la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `taxonomy-validation` | auteur technique LOT37R | validation des taxonomies depuis la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `source-evidence-check` | auteur technique LOT37R | garde des preuves source depuis la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `governance-guard-tests` | auteur technique LOT37R | tests de réfutation des verrous | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `ci-failsafe-tests` | auteur technique LOT37R | tests fail-safe de la CI locale | même environnement local | même synthèse | `c7cff90e84b3768cb7041a92e29e3cb3b6b8d1a5931cae10e986730fcf4fafaa` | PASS |
| `governance locks guard` | GitHub Actions | job du [run 30666016165](https://github.com/cyranoaladin/RAG/actions/runs/30666016165) | événement `pull_request`, tête `eb3a70b…` | `evidence/lot_37r/pr-required-checks.json` | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| `packages/contracts` | GitHub Actions | job du même run immuable | même événement et tête | même preuve PR | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| `repository controls` | GitHub Actions | job du même run immuable | même événement et tête | même preuve PR | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| `services/cockpit` | GitHub Actions | job du même run immuable | même événement et tête | même preuve PR | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| `services/rag-engine` | GitHub Actions | job du même run immuable | même événement et tête | même preuve PR | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| `services/rag-pedago` | GitHub Actions | job du même run immuable | même événement et tête | même preuve PR | `b39cc94873b387103309c12e9ced07ae2cb3ce6626e2c597e54784d8df1fc219` | SUCCESS |
| Politique `main` | auteur technique LOT37R | `main_protection.py --check`, GET-only | GitHub, branche `main` au SHA protégé | `scripts/github/main-protection-policy.json`; `evidence/lot_37r/main-protection-readback.json`; journal GET-only final hors Git | politique `950b967c022691c68c469b04cdb7be808a8d9e224c2f7bf1523fbf97813e64fb`; readback `d62a4ddddb6dc39a3e4d0eee816b96ee8f05a474af5bd61de023d6d75e0207c9`; journal `b199b4de4737e2df1922af7940d3798fcb0d838e9314b0346652a9f94233ddd9` | PASS |

## Décision de livraison

La PR 80 ne peut être fusionnée que par squash, après checks finaux sur la tête
documentaire et revue indépendante du diff complet. LOT37R n'autorise ni
l'activation du pilote ni une promotion de gouvernance. Les PR 56 et 77 ne
seront fermées et leurs branches distantes supprimées qu'après la fusion du
remplacement, la réussite du run `main` exact et la preuve que leurs apports
retenus sont présents dans la source de vérité.
