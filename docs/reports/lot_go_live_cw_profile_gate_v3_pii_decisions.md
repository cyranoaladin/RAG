# Lot CW — décisions PII du candidat profile-gate V3

- Branche : `go-live/profile-gate-v3-pii-decisions`
- Base : `d7611667daef6af45c62e67afcd1db0fd5b3dc5d`
- Campagne : `pii-review-2026-09-22-profile-gate-v3`
- Index : `docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json`
- Empreinte de l'index : `abdd15256eba9ed5717529327131b0afe6f5de17189180bd082fd2a9bfeadb55`

## Portée

Ce lot versionne uniquement la forme canonique des décisions explicitement
validées pour les 22 paquets de la campagne V3, avec le rapport de lot exigé
par `AGENTS.md`. Il ne modifie ni la chaîne batch, ni ADR-0059, ni les verrous
de publication, de staging ou de production, ni aucun code. La protection du
point d'import (§ 4) est livrée dans une PR distincte, pour que le head soumis
à approbation ne porte que l'artefact de décisions.

La validation groupée a porté sur le fichier de propositions hors dépôt
`review-proposals-20260923.json`, SHA-256
`a0081af8bf402ecd1a5adadf9dfeacc4f0f9678d19dc2af849695f4a95f43efb`,
sans exception ni modification de contenu. L'import a utilisé
`revue_pii_cli.py --reponses` séparément pour chaque `content_sha256`.

## Résultat scellé

- Ensemble : `governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json`
- SHA-256 : `1b70d91b52d207d301d87076573593cb0899ed2b52d6e2963fbcf8fcd3472a66`
- `corpus_manifest_sha256` : `5ce13fac8b74e12ac9538a710b733aeb6a78f3d49434a44ac49e4c0b38296df7`
- `review_index_sha256` : `abdd15256eba9ed5717529327131b0afe6f5de17189180bd082fd2a9bfeadb55`
- 22 décisions documentaires `APPROVED`, 0 `REJECTED`
- 48 signalements disposés : 30 `FALSE_POSITIVE_TECHNICAL`,
  10 `SYNTHETIC_EXAMPLE`, 8 `PUBLIC_INSTITUTIONAL_DATA`, 0 `PERSONAL_DATA_PRESENT`
- 0 placeholder, 0 citation de matière brute (`raw_pii_quoted: false` partout)
- Horodatages réels d'import : du `2026-09-23T06:44:42.340848+00:00` au
  `2026-09-23T06:44:43.113820+00:00`, relecteur `abenrhouma`

Le scelleur canonique (`sceller_decisions_pii.py sceller`) a repris depuis
l'index les identités, instruments, empreintes de paquet, classes, comptes et
pages. Le brouillon et les paquets restent hors dépôt. Les jeux du 3 et du
17 septembre ne sont pas modifiés ; les dates et signatures du 3 septembre ne
sont pas reprises.

## Correction de métadonnée autorisée (2026-09-23)

Un premier scellement (`12271bc1ff0ec87efa247a217c75b8d01a0418824b1ae156d5f5ec5b98f971d6`)
portait `corpus_manifest_sha256 = d7e5caa5…4cc1e`. Il n'a été ni commité, ni
poussé, ni soumis en PR, ni couvert par un reçu. Il est conservé hors dépôt
comme preuve remplacée, sous un nom qui ne peut pas être pris pour le chemin
canonique.

**Deux mesures de la même autorité.** Le fichier
`services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/corpus_manifest_authority.json`
(octet pour octet identique à celui de `profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/`)
DÉCLARE `authority_sha256 = d7e5caa5…4cc1e` et a pour empreinte d'octets
`5ce13fac…96df7`. Le producteur (`build_production_profile_release.py`,
`corpus_manifest_authority_file_sha256()`) vérifie la déclaration puis projette
la revue contre l'empreinte du FICHIER ; les jeux du 3 et du 17 septembre
portent eux aussi `5ce13fac…96df7`. `d7e5…` reste la valeur correcte là où un
contrat attend l'autorité déclarée (`CORPUS_MANIFEST_AUTHORITY`) : elle n'a été
remplacée nulle part ailleurs.

**Origine de l'écart.** Le brouillon initial, créé par
`sceller_decisions_pii.py brouillon`, portait déjà `5ce13fac…`. L'import par
`revue_pii_cli.py` réécrit inconditionnellement ce champ avec son argument
`--corpus-manifest-sha256`, dont la valeur par défaut est `d7e5…` : la bonne
valeur a été écrasée silencieusement.

