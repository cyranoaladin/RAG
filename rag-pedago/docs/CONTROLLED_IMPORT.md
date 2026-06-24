# Controlled manifest import

L'import contrôlé est la seule commande prévue pour écrire des métadonnées de manifests dans le ledger après les rapports de décision. Il exécute obligatoirement le gate avant toute écriture.

## Différence avec import_manifest_dir

`import_manifest_dir` importe un dossier de manifests dans le ledger avec une politique qualité. L'import contrôlé ajoute une étape obligatoire :

1. exécuter readiness ;
2. exécuter coverage ;
3. calculer le gate ;
4. écrire dans le ledger uniquement si le gate vaut `ready_for_controlled_import`.

## Gate obligatoire

Si le gate vaut `blocked` ou `review_required`, l'import contrôlé retourne `blocked_by_gate`. Dans ce cas, il n'initialise pas la base, ne crée aucun run, n'écrit aucun document, n'écrit aucun état et n'enregistre aucune erreur.

## Gate prêt

Si le gate vaut `ready_for_controlled_import`, l'import contrôlé lance l'import de manifests existant. Les écritures restent limitées au ledger SQLite : runs, documents, états et erreurs de manifest. Aucun document source n'est ouvert.

## Rapports

La commande écrit :

- `gate_<batch_id>.md/json` ;
- `controlled_import_<batch_id>.md/json` ;
- le rapport d'import de répertoire si l'import est autorisé.

## Garanties

- le gate est évalué avant import ;
- aucun `source_uri` n'est ouvert ;
- aucun appel réseau n'est effectué ;
- aucun parsing documentaire n'est effectué ;
- aucun PDF n'est lu ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Limites

Ce lot importe uniquement des métadonnées déclarées dans les manifests JSONL. Il ne vérifie pas l'existence des documents sources et ne valide pas leur contenu réel. Le parsing documentaire reste interdit jusqu'à un lot dédié.

## Gate et référentiel officiel

Depuis le lot 10, l'import contrôlé dépend aussi des références officielles.
Si le gate bloque à cause d'un `official_level_ref`, `official_exam_ref`,
`official_subject_ref`, `candidate_status_ref`, `official_source_refs` ou
`official_claim_refs` invalide, aucune écriture ledger n'est effectuée.

## Profils officiels validés

Le batch `data/fixtures/manifests/batch_official_profiles_clean/` prouve le
chemin nominal sur plusieurs profils Nexus : DNB scolaire, DNB candidat
individuel, seconde GT, EAF, épreuve anticipée de mathématiques, spécialités,
philosophie, Grand oral, candidat individuel au bac, AEFE scolarisé et double
cursus.

Ces manifests restent metadata-only. Même lorsqu'ils sont importés, l'import
contrôlé n'ouvre aucun `source_uri` et ne lit aucun document pédagogique.

## Explicabilité des blocages

Si le gate bloque à cause d'une source ou claim incompatible, le rapport
controlled import reprend la section `Official reference compatibility` avec :

- `doc_id` ;
- `ref_id` ;
- `document_refs` ;
- `reason`.

Le JSON contient aussi `official_reference_compatibility`. Ces explications
restent limitées aux métadonnées déclarées dans les manifests.

## Revue humaine obligatoire

Depuis le lot 12, l'import contrôlé peut exiger une décision de revue :

- `--require-review` ;
- `--review-decision data/reviews/review_<id>.json`.

La décision doit être `approved`, porter le même `batch_id` et contenir un
`gate_json_sha256` identique au gate recalculé. Si les manifests changent après
approbation, l'import est bloqué avant toute écriture ledger.

Depuis le lot 12.5, `--require-review` exige aussi `--review-package`. L'import
vérifie :

- le hash canonique du review package ;
- les hashes des manifests ;
- le hash du référentiel officiel ;
- les hashes des taxonomies ;
- le hash du JSON gate.

Le rapport controlled import expose les booléens :

- `Review package hash verified` ;
- `Official reference hash verified` ;
- `Taxonomy hash verified` ;
- `Manifest hashes verified`.

## Audit ledger

Depuis le lot 13, `controlled_import_cli` accepte `--audit-ledger`. Une tentative
est alors enregistrée dans SQLite avec ses vérifications.

Si le gate bloque, l'audit peut être écrit mais aucune écriture documentaire
n'est faite : pas de run d'import, pas de document, pas d'état et pas d'erreur
de manifest.

Si l'import est autorisé, l'audit conserve les `run_ids`, les chemins des
rapports et le lien éventuel vers `review_id` et `package_id`.