**Correction.** Seul le champ racine `corpus_manifest_sha256` du brouillon a
été remplacé (substitution d'une occurrence unique, écriture atomique, sans
relancer l'import), après sauvegarde du brouillon et du jeu provisoire
(permissions 600).

| Grandeur | Avant | Après |
|---|---|---|
| brouillon (octets) | `d7ae39f1b2587076945fcee3a5720bdd3da086d12090b6409b756a6af85affb5` | `d8af5564635d98bd5aa0262d883417d2a931e348e74caa6e739fcaf0a53ffb83` |
| `.decisions` du brouillon (`jq -S -c .decisions \| sha256sum`) | `c5d55a28e0afa2eed2328f3da87f1fbc693f707c772b8f9da4750c4215c41bb5` | `c5d55a28e0afa2eed2328f3da87f1fbc693f707c772b8f9da4750c4215c41bb5` |
| clés racine différentes | — | `corpus_manifest_sha256` seule |
| jeu scellé | `12271bc1…` | `1b70d91b…` |
| clés du jeu scellé différentes | — | `corpus_manifest_sha256` seule ; `decisions` égal |

Après correction, chaque décision a été recomparée individuellement aux
propositions validées (`a0081af8…`) et à l'index : même population de 22
contenus, mêmes 48 identifiants de signalements, mêmes dispositions, décisions,
catégories, justifications et horodatages ; aucun écart.

## Contrôles

- comparaison intégrale brouillon/propositions/index avant et après correction :
  22 contenus et 48 signalements identiques, aucun écart ;
- validation par `parse_pii_review_decision_set` : conforme au protocole
  `NEXUS-PII-REVIEW-DECISIONS-V1` ;
- liaison au producteur V3, sans reçu : `project_pii_review` appelé avec
  `corpus_manifest_sha256 = corpus_manifest_authority_file_sha256()` (valeur
  calculée par le producteur sur son chemin effectif) et un scan reconstruit
  depuis les constats de l'INDEX, plus 293 contenus propres :
  315 scannés, 22 détectés, 22 revus acceptés, 293 dégagés, 315 autorisés,
  0 rejeté, 0 quarantaine ;
- contre-épreuve : le jeu remplacé `12271bc1…` est refusé par la même
  projection (« the decisions describe another corpus ») ;
- contrôle restant, impossible honnêtement avant le reçu :
  `verify_pii_review_decision_authority` (reçu ADR-0035, ancre, relecteur,
  dépôt), puis la construction gouvernée complète du successeur V3.

Résultats de la CI locale : § CI ci-dessous.

## Autorités restant distinctes

Produire le JSON canonique et son empreinte n'accomplit ni la revue GitHub, ni
la signature du reçu, ni l'activation d'une autorité. La validation de saisie
ne vaut ni review GitHub ni reçu ADR-0035. La PR doit être approuvée par le
reviewer de confiance sur son HEAD exact avec le challenge
`NEXUS-TRUSTED-REVIEW-V1`. Le reçu
`governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json`
ne pourra être émis qu'après cette approbation, avec la clé privée injectée par
son détenteur ; aucune clé n'est stockée ou affichée par ce lot.

Jusqu'à ce reçu valide, ce jeu ne doit autoriser ni construction gouvernée de
V3, ni publication, ni activation staging, ni déploiement de production.

## CI

Exécutée sur `62a91d5716edb1349b2ad689eaa1bb006e4650ac` (le commit de
l'artefact ; ce rapport seul change ensuite), cible par cible, avec les mêmes
commandes que `scripts/ci-local.sh`. Le script n'a pas été lancé d'un bloc : il
détruit et réinstalle les venvs (~12 Go) alors que le disque n'avait que
2,6 Go libres, au risque de saturer le volume du conteneur
`nexus-drive-staging-restored-20260917`. Espace libéré dans le seul périmètre du
dépôt (retrait du worktree fusionné `lot-cv-snapshot`), puis rag-engine
réinstallé depuis zéro. rag-pedago a été testé dans son venv existant, installé
en éditable depuis ce worktree (`pip check` propre).

| Cible | Résultat |
|---|---|
| packages/contracts | 934 réussis |
| packages/pdf-page-policy | 23 réussis |
| packages/release-chain | import OK |
| services/rag-pedago | lint, mypy, 3552 réussis, 4 ignorés |
| services/rag-engine | install neuve, lint, mypy, tests, `LOT40_HYBRID_INTEGRATION=PASS` |
| services/cockpit | npm ci, lint, tests, build, audits, cohérence, build propre |
| governance-locks | 18/18 verrous inchangés |
| authority-uniqueness (+ garde) | vert |
| repository-hygiene (+ tests), ci-topology, main-protection, evidence-refresh | vert |
| trusted-human-review core / github / workflow | vert |
| taxonomy-validation, source-evidence-check | vert |
| qualification-c1 | 404 réussis, 3 ignorés |
| governance-guard-tests, ci-failsafe-tests | vert |
| go-live-readiness-gate | **rouge** : 4 échecs, 94 réussis |
| script-tests | **rouge** : les mêmes 4 échecs, 534 réussis, 7 ignorés |

Les 4 échecs (`test_go_live_readiness.py`) ont une cause unique :
`disk_policy_ok` (seuil de 40 Go libres ; 19 à 28 Go pendant le run). Rejoués
sur le parent `d7611667` : mêmes 4 échecs, même cause. Préexistants et
environnementaux, tracés dans `docs/reports/lot_go_live_cw_dettes.md`.
